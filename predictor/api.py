"""FastAPI service exposing the predictive model.

Run:  uvicorn predictor.api:app --reload --port 8000
Port 8000 is the Stage A contract (F posts here). Do not move without updating F.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, contract_gate, pipeline

app = FastAPI(
    title="Ayurvedic Predictive Model",
    version="0.2.0",
    description=(
        "Stage A recommender. Accepts F SymptomSpec handoff via `context` "
        "(spec_id, confidence_floor, safety) and emits C FormulationInput "
        "(`formulation_input`, modernized_sku=null) on recommendation."
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


@app.get("/health")
def health():
    return {"status": "ok", "llm_available": config.llm_available(),
            "generator": config.GENERATOR_MODEL, "verifier": config.VERIFIER_MODEL,
            "verifier_usable": config.verifier_usable(),
            "cross_model": config.is_cross_model(),
            "cross_provider": config.is_cross_provider(),
            "max_iterations": config.MAX_ITERATIONS,
            "port_contract": 8000,
            "formulation_export": True,
            "contracts": "herbenzo-contracts"}


@app.post("/predict")
def predict(req: PredictRequest):
    # Audit Finding #1 — validate F SymptomSpec at the HTTP boundary when present.
    contract_gate.validate_inbound_context(req.context)
    result = pipeline.predict(req.query, req.context)
    fi = result.get("formulation_input") if isinstance(result, dict) else None
    if isinstance(fi, dict):
        # Propagate F floor into FormulationInput for C; never raise.
        intake_floor = None
        if isinstance(req.context, dict):
            intake_floor = req.context.get("confidence_floor")
            nested = req.context.get("symptom_spec")
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
    return result


# Serve the web UI at "/". Mounted LAST so /health and /predict take priority.
if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
