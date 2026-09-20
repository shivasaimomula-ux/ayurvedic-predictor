"""A → B FormulationSpec adapter (Task T11 / Audit Finding #3).

Resolves display-name herbs to HB-* ``ingredient_id``, requires positive
``quantity_mg`` (stated dose → CoA/demo defaults → refuse), and emits a
herbenzo-contracts ``FormulationSpec`` alongside today's C ``formulation_input``.

Does not invent ModernizedSKU. Independent A/B UIs stay separate; this is API glue.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from herbenzo_contracts import FormulationSpec

from . import b_registry, config, dose_defaults
from .formulation_export import parse_herb, parse_stated_dose_mg, _dosage_form

# Re-export for tests / callers that imported dose parsing from this module.
__all__ = [
    "FormulationSpecIncomplete",
    "parse_stated_dose_mg",
    "to_formulation_spec",
    "try_formulation_spec",
]


class FormulationSpecIncomplete(ValueError):
    """Identity or dose missing — refuse FormulationSpec (do not invent)."""

    def __init__(self, message: str, *, details: Optional[List[str]] = None):
        super().__init__(message)
        self.details = details or []
        self.body = {
            "error": "formulation_spec_incomplete",
            "message": message,
            "details": self.details,
        }


def _identity_candidates(parsed: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for key in ("latin_name", "name"):
        val = parsed.get(key)
        if isinstance(val, str) and val.strip():
            names.append(val.strip())
    return names


def _resolve_ingredient_row(
    herb: Any,
    *,
    allow_demo: Optional[bool] = None,
) -> Dict[str, Any]:
    """Resolve one A herb line → IngredientSpec fields or raise Incomplete."""
    if isinstance(herb, dict):
        parsed = {
            "name": herb.get("name") or herb.get("common_name"),
            "latin_name": herb.get("latin_name") or herb.get("botanical_name"),
            "stated_dose": herb.get("stated_dose"),
            "stated_standardization": herb.get("stated_standardization"),
        }
        stated = herb.get("quantity_mg")
        if stated is None and herb.get("stated_dose") is not None:
            stated = parse_stated_dose_mg(str(herb.get("stated_dose")))
            if stated is None:
                try:
                    stated = float(herb["stated_dose"])
                except (TypeError, ValueError):
                    stated = None
        raw_for_dose = " ".join(
            str(x) for x in (herb.get("stated_dose"), herb.get("name"), herb.get("dose"))
            if x is not None
        )
    else:
        parsed = parse_herb(str(herb))
        stated = parse_stated_dose_mg(str(parsed.get("stated_dose") or ""))
        raw_for_dose = str(herb)

    if stated is None:
        stated = parse_stated_dose_mg(raw_for_dose)
    if stated is None and parsed.get("stated_dose") is not None:
        stated = parse_stated_dose_mg(str(parsed["stated_dose"]))

    candidates = _identity_candidates(parsed)
    if not candidates:
        raise FormulationSpecIncomplete(
            "ingredient identity missing (no botanical/common name)",
            details=["empty herb identity"],
        )

    last_err: Optional[Exception] = None
    ingredient_id: Optional[str] = None
    for name in candidates:
        try:
            ingredient_id = b_registry.resolve_identity(name)
            break
        except b_registry.UnknownIngredient as exc:
            last_err = exc
    if ingredient_id is None:
        tried = ", ".join(repr(c) for c in candidates)
        raise FormulationSpecIncomplete(
            f"cannot resolve ingredient identity for {tried} to HB-* registry id",
            details=[str(last_err) if last_err else tried],
        )

    rec = b_registry.lookup_ingredient(ingredient_id)
    try:
        quantity_mg, dose_source = dose_defaults.resolve_quantity_mg(
            ingredient_id,
            stated_dose_mg=stated,
            allow_demo=allow_demo,
        )
    except ValueError as exc:
        raise FormulationSpecIncomplete(str(exc), details=[str(exc)]) from exc

    return {
        "ingredient_id": ingredient_id,
        "botanical_name": rec.botanical_name,
        "common_name": rec.common_name,
        "part_used": rec.part_used,
        "quantity_mg": quantity_mg,
        "_dose_source": dose_source,
    }


def to_formulation_spec(
    outcome: Dict[str, Any],
    *,
    f_intake: Optional[Dict[str, Any]] = None,
    allow_demo_doses: Optional[bool] = None,
) -> Dict[str, Any]:
    """Build FormulationSpec dict from a recommendation outcome.

    Raises ``FormulationSpecIncomplete`` when any ingredient lacks identity or
    a positive quantity_mg (stated / demo default).
    """
    f_intake = f_intake or {}
    herbs = outcome.get("herbs") or []
    if not herbs:
        # Fall back to formula name — usually will refuse identity, which is correct.
        herbs = [outcome.get("formula") or ""]

    errors: List[str] = []
    ingredients: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for herb in herbs:
        try:
            row = _resolve_ingredient_row(herb, allow_demo=allow_demo_doses)
        except FormulationSpecIncomplete as exc:
            errors.extend(exc.details or [str(exc)])
            continue
        iid = row["ingredient_id"]
        if iid in seen_ids:
            errors.append(f"duplicate ingredient_id {iid}")
            continue
        seen_ids.add(iid)
        ingredients.append({k: v for k, v in row.items() if not k.startswith("_")})

    if errors:
        raise FormulationSpecIncomplete(
            "FormulationSpec refused: incomplete identity or dose — "
            + "; ".join(errors),
            details=errors,
        )
    if not ingredients:
        raise FormulationSpecIncomplete(
            "FormulationSpec refused: no resolvable ingredients",
            details=["ingredients list empty after resolution"],
        )

    market = (config.FORMULATION_TARGET_MARKET or "US").strip().upper()
    # FormulationSpec target_market is a closed Literal; normalize common aliases.
    market_aliases = {"USA": "US", "UNITED STATES": "US", "GB": "UK"}
    market = market_aliases.get(market, market)

    floor = f_intake.get("confidence_floor")
    if floor is None:
        floor = outcome.get("confidence_floor")
    confidence = float(floor) if floor is not None else 0.5
    inherited = float(floor) if floor is not None else None

    formula = outcome.get("formula") or "Unnamed product"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(formula)).strip("-").upper() or "FORM"
    formulation_id = f"F-A-{slug[:40]}"

    payload: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "formulation_id": formulation_id,
        "product_name": formula,
        "dosage_form": _dosage_form(outcome),
        "target_market": market,
        "servings_per_day": 1,
        "ingredients": ingredients,
        "confidence": confidence,
        "inherited_confidence": inherited,
        "source_stage": "A:recommender",
        "source_spec_id": f_intake.get("spec_id") or outcome.get("spec_id"),
    }
    # Validate against shared contract (strict / unknown fields forbidden).
    return FormulationSpec.model_validate(payload).model_dump(mode="json")


def try_formulation_spec(
    outcome: Dict[str, Any],
    *,
    f_intake: Optional[Dict[str, Any]] = None,
    allow_demo_doses: Optional[bool] = None,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (spec_dict, error_body). Never raises — for pipeline envelope."""
    try:
        return (
            to_formulation_spec(
                outcome, f_intake=f_intake, allow_demo_doses=allow_demo_doses
            ),
            None,
        )
    except FormulationSpecIncomplete as exc:
        return None, exc.body
