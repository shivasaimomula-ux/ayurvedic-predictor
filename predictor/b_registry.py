"""B ingredient identity resolver (HB-* registry) for A → FormulationSpec.

Prefers Stage B ``StaticRegistriesClient`` when ``herbenzo`` is importable.
Otherwise uses an embedded synonym snapshot mirroring B's curated table
(``herbenzo/services/registries.py``). Keep the snapshot in sync when B adds IDs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


class UnknownIngredient(KeyError):
    """Name or ID is not in the B ingredient registry."""


@dataclass(frozen=True)
class IngredientRecord:
    ingredient_id: str
    botanical_name: str
    common_name: str
    part_used: str
    sanskrit_name: str | None = None
    synonyms: tuple[str, ...] = ()


# Snapshot of B StaticRegistriesClient ingredient rows (identity only).
_INGREDIENTS: dict[str, IngredientRecord] = {
    "HB-ASHW": IngredientRecord(
        "HB-ASHW", "Withania somnifera", "Ashwagandha", "root",
        "Ashwagandha", ("Indian ginseng", "winter cherry"),
    ),
    "HB-TURM": IngredientRecord(
        "HB-TURM", "Curcuma longa", "Turmeric", "rhizome",
        "Haridra", ("curcuma", "haldi"),
    ),
    "HB-BERB": IngredientRecord(
        "HB-BERB", "Berberis aristata", "Indian barberry", "root bark",
        "Daruharidra", ("tree turmeric", "berberine source"),
    ),
    "HB-BOSW": IngredientRecord(
        "HB-BOSW", "Boswellia serrata", "Indian frankincense", "gum resin",
        "Shallaki", ("salai guggul",),
    ),
    "HB-PIPL": IngredientRecord(
        "HB-PIPL", "Piper longum", "Long pepper", "fruit",
        "Pippali", ("pipli", "Indian long pepper"),
    ),
    "HB-HARI": IngredientRecord(
        "HB-HARI", "Terminalia chebula", "Chebulic myrobalan", "pericarp of fruit",
        "Haritaki", ("harad",),
    ),
    "HB-BIBH": IngredientRecord(
        "HB-BIBH", "Terminalia bellirica", "Belleric myrobalan", "pericarp of fruit",
        "Bibhitaki", ("baheda",),
    ),
    "HB-AMLA": IngredientRecord(
        "HB-AMLA", "Phyllanthus emblica", "Indian gooseberry", "fruit",
        "Amalaki", ("amla", "Emblica officinalis"),
    ),
    "HB-CINN": IngredientRecord(
        "HB-CINN", "Cinnamomum verum", "True cinnamon", "stem bark",
        "Twak", ("Ceylon cinnamon", "Cinnamomum zeylanicum"),
    ),
    "HB-ELAA": IngredientRecord(
        "HB-ELAA", "Elettaria cardamomum", "Green cardamom", "seed",
        "Ela", ("chhoti elaichi",),
    ),
}

_SYNONYM_INDEX: dict[str, str] = {}
for _rec in _INGREDIENTS.values():
    for _name in (
        _rec.ingredient_id,
        _rec.botanical_name,
        _rec.common_name,
        _rec.sanskrit_name,
        *_rec.synonyms,
    ):
        if _name:
            _SYNONYM_INDEX[_name.strip().lower()] = _rec.ingredient_id


class RegistriesClient(Protocol):
    def lookup_ingredient(self, ingredient_id: str) -> IngredientRecord: ...
    def resolve_identity(self, name: str) -> str: ...


class EmbeddedRegistriesClient:
    """Offline HB-* synonym map (B registry snapshot)."""

    def lookup_ingredient(self, ingredient_id: str) -> IngredientRecord:
        try:
            return _INGREDIENTS[ingredient_id]
        except KeyError as exc:
            raise UnknownIngredient(
                f"{ingredient_id!r} is not in the ingredient registry; "
                "resolve botanical identity before FormulationSpec"
            ) from exc

    def resolve_identity(self, name: str) -> str:
        key = (name or "").strip().lower()
        if not key:
            raise UnknownIngredient("empty botanical/common name")
        if key in _INGREDIENTS:
            return key
        try:
            return _SYNONYM_INDEX[key]
        except KeyError as exc:
            raise UnknownIngredient(f"no registry entry matching {name!r}") from exc


def _try_b_client() -> Optional[RegistriesClient]:
    """Use live B StaticRegistriesClient when herbenzo is installed."""
    try:
        from herbenzo.services.registries import (  # type: ignore
            StaticRegistriesClient,
            UnknownIngredient as BUnknown,
        )
    except ImportError:
        return None

    client = StaticRegistriesClient()

    class _Adapter:
        def lookup_ingredient(self, ingredient_id: str) -> IngredientRecord:
            try:
                rec = client.lookup_ingredient(ingredient_id)
            except BUnknown as exc:
                raise UnknownIngredient(str(exc)) from exc
            return IngredientRecord(
                ingredient_id=rec.ingredient_id,
                botanical_name=rec.botanical_name,
                common_name=rec.common_name,
                part_used=rec.part_used,
                sanskrit_name=rec.sanskrit_name,
                synonyms=tuple(rec.synonyms or ()),
            )

        def resolve_identity(self, name: str) -> str:
            try:
                return client.resolve_identity(name)
            except BUnknown as exc:
                raise UnknownIngredient(str(exc)) from exc

    return _Adapter()


_CLIENT: RegistriesClient | None = None


def get_registries_client() -> RegistriesClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = _try_b_client() or EmbeddedRegistriesClient()
    return _CLIENT


def resolve_identity(name: str) -> str:
    """Map botanical / common / Sanskrit / HB-* id → ingredient_id."""
    return get_registries_client().resolve_identity(name)


def lookup_ingredient(ingredient_id: str) -> IngredientRecord:
    return get_registries_client().lookup_ingredient(ingredient_id)
