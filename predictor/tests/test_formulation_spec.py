"""Unit tests for A → B FormulationSpec adapter (Task T11)."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from herbenzo_contracts import FormulationSpec

from predictor import formulation_spec_export, pipeline
from predictor.formulation_spec_export import FormulationSpecIncomplete


class FormulationSpecHappyPathTests(unittest.TestCase):
    def test_ashwagandha_demo_dose_emits_spec(self):
        outcome = {
            "formula": "Ashwagandha Churna",
            "formulation": "Churna (fine powder)",
            "delivery_system": "Oral",
            "herbs": ["Ashwagandha (Withania somnifera)"],
            "source": "curated",
            "substantiated_claims": [],
        }
        spec = formulation_spec_export.to_formulation_spec(
            outcome, f_intake={"spec_id": "s-ashw", "confidence_floor": 0.8}
        )
        FormulationSpec.model_validate(spec)
        self.assertEqual(spec["ingredients"][0]["ingredient_id"], "HB-ASHW")
        self.assertEqual(spec["ingredients"][0]["botanical_name"], "Withania somnifera")
        self.assertGreater(spec["ingredients"][0]["quantity_mg"], 0)
        self.assertEqual(spec["source_spec_id"], "s-ashw")
        self.assertEqual(spec["confidence"], 0.8)
        self.assertEqual(spec["inherited_confidence"], 0.8)

    def test_stated_dose_overrides_demo(self):
        outcome = {
            "formula": "Ashwagandha 750 mg capsule",
            "formulation": "capsule",
            "delivery_system": "Oral",
            "herbs": ["Ashwagandha (Withania somnifera) 750 mg"],
            "source": "curated",
        }
        spec = formulation_spec_export.to_formulation_spec(outcome)
        self.assertEqual(spec["ingredients"][0]["quantity_mg"], 750.0)

    def test_triphala_all_registry_ids(self):
        outcome = {
            "formula": "Triphala Churna",
            "formulation": "Churna (fine powder)",
            "delivery_system": "Oral",
            "herbs": [
                "Amalaki (Emblica officinalis)",
                "Haritaki (Terminalia chebula)",
                "Bibhitaki (Terminalia bellirica)",
            ],
        }
        spec = formulation_spec_export.to_formulation_spec(outcome)
        ids = {i["ingredient_id"] for i in spec["ingredients"]}
        self.assertEqual(ids, {"HB-AMLA", "HB-HARI", "HB-BIBH"})


class FormulationSpecRefuseTests(unittest.TestCase):
    def test_refuse_unknown_identity(self):
        outcome = {
            "formula": "Mystery Blend",
            "formulation": "powder",
            "herbs": ["Definitely Not A Plant (Fictus inventus)"],
        }
        with self.assertRaises(FormulationSpecIncomplete) as ctx:
            formulation_spec_export.to_formulation_spec(outcome)
        self.assertEqual(ctx.exception.body["error"], "formulation_spec_incomplete")
        self.assertTrue(ctx.exception.details)

    def test_refuse_when_demo_disabled_and_no_stated_dose(self):
        outcome = {
            "formula": "Ashwagandha Churna",
            "formulation": "powder",
            "herbs": ["Ashwagandha (Withania somnifera)"],
        }
        with self.assertRaises(FormulationSpecIncomplete) as ctx:
            formulation_spec_export.to_formulation_spec(
                outcome, allow_demo_doses=False
            )
        self.assertIn("demo defaults disabled", str(ctx.exception).lower())

    def test_refuse_partial_blend_with_unregistered_herb(self):
        # Avipattikar includes Zingiber — not in HB-* registry → refuse whole spec.
        outcome = {
            "formula": "Avipattikar Churna",
            "formulation": "Churna (fine powder)",
            "herbs": [
                "Amalaki (Emblica officinalis)",
                "Haritaki (Terminalia chebula)",
                "Shunthi (Zingiber officinale)",
                "Pippali (Piper longum)",
            ],
        }
        with self.assertRaises(FormulationSpecIncomplete):
            formulation_spec_export.to_formulation_spec(outcome)

    def test_try_returns_error_body_not_raise(self):
        spec, err = formulation_spec_export.try_formulation_spec(
            {"formula": "X", "herbs": ["Unknownia falsia"]}
        )
        self.assertIsNone(spec)
        self.assertEqual(err["error"], "formulation_spec_incomplete")


class EnvelopeFormulationSpecTests(unittest.TestCase):
    def test_refusal_clears_formulation_spec(self):
        env = pipeline._envelope(
            "q", {}, "insufficient_evidence", None, [], [],
            f_intake={"spec_id": "x"},
            formulation_input={"product_name": "no"},
            formulation_spec={"formulation_id": "no"},
            formulation_spec_error={"error": "x"},
        )
        self.assertIsNone(env["formulation_input"])
        self.assertIsNone(env["formulation_spec"])
        self.assertIsNone(env["formulation_spec_error"])


class EnvDemoDoseFlagTests(unittest.TestCase):
    def test_env_disables_demo_defaults(self):
        outcome = {
            "formula": "Ashwagandha Churna",
            "formulation": "powder",
            "herbs": ["Ashwagandha (Withania somnifera)"],
        }
        with mock.patch.dict(os.environ, {"FORMULATION_SPEC_ALLOW_DEMO_DOSES": "0"}):
            # dose_defaults reads env at call time
            with self.assertRaises(FormulationSpecIncomplete):
                formulation_spec_export.to_formulation_spec(outcome)


if __name__ == "__main__":
    unittest.main()
