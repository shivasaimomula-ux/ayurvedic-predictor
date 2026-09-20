"""Thin A → C FormulationInput adapter (B Modernizer skipped).

Maps a Stage A recommendation `outcome` into the shape Stage C
(`dossier_engine` FormulationInput / sample_formulation.json) expects.

Explicitly sets `modernized_sku: null` so the handoff is honest about the
classical/label path (lower trust posture for export claims).

Does NOT invent doses or standardizations — those stay null until a real
label / CoA path exists.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import config
from .enum_adapter import resolve_a_enums

# "Ashwagandha (Withania somnifera)" or plain "Ashwagandha"
_HERB_RE = re.compile(r"^\s*(.+?)\s*\(([^)]+)\)\s*$")


def parse_herb(herb: str) -> Dict[str, Optional[str]]:
    """Split display herb string into common name + latin when present."""
    if not isinstance(herb, str):
        return {
            "name": str(herb),
            "latin_name": None,
            "stated_dose": None,
            "stated_standardization": None,
        }
    m = _HERB_RE.match(herb.strip())
    if m:
        return {
            "name": m.group(1).strip(),
            "latin_name": m.group(2).strip(),
            "stated_dose": None,
            "stated_standardization": None,
        }
    return {
        "name": herb.strip(),
        "latin_name": None,
        "stated_dose": None,
        "stated_standardization": None,
    }


def _dosage_form(outcome: Dict[str, Any]) -> str:
    """Prefer env/demo default; else derive a coarse form from A fields."""
    if config.FORMULATION_DOSAGE_FORM:
        return config.FORMULATION_DOSAGE_FORM
    formulation = (outcome.get("formulation") or "").lower()
    delivery = (outcome.get("delivery_system") or "").lower()
    text = f"{formulation} {delivery}"
    if "churna" in text or "powder" in text:
        return "powder"
    if "capsule" in text:
        return "capsule"
    if "tablet" in text:
        return "tablet"
    if "oil" in text or "taila" in text:
        return "oil"
    return formulation.strip() or "oral"


def to_formulation_input(
    outcome: Dict[str, Any],
    *,
    f_intake: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build C-shaped FormulationInput from a recommendation outcome.

    Call only when status == recommendation and outcome is non-null.
    """
    herbs = outcome.get("herbs") or []
    ingredients: List[Dict[str, Any]] = [parse_herb(h) for h in herbs]
    if not ingredients:
        # C requires ≥1 ingredient; fall back to formula name as single line.
        ingredients = [parse_herb(outcome.get("formula") or "Unnamed ingredient")]

    claims = outcome.get("substantiated_claims") or []
    claimed_benefits = [
        c.get("claim") for c in claims if isinstance(c, dict) and c.get("claim")
    ]

    note_parts = [
        "classical/label path; B Modernizer skipped",
        f"source={outcome.get('source') or 'unknown'}",
    ]
    if f_intake and f_intake.get("spec_id"):
        note_parts.append(f"spec_id={f_intake['spec_id']}")
    if f_intake and f_intake.get("confidence_floor") is not None:
        note_parts.append(f"confidence_floor={f_intake['confidence_floor']}")

    enum_fields, cat_meta, mkt_meta = resolve_a_enums(
        product_category=config.FORMULATION_PRODUCT_CATEGORY,
        regulatory_category=config.FORMULATION_REGULATORY_CATEGORY,
        target_market=config.FORMULATION_TARGET_MARKET,
    )
    if cat_meta.get("dropped"):
        note_parts.append(
            f"regulatory_category_unresolved={cat_meta.get('input')!r}"
        )

    payload: Dict[str, Any] = {
        "product_name": outcome.get("formula") or "Unnamed product",
        "product_category": enum_fields["product_category"],
        "regulatory_category": enum_fields["regulatory_category"],
        "target_market": enum_fields["target_market"],
        "dosage_form": _dosage_form(outcome),
        "serving_size_g": config.FORMULATION_SERVING_SIZE_G,
        "claimed_benefits": claimed_benefits,
        "ingredients": ingredients,
        # Explicit B skip — do not invent a ModernizedSKU.
        "modernized_sku": None,
        "handoff_note": "; ".join(note_parts),
        "ayurvedic_formulation": outcome.get("formulation"),
        "ayurvedic_delivery": outcome.get("delivery_system"),
        # Non-contract diagnostic (stripped by FormulationInput extra=forbid
        # callers that validate strictly — keep only if gate allows extras).
    }
    # Attach resolution only when the consumer is glue/debug (not C StrictModel).
    # C contract_gate forbids unknown keys; omit _enum_meta from the handoff body.
    _ = (cat_meta, mkt_meta)
    return payload
