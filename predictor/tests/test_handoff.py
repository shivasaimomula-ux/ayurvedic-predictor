"""Unit tests for F context intake + A→C FormulationInput export (no live LLM)."""
from __future__ import annotations

import unittest

from predictor import f_context, formulation_export, pipeline


class FContextTests(unittest.TestCase):
    def test_empty_context(self):
        intake = f_context.consume_f_context(None)
        self.assertFalse(intake["present"])
        self.assertIsNone(intake["confidence_floor"])
        self.assertIsNone(intake["spec_id"])

    def test_f_handoff_fields(self):
        raw = {
            "source": "herbenzo-stage-f",
            "spec_id": "abc-123",
            "spec_version": "1.0.0",
            "confidence_floor": 0.95,
            "jurisdiction": "IN",
            "safety": {
                "age_years": 34,
                "sex_at_birth": "male",
                "pregnancy_status": None,
                "current_medications": [{"name": "pantoprazole"}],
                "allergies": [],
                "chronic_conditions": [],
            },
            "symptom_spec": {"spec_id": "abc-123", "confidence_floor": 0.95},
        }
        intake = f_context.consume_f_context(raw)
        self.assertTrue(intake["present"])
        self.assertEqual(intake["spec_id"], "abc-123")
        self.assertEqual(intake["confidence_floor"], 0.95)
        self.assertEqual(intake["jurisdiction"], "IN")
        self.assertEqual(intake["safety"]["age_years"], 34)
        self.assertTrue(intake["has_symptom_spec"])

        # Never raise: floor stays exactly what F sent.
        event = f_context.audit_event(intake)
        self.assertEqual(event["confidence_floor"], 0.95)
        self.assertIn("does not raise", event["note"])

    def test_floor_from_symptom_spec_fallback(self):
        intake = f_context.consume_f_context(
            {"symptom_spec": {"spec_id": "x", "confidence_floor": 0.6}}
        )
        self.assertEqual(intake["confidence_floor"], 0.6)
        self.assertEqual(intake["spec_id"], "x")


class FormulationExportTests(unittest.TestCase):
    def test_parse_herb_with_latin(self):
        row = formulation_export.parse_herb("Ashwagandha (Withania somnifera)")
        self.assertEqual(row["name"], "Ashwagandha")
        self.assertEqual(row["latin_name"], "Withania somnifera")
        self.assertIsNone(row["stated_dose"])

    def test_parse_herb_plain(self):
        row = formulation_export.parse_herb("Triphala")
        self.assertEqual(row["name"], "Triphala")
        self.assertIsNone(row["latin_name"])

    def test_to_formulation_input_b_skipped(self):
        outcome = {
            "formula": "Avipattikar Churna",
            "formulation": "Churna (fine powder)",
            "delivery_system": "Oral, with water before meals",
            "herbs": [
                "Amalaki (Emblica officinalis)",
                "Haritaki (Terminalia chebula)",
            ],
            "source": "curated",
            "substantiated_claims": [
                {"claim": "Emblica officinalis reduces gastric acidity"},
            ],
        }
        fi = formulation_export.to_formulation_input(
            outcome, f_intake={"spec_id": "s1", "confidence_floor": 0.9}
        )
        self.assertEqual(fi["product_name"], "Avipattikar Churna")
        self.assertIsNone(fi["modernized_sku"])
        self.assertEqual(fi["target_market"], "US")
        self.assertEqual(fi["product_category"], "dietary_supplement")
        self.assertEqual(fi["regulatory_category"], "SUPPLEMENT")
        self.assertEqual(fi["dosage_form"], "powder")
        self.assertEqual(len(fi["ingredients"]), 2)
        self.assertEqual(fi["ingredients"][0]["latin_name"], "Emblica officinalis")
        self.assertEqual(
            fi["claimed_benefits"],
            ["Emblica officinalis reduces gastric acidity"],
        )
        self.assertIn("B Modernizer skipped", fi["handoff_note"])
        self.assertIn("spec_id=s1", fi["handoff_note"])


class EnvelopeTests(unittest.TestCase):
    def test_refusal_clears_formulation_input(self):
        env = pipeline._envelope(
            "q", {}, "insufficient_evidence", None, [], [],
            f_intake={"spec_id": "x", "confidence_floor": 0.5},
            formulation_input={"product_name": "should not ship"},
        )
        self.assertIsNone(env["formulation_input"])
        self.assertEqual(env["f_context"]["spec_id"], "x")
        self.assertEqual(env["f_context"]["confidence_floor"], 0.5)


if __name__ == "__main__":
    unittest.main()
