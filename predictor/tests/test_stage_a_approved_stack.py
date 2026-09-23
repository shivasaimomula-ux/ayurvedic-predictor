"""Stage A approved stack: Gemini generate + Nemotron Ultra verify; novel KG miss → AI propose."""
from __future__ import annotations

import unittest
from unittest import mock

from predictor import agents, config, knowledge_graph


class TestStageAApprovedStack(unittest.TestCase):
    def test_generator_is_gemini_flash_family(self):
        g = config.GENERATOR_MODEL.lower()
        self.assertTrue("gemini" in g and "flash" in g, msg=g)

    def test_verifier_is_nvidia_nemotron(self):
        v = config.VERIFIER_MODEL.lower()
        self.assertTrue(
            "nvidia/" in v or v.startswith("nim/") or "nemotron" in v,
            msg=v,
        )
        self.assertFalse(v.startswith("claude"))

    def test_default_verifier_not_claude(self):
        self.assertFalse(config.default_verifier_is_claude())

    def test_cost_order_excludes_claude_by_default(self):
        self.assertNotIn("claude", config.VERIFIER_COST_ORDER)

    def test_cross_provider_gemini_vs_nim(self):
        self.assertEqual(config.generator_provider(), "google")
        self.assertEqual(config.verifier_provider(), "nvidia")
        self.assertTrue(config.is_cross_provider())

    def test_pneumonia_matches_or_falls_through_to_empty_for_ai(self):
        # Synonym expansion should hit respiratory; if not, KG returns empty (AI path).
        key = knowledge_graph.match_condition("pneumonia with cold symptoms")
        self.assertEqual(key, "respiratory")

    def test_frame_to_str_object(self):
        self.assertEqual(
            agents._frame_to_str({"dosha": "Kapha", "srotas": "Pranavaha"}),
            "dosha: Kapha; srotas: Pranavaha",
        )
        self.assertIsNone(agents._frame_to_str(None))

    def test_propose_normalizes_object_frame(self):
        with mock.patch.object(config, "llm_available", return_value=True), mock.patch.object(
            config, "gemini_usable", return_value=True
        ), mock.patch.object(config, "nim_usable", return_value=False), mock.patch(
            "predictor.llm.complete_json",
            return_value={
                "formula": "Sitopaladi Churna",
                "formulation": "Churna",
                "delivery": "Oral",
                "ayurvedic_frame": {"dosha": "Kapha"},
                "herbs": ["Pippali (Piper longum)"],
                "phytochemicals": ["piperine"],
                "claims": [
                    "Piper longum has anti-inflammatory activity relevant to respiratory tract"
                ],
            },
        ):
            c = agents.propose_candidate("pneumonia", {"ayurvedic_frame": None})
        self.assertIsNotNone(c)
        self.assertIsInstance(c["ayurvedic_frame"], str)
        self.assertIn("Kapha", c["ayurvedic_frame"])


if __name__ == "__main__":
    unittest.main()
