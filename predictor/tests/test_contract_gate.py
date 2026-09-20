"""Unit tests: Stage A contract gate (Task T6)."""
from __future__ import annotations

import unittest

from fastapi import HTTPException

from predictor import contract_gate


class ContractGateTests(unittest.TestCase):
    def test_missing_context_ok(self):
        self.assertIsNone(contract_gate.validate_inbound_context(None))

    def test_context_without_symptom_spec_ok(self):
        self.assertIsNone(
            contract_gate.validate_inbound_context(
                {"spec_id": "x", "confidence_floor": 0.5}
            )
        )

    def test_reject_invalid_symptom_spec(self):
        with self.assertRaises(HTTPException) as ctx:
            contract_gate.validate_inbound_context(
                {"symptom_spec": {"totally": "wrong"}}
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_outbound_formulation_happy(self):
        fi = contract_gate.validate_outbound_formulation_input(
            {
                "product_name": "Demo",
                "target_market": "US",
                "ingredients": [{"name": "Ashwagandha"}],
                "modernized_sku": None,
            }
        )
        self.assertEqual(fi.product_name, "Demo")

    def test_outbound_rejects_unknown(self):
        with self.assertRaises(HTTPException) as ctx:
            contract_gate.validate_outbound_formulation_input(
                {
                    "product_name": "Demo",
                    "ingredients": [{"name": "X"}],
                    "mystery": True,
                }
            )
        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
