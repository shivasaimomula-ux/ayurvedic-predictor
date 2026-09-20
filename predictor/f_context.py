"""Consume Stage F handoff `context` on POST /predict.

F's recommender_adapter sends:
  source, spec_id, spec_version, confidence_floor, jurisdiction, safety, symptom_spec

A previously accepted `context` and ignored it. This module normalizes the
fields we can honor without inventing new intake products:
  - echo provenance (spec_id / version / source / jurisdiction)
  - propagate confidence_floor unchanged (never raise)
  - propagate safety flags for audit + downstream (A has no herb–drug engine yet)
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def consume_f_context(raw: Optional[Dict]) -> Dict[str, Any]:
    """Normalize F (or empty) context into a stable intake record.

    Missing context is fine (CLI / web UI). We never invent a higher
    confidence_floor than F supplied.
    """
    ctx = raw if isinstance(raw, dict) else {}
    symptom_spec = ctx.get("symptom_spec") if isinstance(ctx.get("symptom_spec"), dict) else None

    # Prefer top-level keys from to_predict_request; fall back into SymptomSpec.
    spec_id = ctx.get("spec_id") or (symptom_spec or {}).get("spec_id")
    spec_version = ctx.get("spec_version") or (symptom_spec or {}).get("spec_version")
    jurisdiction = ctx.get("jurisdiction") or (symptom_spec or {}).get("jurisdiction")
    source = ctx.get("source")

    floor = _as_float(ctx.get("confidence_floor"))
    if floor is None and symptom_spec is not None:
        floor = _as_float(symptom_spec.get("confidence_floor"))

    safety = ctx.get("safety")
    if not isinstance(safety, dict):
        safety = None
        if isinstance((symptom_spec or {}).get("safety_profile"), dict):
            # Keep raw safety_profile under a clear key when F only nested it.
            safety = {"_from_symptom_spec": True, **(symptom_spec["safety_profile"])}

    # Never raise: store exactly what F sent (or None). Downstream must not
    # treat absence as 1.0.
    intake = {
        "present": bool(ctx),
        "source": source,
        "spec_id": spec_id,
        "spec_version": spec_version,
        "jurisdiction": jurisdiction,
        "confidence_floor": floor,
        "safety": safety,
        "has_symptom_spec": symptom_spec is not None,
    }
    return intake


def audit_event(intake: Dict[str, Any]) -> Dict[str, Any]:
    """Compact audit payload (omit bulky symptom_spec body)."""
    safety = intake.get("safety") or {}
    safety_summary = None
    if isinstance(safety, dict) and safety:
        safety_summary = {
            "age_years": safety.get("age_years"),
            "sex_at_birth": safety.get("sex_at_birth"),
            "pregnancy_status": safety.get("pregnancy_status"),
            "n_medications": len(safety.get("current_medications") or [])
            if isinstance(safety.get("current_medications"), list)
            else None,
            "n_allergies": len(safety.get("allergies") or [])
            if isinstance(safety.get("allergies"), list)
            else None,
            "n_chronic_conditions": len(safety.get("chronic_conditions") or [])
            if isinstance(safety.get("chronic_conditions"), list)
            else None,
            "recent_or_planned_surgery": safety.get("recent_or_planned_surgery"),
        }
    return {
        "source": intake.get("source"),
        "spec_id": intake.get("spec_id"),
        "spec_version": intake.get("spec_version"),
        "jurisdiction": intake.get("jurisdiction"),
        "confidence_floor": intake.get("confidence_floor"),
        "has_symptom_spec": intake.get("has_symptom_spec"),
        "safety_summary": safety_summary,
        "note": "confidence_floor propagated unchanged; A does not raise it",
    }
