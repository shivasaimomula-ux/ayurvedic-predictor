"""A → shared-enum adapter for regulatory category + target market (Task T8).

Uses herbenzo-contracts as the single source of truth. Stage A still emits
``product_category`` for C MeSH / indication; ``regulatory_category`` carries
the E lens enum.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from herbenzo_contracts import (
    UnknownEnumValue,
    resolve_regulatory_category,
    resolve_target_market,
    resolution_to_meta,
)

_STRICT = os.getenv("ENUM_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_a_enums(
    *,
    product_category: str,
    regulatory_category: Optional[str],
    target_market: str,
    strict: Optional[bool] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Return (fields_for_formulation_input, category_meta, market_meta)."""
    use_strict = _STRICT if strict is None else strict
    # Prefer explicit regulatory_category; else try product_category aliases.
    cat_raw = regulatory_category if regulatory_category else product_category
    try:
        cat_res = resolve_regulatory_category(cat_raw, strict=use_strict)
    except UnknownEnumValue:
        raise
    mkt_res = resolve_target_market(target_market, for_e=False, strict=use_strict)

    fields = {
        "product_category": product_category,
        "regulatory_category": cat_res["value"],
        "target_market": mkt_res["value"] or target_market,
        "_enum_meta": {
            "categoryResolution": resolution_to_meta(cat_res, kind="category"),
            "marketResolution": resolution_to_meta(mkt_res, kind="market"),
        },
    }
    return (
        fields,
        resolution_to_meta(cat_res, kind="category"),
        resolution_to_meta(mkt_res, kind="market"),
    )
