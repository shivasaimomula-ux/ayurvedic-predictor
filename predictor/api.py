"""FastAPI service exposing the predictive model.

Run:  uvicorn predictor.api:app --reload --port 8000
Port 8000 is the Stage A contract (F posts here). Do not move without updating F.

Async jobs (Task T18 / Finding #20):
  POST /jobs/predict  → 202 {job_id}; GET /jobs/{id} polls progress/result.
  POST /predict stays synchronous for backward compatibility (glue / F).
  Stage A UI polls its own jobs — not a mega dashboard.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, contract_gate, jobs, pipeline

app = FastAPI(
    title="Ayurvedic Predictive Model",
    version="0.3.0",
    description=(
        "Stage A recommender. Accepts F SymptomSpec handoff via `context` "
        "(spec_id, confidence_floor, safety) and emits C FormulationInput "
        "(`formulation_input`, modernized_sku=null) plus B FormulationSpec "
        "(`formulation_spec`) when HB-* identity and quantity_mg resolve; "
        "otherwise formulation_spec is null with formulation_spec_error. "
        "Prefer POST /jobs/predict + poll for long runs; POST /predict remains "
        "for sync callers."
    ),
)

# web/ sits next to the predictor/ package at the project root.
_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


class PredictRequest(BaseModel):
    query: str
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional Stage F handoff: spec_id, confidence_floor, jurisdiction, "
            "safety, symptom_spec. Consumed for audit/propagation; "
            "confidence_floor is never raised."
        ),
    )
    timeout_s: Optional[float] = Field(
        default=None,
        description="Optional per-job wall-clock budget (async path only).",
        ge=5,
        le=3600,
    )


def _finalize_predict_result(
    result: Any,
    context: Optional[Dict[str, Any]],
) -> Any:
    """Apply T6/T11 contract gates and F floor propagation on predict envelopes."""
    # Audit Finding #1 — validate F SymptomSpec at the HTTP boundary when present.
    contract_gate.validate_inbound_context(context)
    fi = result.get("formulation_input") if isinstance(result, dict) else None
    if isinstance(fi, dict):
        # Propagate F floor into FormulationInput for C; never raise.
        intake_floor = None
        if isinstance(context, dict):
            intake_floor = context.get("confidence_floor")
            nested = context.get("symptom_spec")
            if intake_floor is None and isinstance(nested, dict):
                intake_floor = nested.get("confidence_floor")
        if intake_floor is not None and fi.get("inherited_confidence") is None:
            fi = {
                **fi,
                "inherited_confidence": float(intake_floor),
                "confidence_floor": float(
                    fi.get("confidence_floor")
                    if fi.get("confidence_floor") is not None
                    else intake_floor
                ),
            }
            result = {**result, "formulation_input": fi}
        contract_gate.validate_outbound_formulation_input(fi)
    fs = result.get("formulation_spec") if isinstance(result, dict) else None
    if isinstance(fs, dict):
        contract_gate.validate_outbound_formulation_spec(fs)
    return result


@app.get("/health")
def health():
    from . import claim_verifier

    verifier = claim_verifier.describe_verifier_config()
    adjudication_reachable = False
    if config.ADJUDICATION_PREFERRED:
        try:
            from .adjudication_client import AdjudicationClient
            adjudication_reachable = AdjudicationClient().is_reachable()
        except Exception:  # noqa: BLE001
            adjudication_reachable = False
    return {"status": "ok", "llm_available": config.llm_available(),
            "generator": config.GENERATOR_MODEL, "verifier": config.VERIFIER_MODEL,
            "escalate_model": config.ESCALATE_MODEL,
            "verifier_usable": config.verifier_usable(),
            "cost_order": verifier["cost_order"],
            "cheap_available": verifier["cheap_available"],
            "default_verifier_is_claude": verifier["default_verifier_is_claude"],
            "adjudication_url": config.ADJUDICATION_URL,
            "adjudication_preferred": config.ADJUDICATION_PREFERRED,
            "adjudication_reachable": adjudication_reachable,
            "cross_model": config.is_cross_model(),
            "cross_provider": config.is_cross_provider(),
            "max_iterations": config.MAX_ITERATIONS,
            "port_contract": 8000,
            "formulation_export": True,
            "formulation_spec_export": True,
            "contracts": "herbenzo-contracts",
            "async_jobs": True,
            "predict_job_timeout_s": config.PREDICT_JOB_TIMEOUT_S,
            "predict_max_concurrent_jobs": config.PREDICT_MAX_CONCURRENT_JOBS}


@app.post("/predict")
def predict(req: PredictRequest):
    """Synchronous predict (backward compatible). Prefer /jobs/predict for UIs."""
    result = pipeline.predict(req.query, req.context)
    return _finalize_predict_result(result, req.context)


@app.post("/jobs/predict", status_code=202)
def submit_predict_job(
    req: PredictRequest,
    response: Response,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Submit async predict; poll GET /jobs/{job_id} for progress/result."""
    # Validate inbound SymptomSpec at submit time (same gate as sync /predict).
    contract_gate.validate_inbound_context(req.context)
    rec = jobs.STORE.submit_predict(
        query=req.query,
        context=req.context,
        idempotency_key=idempotency_key,
        timeout_s=req.timeout_s,
    )
    view = jobs.STORE.public_view(rec)
    response.headers["Location"] = view["poll_url"]
    return view


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    rec = jobs.STORE.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return jobs.STORE.public_view(rec)


@app.get("/jobs/{job_id}/result")
def get_job_result(job_id: str):
    """Convenience: 200 + result when succeeded; 409 while in flight; 4xx on fail."""
    rec = jobs.STORE.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    if rec.status in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Job not finished",
                "status": rec.status,
                "progress": {
                    "stage": rec.progress_stage,
                    "percent": rec.progress_percent,
                    "message": rec.progress_message,
                },
            },
        )
    if rec.status == "succeeded":
        # Apply outbound contract gates to async results (parity with /predict).
        return _finalize_predict_result(rec.result, None)
    raise HTTPException(
        status_code=422,
        detail={"message": rec.error or "Job failed", "status": rec.status},
    )


# Serve the web UI at "/". Mounted LAST so API routes take priority.
if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
