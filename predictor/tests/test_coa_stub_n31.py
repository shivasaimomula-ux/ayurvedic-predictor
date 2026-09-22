"""Task N3.1 — CoA stub → FormulationSpec on Stage A."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from herbenzo_contracts import FormulationSpec

from predictor import coa_stub, formulation_spec_export
from predictor.coa_stub import CoAStubIncomplete

CORRIDOR_COA = (
    Path.home()
    / "Desktop"
    / "herbenzo-pipeline-glue"
    / "tests"
    / "fixtures"
    / "corridor-fda-supplement"
    / "coa_stub.json"
)


class CoAStubHappyTests(unittest.TestCase):
    def test_corridor_stub_via_b_registry(self):
        if not CORRIDOR_COA.is_file():
            self.skipTest(f"corridor fixture missing: {CORRIDOR_COA}")
        spec = coa_stub.formulation_spec_from_coa_path(CORRIDOR_COA)
        FormulationSpec.model_validate(spec)
        self.assertEqual(spec["identity_source"], "coa_file")
        self.assertEqual(spec["formulation_id"], "F-CORRIDOR-FDA-SUPP-001")
        ids = {i["ingredient_id"] for i in spec["ingredients"]}
        self.assertEqual(ids, {"HB-BOSW", "HB-TURM"})


class CoAStubRefuseTests(unittest.TestCase):
    def test_refuse_missing_quantity(self):
        with self.assertRaises(CoAStubIncomplete) as ctx:
            coa_stub.coa_stub_to_formulation_spec(
                {
                    "product_name": "X",
                    "ingredients": [
                        {
                            "name": "Ashwagandha",
                            "botanical_name": "Withania somnifera",
                        }
                    ],
                }
            )
        self.assertEqual(ctx.exception.body["error"], "coa_stub_incomplete")

    def test_refuse_unknown_identity(self):
        with self.assertRaises(CoAStubIncomplete):
            coa_stub.coa_stub_to_formulation_spec(
                {
                    "product_name": "X",
                    "ingredients": [
                        {
                            "name": "Fictus inventus",
                            "quantity_mg": 10.0,
                        }
                    ],
                }
            )

    def test_no_demo_fill_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "product_name": "Ashwagandha",
                        "ingredients": [
                            {
                                "name": "Ashwagandha",
                                "botanical_name": "Withania somnifera",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(CoAStubIncomplete):
                coa_stub.formulation_spec_from_coa_path(path)


class DemoLabelTests(unittest.TestCase):
    def test_adapter_labels_demo(self):
        outcome = {
            "formula": "Ashwagandha Churna",
            "formulation": "powder",
            "herbs": ["Ashwagandha (Withania somnifera)"],
        }
        spec = formulation_spec_export.to_formulation_spec(outcome)
        self.assertEqual(spec["identity_source"], "demo")


if __name__ == "__main__":
    unittest.main()
