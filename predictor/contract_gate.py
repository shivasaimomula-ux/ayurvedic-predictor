"""Inbound/outbound contract gates for Stage A (F → A → C/B)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException
from pydantic import ValidationError

from herbenzo_contracts import (
    FormulationInput,
    FormulationSpec,
    SymptomSpec,
    validation_error_body,
)


def validate_inbound_context(context: Optional[dict[str, Any]]) -> Optional[SymptomSpec]:
    """When ``context.symptom_spec`` is present, validate against shared SymptomSpec.

    Missing context (CLI / web UI) is allowed. Unknown fields / invalid schema → 422.
    """
    if not isinstance(context, dict):
        return None
    raw = context.get("symptom_spec")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=422,
            detail=validation_error_body(
                ValueError("context.symptom_spec must be an object")
            ),
        )
    try:
        return SymptomSpec.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=validation_error_body(exc)) from exc


def validate_outbound_formulation_input(payload: dict[str, Any]) -> FormulationInput:
    """Validate A→C classical FormulationInput; raise HTTPException on failure."""
    try:
        return FormulationInput.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=validation_error_body(exc)) from exc


def validate_outbound_formulation_spec(payload: dict[str, Any]) -> FormulationSpec:
    """Validate A→B FormulationSpec; raise HTTPException on failure."""
    try:
        return FormulationSpec.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=validation_error_body(exc)) from exc
