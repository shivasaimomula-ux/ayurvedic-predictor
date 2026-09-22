"""File-based CoA / dose stub → FormulationSpec (Task N3.1).

Thin pilot loader for Stage A. Resolves identity via ``b_registry``
(B ``StaticRegistriesClient`` when importable). Requires positive
``quantity_mg`` on every line — never fills demo defaults from a CoA file.
Labels output ``identity_source=coa_file``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from herbenzo_contracts import FormulationSpec

from . import b_registry

__all__ = [
    "CoAStubIncomplete",
    "load_coa_stub",
    "coa_stub_to_formulation_spec",
    "formulation_spec_from_coa_path",
]


class CoAStubIncomplete(ValueError):
    """Missing identity or quantity_mg in a CoA stub — refuse, do not invent."""

    def __init__(self, message: str, *, details: Optional[List[str]] = None):
        super().__init__(message)
        self.details = details or []
        self.body = {
            "error": "coa_stub_incomplete",
            "message": message,
            "details": self.details,
        }


def _load_mapping(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise CoAStubIncomplete(
                "PyYAML required for CoA stub YAML (or use .json)",
                details=[str(exc)],
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise CoAStubIncomplete(
            f"CoA stub must be a JSON/YAML object, got {type(data).__name__}",
            details=["root must be object"],
        )
    return data


def load_coa_stub(path: Path | str) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise CoAStubIncomplete(
            f"CoA stub file not found: {p}",
            details=[f"missing file {p}"],
        )
    data = _load_mapping(p)
    ingredients = data.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        raise CoAStubIncomplete(
            "CoA stub refused: ingredients list missing or empty",
            details=["ingredients required"],
        )
    return data


def _resolve_line(raw: Any, *, index: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise CoAStubIncomplete(
            f"ingredient[{index}] must be an object",
            details=[f"ingredient[{index}] not an object"],
        )
    qty = raw.get("quantity_mg")
    if qty is None:
        raise CoAStubIncomplete(
            f"ingredient[{index}] missing quantity_mg — CoA stub refuses silent demo invent",
            details=[f"ingredient[{index}] missing quantity_mg"],
        )
    try:
        quantity_mg = float(qty)
    except (TypeError, ValueError) as exc:
        raise CoAStubIncomplete(
            f"ingredient[{index}] quantity_mg must be a positive number, got {qty!r}",
            details=[f"ingredient[{index}] bad quantity_mg"],
        ) from exc
    if quantity_mg <= 0:
        raise CoAStubIncomplete(
            f"ingredient[{index}] quantity_mg must be positive, got {quantity_mg}",
            details=[f"ingredient[{index}] non-positive quantity_mg"],
        )

    candidates: List[str] = []
    for key in (
        "ingredient_id",
        "botanical_name",
        "latin_name",
        "name",
        "common_name",
        "sanskrit_name",
    ):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            candidates.append(val.strip())
    if not candidates:
        raise CoAStubIncomplete(
            f"ingredient[{index}] missing identity (name / botanical_name / ingredient_id)",
            details=[f"ingredient[{index}] empty identity"],
        )

    last: Optional[Exception] = None
    ingredient_id: Optional[str] = None
    for name in candidates:
        try:
            ingredient_id = b_registry.resolve_identity(name)
            break
        except b_registry.UnknownIngredient as exc:
            last = exc
    if ingredient_id is None:
        tried = ", ".join(repr(c) for c in candidates)
        raise CoAStubIncomplete(
            f"ingredient[{index}] cannot resolve identity for {tried} via B registries",
            details=[str(last) if last else tried],
        )

    rec = b_registry.lookup_ingredient(ingredient_id)
    return {
        "ingredient_id": ingredient_id,
        "botanical_name": rec.botanical_name,
        "common_name": rec.common_name,
        "part_used": raw.get("part_used") or rec.part_used,
        "quantity_mg": quantity_mg,
    }


def coa_stub_to_formulation_spec(
    stub: Mapping[str, Any],
    *,
    formulation_id: Optional[str] = None,
    confidence: float = 0.55,
    inherited_confidence: Optional[float] = None,
    source_spec_id: Optional[str] = None,
    provenance_thread: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw_ings = stub.get("ingredients")
    if not isinstance(raw_ings, list) or not raw_ings:
        raise CoAStubIncomplete(
            "CoA stub refused: ingredients list missing or empty",
            details=["ingredients required"],
        )

    errors: List[str] = []
    ingredients: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for i, line in enumerate(raw_ings):
        try:
            row = _resolve_line(line, index=i)
        except CoAStubIncomplete as exc:
            errors.extend(exc.details or [str(exc)])
            continue
        iid = row["ingredient_id"]
        if iid in seen:
            errors.append(f"duplicate ingredient_id {iid}")
            continue
        seen.add(iid)
        ingredients.append(row)

    if errors:
        raise CoAStubIncomplete(
            "CoA stub refused: incomplete identity or dose — " + "; ".join(errors),
            details=errors,
        )
    if not ingredients:
        raise CoAStubIncomplete(
            "CoA stub refused: no resolvable ingredients",
            details=["ingredients empty after resolution"],
        )

    product_name = stub.get("product_name") or stub.get("product") or "Unnamed CoA product"
    dosage_form = stub.get("dosage_form") or "oral"
    market = str(stub.get("target_market") or "US").strip().upper()
    market = {"USA": "US", "UNITED STATES": "US", "GB": "UK"}.get(market, market)

    coa_id = stub.get("coa_id") or stub.get("lot")
    if formulation_id:
        fid = formulation_id
    elif isinstance(coa_id, str) and coa_id.startswith("COA-"):
        fid = "F-" + coa_id[len("COA-") :]
    else:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", str(product_name)).strip("-").upper() or "COA"
        fid = f"F-COA-{coa_id}" if coa_id else f"F-COA-{slug[:40]}"

    payload: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "formulation_id": fid,
        "product_name": str(product_name),
        "dosage_form": str(dosage_form),
        "target_market": market,
        "servings_per_day": int(stub.get("servings_per_day") or 1),
        "ingredients": ingredients,
        "confidence": float(stub.get("confidence") or confidence),
        "inherited_confidence": (
            float(inherited_confidence)
            if inherited_confidence is not None
            else (
                float(stub["inherited_confidence"])
                if stub.get("inherited_confidence") is not None
                else None
            )
        ),
        "source_stage": "A:coa_stub",
        "source_spec_id": source_spec_id or stub.get("source_spec_id"),
        "identity_source": "coa_file",
        "provenance_thread": provenance_thread or stub.get("provenance_thread"),
    }
    return FormulationSpec.model_validate(payload).model_dump(mode="json")


def formulation_spec_from_coa_path(
    path: Path | str,
    **kwargs: Any,
) -> Dict[str, Any]:
    return coa_stub_to_formulation_spec(load_coa_stub(path), **kwargs)
