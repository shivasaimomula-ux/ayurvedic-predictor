"""Orchestrator: runs the full predict -> substantiate pipeline.

Stages (see architecture diagram):
  1. dual interpretation
  2. knowledge-graph candidate generation
  3. agentic evidence loop per claim (retrieve -> verify -> escalate)
  4. justification + safety (PubChem chemistry grounding)
  5. synthesis -> graded recommendation OR honest "insufficient evidence"
Everything is recorded in an append-only audit trail.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List

from . import config, agents, knowledge_graph
from .connectors import pubchem


def _now() -> str:
    return _dt.datetime.utcnow().isoformat() + "Z"


def _grade_label(evidence: List[Dict]) -> str:
    """Return the actual evidence_level of the strongest supporting article."""
    if not evidence:
        return "none"
    best = max(evidence, key=lambda e: config.EVIDENCE_RANK.get(e.get("evidence_level", "unknown"), 0))
    return best.get("evidence_level", "unknown")


def predict(user_input: str, context: Dict | None = None) -> Dict:
    context = context or {}
    audit: List[Dict] = []

    def log(stage, **data):
        audit.append({"ts": _now(), "stage": stage, **data})

    # --- Stage 1 ------------------------------------------------------------
    interp = agents.interpret(user_input)
    condition = interp.get("normalized_condition", user_input)
    log("interpret", result=interp)

    # --- Stage 2 ------------------------------------------------------------
    cand = knowledge_graph.generate_candidates(user_input)
    source = "curated"

    # Open fallback: if the curated KG has no match, let the generator propose a
    # candidate. Its claims are STILL verified below, so this widens coverage to
    # any symptom without weakening the no-fabrication guarantee.
    if not cand["candidates"]:
        proposed = agents.propose_candidate(user_input, interp)
        if proposed:
            cand = {"condition_key": None,
                    "ayurvedic_frame": proposed.get("ayurvedic_frame"),
                    "candidates": [proposed]}
            source = "ai_proposed"

    log("candidate_generation", condition_key=cand["condition_key"],
        source=source, n_candidates=len(cand["candidates"]))

    if not cand["candidates"]:
        return _envelope(user_input, interp, "insufficient_evidence", None, [],
                         audit, source=source,
                         note="Could not generate any candidate formulation for this input.")

    # MVP: evaluate the top candidate. (Extend to rank multiple candidates.)
    candidate = cand["candidates"][0]

    # --- Stage 3: evidence loop per claim -----------------------------------
    claim_results = []
    for claim in candidate["claims"]:
        res = agents.evidence_loop(claim, condition)
        claim_results.append(res)
        log("evidence_loop", claim=claim, status=res["status"],
            iterations=res["iterations_used"],
            supporting=[e["pmid"] for e in res["evidence"]])

    supported = [c for c in claim_results if c["status"] == "supported"]
    all_evidence = [e for c in claim_results for e in c["evidence"]]

    # --- Stage 4: justification + safety (chemistry grounding) --------------
    chemistry = []
    for name in candidate.get("phytochemicals", []):
        info = pubchem.compound(name)
        if info:
            chemistry.append(info)
    log("chemistry_grounding", resolved=[c["name"] for c in chemistry])

    # --- Stage 5: synthesis -------------------------------------------------
    # A recommendation requires at least one fully-substantiated claim.
    if not supported:
        return _envelope(user_input, interp, "insufficient_evidence", candidate,
                         all_evidence, audit, source=source,
                         note="No candidate claim could be substantiated with graded PubMed evidence.")

    outcome = {
        "formula": candidate["formula"],
        "formulation": candidate["formulation"],
        "delivery_system": candidate["delivery"],
        "herbs": candidate["herbs"],
        "ayurvedic_frame": cand["ayurvedic_frame"],
        "source": source,
        "ai_proposed": source == "ai_proposed",
        "substantiated_claims": [
            {
                "claim": c["claim"],
                "evidence_grade": _grade_label(c["evidence"]),
                "citations": [
                    {"pmid": e["pmid"], "url": e["url"], "title": e.get("title", ""),
                     "year": e.get("year", ""), "evidence_level": e.get("evidence_level"),
                     "support_quote": e.get("support_quote", ""),
                     "verified_by": e.get("verified_by")}
                    for e in c["evidence"]
                ],
            } for c in supported
        ],
        "unsubstantiated_claims": [c["claim"] for c in claim_results if c["status"] != "supported"],
        "chemistry": chemistry,
        "overall_evidence_grade": _grade_label(all_evidence),
    }
    return _envelope(user_input, interp, "recommendation", candidate, all_evidence,
                     audit, outcome=outcome, source=source)


def _envelope(user_input, interp, status, candidate, evidence, audit,
              outcome=None, note=None, source="curated") -> Dict:
    return {
        "input": user_input,
        "interpretation": interp,
        "status": status,                 # "recommendation" | "insufficient_evidence"
        "source": source,                 # "curated" | "ai_proposed"
        "outcome": outcome,
        "note": note,
        "n_citations": len({e["pmid"] for e in evidence}),
        "models": {
            "generator": config.GENERATOR_MODEL,
            "verifier": config.VERIFIER_MODEL,
            "cross_model": config.is_cross_model(),
            "cross_provider": config.is_cross_provider(),
        },
        "disclaimer": config.DISCLAIMER,
        "audit_trail": audit,
    }
