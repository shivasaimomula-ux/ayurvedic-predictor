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
# Optional trailing dose text after the closing paren is allowed.
_HERB_RE = re.compile(r"^\s*(.+?)\s*\(([^)]+)\)\s*(.*)$")
_DOSE_MG_RE = re.compile(
    r"(?P<qty>\d+(?:\.\d+)?)\s*(?:mg|milligrams?)\b",
    re.IGNORECASE,
)
_DOSE_G_RE = re.compile(
    r"(?P<qty>\d+(?:\.\d+)?)\s*g(?:rams?)?\b",
    re.IGNORECASE,
)


def parse_stated_dose_mg(text: Optional[str]) -> Optional[float]:
    """Extract a positive milligram dose from free text when present."""
    if not isinstance(text, str) or not text.strip():
        return None
    m = _DOSE_MG_RE.search(text)
    if m:
        qty = float(m.group("qty"))
        return qty if qty > 0 else None
    m = _DOSE_G_RE.search(text)
    if m:
        qty = float(m.group("qty")) * 1000.0
        return qty if qty > 0 else None
    return None


def parse_herb(herb: str) -> Dict[str, Optional[str]]:
    """Split display herb string into common name + latin when present."""
    if not isinstance(herb, str):
        return {
            "name": str(herb),
            "latin_name": None,
            "stated_dose": None,
            "stated_standardization": None,
        }
    raw = herb.strip()
    m = _HERB_RE.match(raw)
    if m:
        name = m.group(1).strip()
        latin = m.group(2).strip()
        rest = (m.group(3) or "").strip()
        stated = parse_stated_dose_mg(rest) or parse_stated_dose_mg(raw)
        return {
            "name": name,
            "latin_name": latin,
            "stated_dose": f"{stated} mg" if stated is not None else None,
            "stated_standardization": None,
        }
    stated = parse_stated_dose_mg(raw)
    # Strip trailing dose from plain names: "Ashwagandha 500 mg"
    name = raw
    if stated is not None:
        name = _DOSE_MG_RE.sub("", name)
        name = _DOSE_G_RE.sub("", name)
        name = re.sub(r"\s+", " ", name).strip(" -,\t")
    return {
        "name": name or raw,
        "latin_name": None,
        "stated_dose": f"{stated} mg" if stated is not None else None,
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
