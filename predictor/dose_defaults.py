"""CoA / demo quantity_mg defaults for A → FormulationSpec (Task T11).

Positive milligram doses are required by FormulationSpec. When Stage A has no
stated label/CoA dose, these demo defaults may fill the gap. Unknown IDs or
disabled demo defaults → refuse (no invented dose).
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

# Demo / CoA placeholder doses (mg per serving). Domain review before production.
DEMO_QUANTITY_MG: dict[str, float] = {
    "HB-ASHW": 500.0,
    "HB-TURM": 500.0,
    "HB-BERB": 500.0,
    "HB-BOSW": 300.0,
    "HB-PIPL": 150.0,
    "HB-HARI": 500.0,
    "HB-BIBH": 500.0,
    "HB-AMLA": 500.0,
    "HB-CINN": 250.0,
    "HB-ELAA": 150.0,
}


def demo_doses_enabled() -> bool:
    """When false, only explicit stated doses satisfy quantity_mg."""
    raw = os.getenv("FORMULATION_SPEC_ALLOW_DEMO_DOSES", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def resolve_quantity_mg(
    ingredient_id: str,
    *,
    stated_dose_mg: Optional[float] = None,
    defaults: Optional[Mapping[str, float]] = None,
    allow_demo: Optional[bool] = None,
) -> tuple[float, str]:
    """Return (quantity_mg, source) or raise ValueError if incomplete.

    Priority: stated dose → CoA/demo defaults table → refuse.
    """
    if stated_dose_mg is not None:
        qty = float(stated_dose_mg)
        if qty <= 0:
            raise ValueError(
                f"stated dose for {ingredient_id} must be positive mg, got {qty!r}"
            )
        return qty, "stated_dose"

    use_demo = demo_doses_enabled() if allow_demo is None else allow_demo
    table = defaults if defaults is not None else DEMO_QUANTITY_MG
    if use_demo and ingredient_id in table:
        qty = float(table[ingredient_id])
        if qty <= 0:
            raise ValueError(
                f"demo default for {ingredient_id} must be positive mg, got {qty!r}"
            )
        return qty, "demo_default"

    if not use_demo:
        raise ValueError(
            f"no stated dose for {ingredient_id} and demo defaults disabled "
            "(set FORMULATION_SPEC_ALLOW_DEMO_DOSES=1 or supply quantity_mg)"
        )
    raise ValueError(
        f"no quantity_mg for {ingredient_id}: missing stated dose and no "
        "CoA/demo default in DEMO_QUANTITY_MG"
    )
