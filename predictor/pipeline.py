"""Orchestrator: runs the full predict -> substantiate pipeline.

Stages (see architecture diagram):
  1. dual interpretation
  2. knowledge-graph candidate generation
  3. agentic evidence loop per claim (retrieve -> verify -> escalate)
  4. justification + safety (PubChem chemistry grounding)
  5. synthesis -> graded recommendation OR honest "insufficient evidence"
Everything is recorded in an append-only audit trail.

Handoffs (functional pipeline hardening):
  - F context (spec_id, confidence_floor, safety) is consumed and echoed;
    confidence_floor is never raised.
  - On recommendation, emit C-shaped `formulation_input` with modernized_sku=null.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List

from . import config, agents, knowledge_graph, f_context, formulation_export
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
    intake = f_context.consume_f_context(context)
    audit: List[Dict] = []

    def log(stage, **data):
        audit.append({"ts": _now(), "stage": stage, **data})

    log("f_context", **f_context.audit_event(intake))

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
                         audit, source=source, f_intake=intake,
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
                         all_evidence, audit, source=source, f_intake=intake,
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
        # Propagate F floor unchanged — A has no numeric confidence to raise.
        "confidence_floor": intake.get("confidence_floor"),
        "spec_id": intake.get("spec_id"),
        "safety": intake.get("safety"),
    }
    formulation_input = formulation_export.to_formulation_input(
        outcome, f_intake=intake
    )
    log("formulation_export",
        product_name=formulation_input.get("product_name"),
        n_ingredients=len(formulation_input.get("ingredients") or []),
        modernized_sku=formulation_input.get("modernized_sku"))
    return _envelope(user_input, interp, "recommendation", candidate, all_evidence,
                     audit, outcome=outcome, source=source, f_intake=intake,
                     formulation_input=formulation_input)


def _envelope(user_input, interp, status, candidate, evidence, audit,
              outcome=None, note=None, source="curated",
              f_intake=None, formulation_input=None) -> Dict:
    f_intake = f_intake or {}
    # Refuse → never invent a FormulationInput for C.
    if status != "recommendation":
        formulation_input = None
    return {
        "input": user_input,
        "interpretation": interp,
        "status": status,                 # "recommendation" | "insufficient_evidence"
        "source": source,                 # "curated" | "ai_proposed"
        "outcome": outcome,
        "formulation_input": formulation_input,  # C handoff; null on refusal / B skip null SKU
        "f_context": {
            "spec_id": f_intake.get("spec_id"),
            "spec_version": f_intake.get("spec_version"),
            "source": f_intake.get("source"),
            "jurisdiction": f_intake.get("jurisdiction"),
            "confidence_floor": f_intake.get("confidence_floor"),
            "safety": f_intake.get("safety"),
            "has_symptom_spec": f_intake.get("has_symptom_spec", False),
        },
        "note": note,
        "n_citations": len({e["pmid"] for e in evidence}),
        "models": {
            "generator": config.GENERATOR_MODEL,
            "verifier": config.VERIFIER_MODEL,
            "escalate": config.ESCALATE_MODEL,
            "cost_order": list(config.VERIFIER_COST_ORDER),
            "cross_model": config.is_cross_model(),
            "cross_provider": config.is_cross_provider(),
        },
        "disclaimer": config.DISCLAIMER,
        "audit_trail": audit,
    }
