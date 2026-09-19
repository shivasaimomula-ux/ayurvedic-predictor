"""PubChem connector via PUG-REST (free, no key required).

Used in the justification stage to ground a phytochemical in real chemistry
(formula, SMILES, canonical name) rather than letting the model assert it.
"""
from __future__ import annotations

from typing import Dict, Optional

import requests

_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_TIMEOUT = 20


def compound(name: str) -> Optional[Dict]:
    """Look up a compound by name. Returns chemistry facts or None if unknown."""
    props = "MolecularFormula,MolecularWeight,CanonicalSMILES,IUPACName"
    try:
        r = requests.get(
            f"{_BASE}/compound/name/{requests.utils.quote(name)}/property/{props}/JSON",
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        rows = r.json().get("PropertyTable", {}).get("Properties", [])
        if not rows:
            return None
        row = rows[0]
        return {
            "name": name,
            "cid": row.get("CID"),
            "molecular_formula": row.get("MolecularFormula"),
            "molecular_weight": row.get("MolecularWeight"),
            "smiles": row.get("CanonicalSMILES"),
            "iupac_name": row.get("IUPACName"),
            "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{row.get('CID')}",
        }
    except requests.RequestException:
        return None
