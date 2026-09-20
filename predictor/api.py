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

from . import config, pipeline

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
            "formulation_export": True}


@app.post("/predict")
def predict(req: PredictRequest):
    return pipeline.predict(req.query, req.context)


# Serve the web UI at "/". Mounted LAST so /health and /predict take priority.
if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
