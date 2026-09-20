"""Unit tests: A enum adapter (Task T8)."""

from __future__ import annotations

import unittest

from predictor.enum_adapter import resolve_a_enums


class EnumAdapterTests(unittest.TestCase):
    def test_dietary_supplement_resolves(self):
        fields, cat, mkt = resolve_a_enums(
            product_category="dietary_supplement",
            regulatory_category=None,
            target_market="US",
        )
        self.assertEqual(fields["regulatory_category"], "SUPPLEMENT")
        self.assertEqual(cat["category"], "SUPPLEMENT")
        self.assertFalse(cat["dropped"])
        self.assertEqual(mkt["market"], "US")

    def test_explicit_regulatory_wins(self):
        fields, cat, _ = resolve_a_enums(
            product_category="anti-inflammatory",
            regulatory_category="HERBAL",
            target_market="EU",
        )
        self.assertEqual(fields["product_category"], "anti-inflammatory")
        self.assertEqual(fields["regulatory_category"], "HERBAL")
        self.assertFalse(cat["dropped"])

    def test_indication_only_drops_regulatory(self):
        fields, cat, _ = resolve_a_enums(
            product_category="laxative",
            regulatory_category=None,
            target_market="US",
        )
        self.assertIsNone(fields["regulatory_category"])
        self.assertTrue(cat["dropped"])


if __name__ == "__main__":
    unittest.main()
