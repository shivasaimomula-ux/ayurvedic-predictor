"""FastAPI service exposing the predictive model.

Run:  uvicorn predictor.api:app --reload --port 8000
"""
from __future__ import annotations

import os
from typing import Optional, Dict

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, pipeline

app = FastAPI(title="Ayurvedic Predictive Model", version="0.1.0")

# web/ sits next to the predictor/ package at the project root.
_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


class PredictRequest(BaseModel):
    query: str
    context: Optional[Dict] = None


@app.get("/health")
def health():
    return {"status": "ok", "llm_available": config.llm_available(),
            "generator": config.GENERATOR_MODEL, "verifier": config.VERIFIER_MODEL,
            "verifier_usable": config.verifier_usable(),
            "cross_model": config.is_cross_model(),
            "cross_provider": config.is_cross_provider(),
            "max_iterations": config.MAX_ITERATIONS}


@app.post("/predict")
def predict(req: PredictRequest):
    return pipeline.predict(req.query, req.context)


# Serve the web UI at "/". Mounted LAST so /health and /predict take priority.
if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
