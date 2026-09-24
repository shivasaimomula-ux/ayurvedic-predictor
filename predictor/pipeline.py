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
  - Also emit B-shaped `formulation_spec` when HB-* identity + quantity_mg
    resolve; otherwise formulation_spec=null with a clear error (do not invent).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Dict, List, Optional

from . import (
    config,
    agents,
    knowledge_graph,
    f_context,
    formulation_export,
    formulation_spec_export,
)
from .connectors import pubchem

ProgressCb = Callable[[str, int, str, Optional[Dict[str, Any]]], None]


def _now() -> str:
    return _dt.datetime.utcnow().isoformat() + "Z"


def _grade_label(evidence: List[Dict]) -> str:
    """Return the actual evidence_level of the strongest supporting article."""
    if not evidence:
        return "none"
    best = max(evidence, key=lambda e: config.EVIDENCE_RANK.get(e.get("evidence_level", "unknown"), 0))
    return best.get("evidence_level", "unknown")


def _progress(
    cb: ProgressCb | None,
    stage: str,
    percent: int,
    message: str,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    if cb is None:
        return
    try:
        cb(stage, percent, message, detail)
    except Exception:  # noqa: BLE001 — progress must never break predict
        pass


def predict(
    user_input: str,
    context: Dict | None = None,
    *,
    on_progress: ProgressCb | None = None,
) -> Dict:
    intake = f_context.consume_f_context(context)
    audit: List[Dict] = []

    def log(stage, **data):
        audit.append({"ts": _now(), "stage": stage, **data})

    log("f_context", **f_context.audit_event(intake))
    _progress(on_progress, "interpret", 5, "Interpreting symptom…")

    # --- Stage 1 ------------------------------------------------------------
    interp = agents.interpret(user_input)
    condition = interp.get("normalized_condition", user_input)
    log("interpret", result=interp)

    # --- Stage 2 ------------------------------------------------------------
    _progress(on_progress, "candidates", 15, "Generating candidates…")
    # Live volume path: never serve fixture/mock predict results. Optional
    # A_FORCE_AI_PROPOSE=1 skips curated KG so propose LLM always runs.
    if config.FORCE_AI_PROPOSE:
        cand = {"condition_key": None, "ayurvedic_frame": None, "candidates": []}
        skipped_curated = True
    else:
        cand = knowledge_graph.generate_candidates(user_input)
        skipped_curated = False
    source = "curated"
    propose_ran = False

    # Open fallback: if the curated KG has no match, let the generator propose a
    # candidate. Its claims are STILL verified below, so this widens coverage to
    # any symptom without weakening the no-fabrication guarantee.
    if not cand["candidates"]:
        proposed = agents.propose_candidate(user_input, interp)
        propose_ran = True
        if proposed:
            cand = {"condition_key": None,
                    "ayurvedic_frame": proposed.get("ayurvedic_frame"),
                    "candidates": [proposed]}
            source = "ai_proposed"

    log("candidate_generation", condition_key=cand["condition_key"],
        source=source, n_candidates=len(cand["candidates"]),
        force_ai_propose=bool(config.FORCE_AI_PROPOSE),
        skipped_curated=skipped_curated, propose_ran=propose_ran)

    if not cand["candidates"]:
        _progress(on_progress, "done", 100, "No candidates")
        return _envelope(user_input, interp, "insufficient_evidence", None, [],
                         audit, source=source, f_intake=intake,
                         note="Could not generate any candidate formulation for this input.",
                         propose_ran=propose_ran, skipped_curated=skipped_curated)

    # MVP: evaluate the top candidate. (Extend to rank multiple candidates.)
    candidate = cand["candidates"][0]

    # --- Stage 3: evidence loop per claim -----------------------------------
    claims = list(candidate.get("claims") or [])
    claim_results = []
    for idx, claim in enumerate(claims):
        pct = 20 + int(55 * ((idx + 1) / max(1, len(claims))))
        _progress(
            on_progress,
            "evidence",
            pct,
            f"Verifying claim {idx + 1}/{len(claims)}…",
            {"claim_index": idx, "claim_total": len(claims), "claim": claim},
        )
        res = agents.evidence_loop(claim, condition)
        claim_results.append(res)
        log("evidence_loop", claim=claim, status=res["status"],
            iterations=res["iterations_used"],
            supporting=[e["pmid"] for e in res["evidence"]])

    supported = [c for c in claim_results if c["status"] == "supported"]
    all_evidence = [e for c in claim_results for e in c["evidence"]]

    # --- Stage 4: justification + safety (chemistry grounding) --------------
    _progress(on_progress, "chemistry", 80, "Grounding chemistry (PubChem)…")
    chemistry = []
    for name in candidate.get("phytochemicals", []):
        info = pubchem.compound(name)
        if info:
            chemistry.append(info)
    log("chemistry_grounding", resolved=[c["name"] for c in chemistry])

    # --- Stage 5: synthesis -------------------------------------------------
    # A recommendation requires at least one fully-substantiated claim.
    _progress(on_progress, "synthesize", 90, "Synthesizing recommendation…")
    if not supported:
        _progress(on_progress, "done", 100, "Insufficient evidence")
        return _envelope(user_input, interp, "insufficient_evidence", candidate,
                         all_evidence, audit, source=source, f_intake=intake,
                         note="No candidate claim could be substantiated with graded PubMed evidence.",
                         propose_ran=propose_ran, skipped_curated=skipped_curated)

    outcome = {
        "formula": candidate["formula"],
        "formulation": candidate["formulation"],
        "delivery_system": candidate["delivery"],
        "herbs": candidate["herbs"],
        "ayurvedic_frame": agents._frame_to_str(cand.get("ayurvedic_frame"))
            or agents._frame_to_str(candidate.get("ayurvedic_frame")),
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
    formulation_spec, formulation_spec_error = (
        formulation_spec_export.try_formulation_spec(outcome, f_intake=intake)
    )
    log("formulation_export",
        product_name=formulation_input.get("product_name"),
        n_ingredients=len(formulation_input.get("ingredients") or []),
        modernized_sku=formulation_input.get("modernized_sku"),
        formulation_spec=bool(formulation_spec),
        formulation_spec_error=(
            (formulation_spec_error or {}).get("message")
            if formulation_spec_error
            else None
        ))
    _progress(on_progress, "done", 100, "Complete")
    return _envelope(user_input, interp, "recommendation", candidate, all_evidence,
                     audit, outcome=outcome, source=source, f_intake=intake,
                     formulation_input=formulation_input,
                     formulation_spec=formulation_spec,
                     formulation_spec_error=formulation_spec_error,
                     propose_ran=propose_ran, skipped_curated=skipped_curated)


def _live_path_summary(
    interp: Dict,
    source: str,
    evidence: List[Dict],
    audit: List[Dict],
    *,
    propose_ran: bool,
    skipped_curated: bool,
) -> Dict[str, Any]:
    """Operator-facing proof that this response was not a fixture replay."""
    interpret_llm = bool(interp.get("_llm")) if isinstance(interp, dict) else False
    verified_by = sorted({
        str(e.get("verified_by"))
        for e in evidence
        if e.get("verified_by")
    })
    pubmed_iterations = 0
    pubmed_retrieved = 0
    for ev in audit:
        if ev.get("stage") != "evidence_loop":
            continue
        # Prefer trail on claim results if present in nested structures later;
        # audit only stores status — count supporting PMIDs as evidence activity.
        pubmed_retrieved += len(ev.get("supporting") or [])
        pubmed_iterations += int(ev.get("iterations") or 0)
    degraded = (not interpret_llm) or (
        source == "ai_proposed" and not propose_ran
    )
    return {
        "mode": "live",
        "interpret_llm": interpret_llm,
        "candidate_source": source,
        "propose_ran": propose_ran,
        "force_ai_propose": bool(config.FORCE_AI_PROPOSE),
        "skipped_curated": skipped_curated,
        "pubmed_evidence_iterations": pubmed_iterations,
        "n_supporting_pmids": len({e.get("pmid") for e in evidence if e.get("pmid")}),
        "verified_by": verified_by,
        "degraded": degraded,
        "note": (
            "PubMed PMID disk cache may speed retrieval; LLMs still run. "
            "No predict-job response fixture cache on the volume path."
        ),
    }


def _envelope(user_input, interp, status, candidate, evidence, audit,
              outcome=None, note=None, source="curated",
              f_intake=None, formulation_input=None,
              formulation_spec=None, formulation_spec_error=None,
              propose_ran: bool = False, skipped_curated: bool = False) -> Dict:
    f_intake = f_intake or {}
    # Refuse → never invent a FormulationInput for C or FormulationSpec for B.
    if status != "recommendation":
        formulation_input = None
        formulation_spec = None
        formulation_spec_error = None
    thread = None
    if formulation_input and isinstance(formulation_input.get("provenance_thread"), dict):
        thread = formulation_input["provenance_thread"]
    elif f_intake:
        from . import formulation_export as _fe

        thread = _fe.build_provenance_thread(f_intake)
    # Early-return paths (no candidates) never set propose_ran locals — infer.
    if not propose_ran:
        for ev in audit:
            if ev.get("stage") == "candidate_generation" and ev.get("propose_ran"):
                propose_ran = True
                skipped_curated = bool(ev.get("skipped_curated"))
                break
    live_path = _live_path_summary(
        interp, source, evidence, audit,
        propose_ran=propose_ran, skipped_curated=skipped_curated,
    )
    return {
        "input": user_input,
        "interpretation": interp,
        "status": status,                 # "recommendation" | "insufficient_evidence"
        "source": source,                 # "curated" | "ai_proposed"
        "outcome": outcome,
        "formulation_input": formulation_input,  # C handoff; null on refusal / B skip null SKU
        "formulation_spec": formulation_spec,  # B handoff; null when identity/dose incomplete
        "formulation_spec_error": formulation_spec_error,
        "f_context": {
            "spec_id": f_intake.get("spec_id"),
            "spec_version": f_intake.get("spec_version"),
            "source": f_intake.get("source"),
            "jurisdiction": f_intake.get("jurisdiction"),
            "confidence_floor": f_intake.get("confidence_floor"),
            "safety": f_intake.get("safety"),
            "has_symptom_spec": f_intake.get("has_symptom_spec", False),
            "provenance_thread": thread or f_intake.get("provenance_thread"),
        },
        "provenance_thread": thread or f_intake.get("provenance_thread"),
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
        "live_path": live_path,
        "disclaimer": config.DISCLAIMER,
        "audit_trail": audit,
    }
