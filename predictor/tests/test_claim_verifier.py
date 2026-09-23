"""Unit tests: A claim-verifier cost order + Claude escalate (Task T15)."""
from __future__ import annotations

import unittest
from unittest import mock

from predictor import claim_verifier, config
from predictor.adjudication_client import AdjudicationClient


_ARTICLE = {
    "pmid": "12345",
    "title": "Withania somnifera and stress",
    "abstract": "Withania somnifera reduced cortisol in adults.",
    "url": "https://pubmed.ncbi.nlm.nih.gov/12345/",
    "year": "2020",
    "evidence_level": "clinical_trial",
}


def _verdict(supported: bool, reason: str = "ok") -> dict:
    return {
        "supported": supported,
        "support_quote": "reduced cortisol" if supported else "",
        "evidence_level": "clinical_trial",
        "reason": reason,
    }


class CostOrderDefaultsTests(unittest.TestCase):
    def test_cost_order_is_nim_gemini(self):
        """Stage A approved stack: NIM → Gemini; Claude off the default order."""
        self.assertEqual(config.VERIFIER_COST_ORDER, ("nim", "gemini"))

    def test_default_verifier_is_not_claude(self):
        """Finding #11 / Stage A: default verifier is Nemotron Ultra, not Claude."""
        self.assertFalse(
            config.VERIFIER_MODEL.lower().startswith("claude"),
            msg=f"VERIFIER_MODEL unexpectedly Claude: {config.VERIFIER_MODEL}",
        )
        self.assertFalse(config.default_verifier_is_claude())

    def test_claude_verifier_env_is_coerced_to_nim(self):
        """Old .env VERIFIER_MODEL=claude-* must not stay on the volume path."""
        import importlib
        import os

        with mock.patch.dict(
            os.environ,
            {
                "VERIFIER_MODEL": "claude-sonnet-4-6",
                "A_CLAUDE_ESCALATE": "0",
            },
            clear=False,
        ):
            os.environ["VERIFIER_MODEL"] = "claude-sonnet-4-6"
            os.environ["A_CLAUDE_ESCALATE"] = "0"
            reloaded = importlib.reload(config)
            self.assertFalse(reloaded.VERIFIER_MODEL.lower().startswith("claude"))
            self.assertIn("nemotron", reloaded.VERIFIER_MODEL.lower())
            self.assertFalse(reloaded.default_verifier_is_claude())
        importlib.reload(config)

    def test_cheap_providers_exclude_claude(self):
        with mock.patch.object(config, "NVIDIA_API_KEY", "nv-test"), \
             mock.patch.object(config, "GEMINI_API_KEY", "gm-test"), \
             mock.patch.object(config, "ANTHROPIC_API_KEY", "sk-ant-test"):
            cheap = claim_verifier.available_cheap_providers()
        self.assertEqual(cheap, ["nim", "gemini"])
        self.assertNotIn("claude", cheap)

    def test_cheap_providers_gemini_only_when_no_nim(self):
        with mock.patch.object(config, "NVIDIA_API_KEY", None), \
             mock.patch.object(config, "GEMINI_API_KEY", "gm-test"):
            cheap = claim_verifier.available_cheap_providers()
        self.assertEqual(cheap, ["gemini"])


class LocalCascadeEscalateTests(unittest.TestCase):
    def test_nim_first_no_claude_on_support(self):
        calls: list[str] = []

        def fake_complete(prompt, model, system=None):
            calls.append(model)
            return _verdict(True, "nim support")

        with mock.patch.object(config, "NVIDIA_API_KEY", "nv-test"), \
             mock.patch.object(config, "GEMINI_API_KEY", "gm-test"), \
             mock.patch.object(config, "ANTHROPIC_API_KEY", "sk-ant-test"):
            result = claim_verifier.verify_claim_cascade(
                "Withania somnifera reduces stress",
                _ARTICLE,
                prefer_adjudication=False,
                complete_json=fake_complete,
            )
        self.assertTrue(result["supported"])
        self.assertFalse(result["escalated"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(
            calls[0].startswith("nim/")
            or "meta/" in calls[0]
            or "nvidia/" in calls[0]
            or "nemotron" in calls[0].lower(),
            msg=calls,
        )
        self.assertFalse(any(c.startswith("claude") for c in calls))

    def test_both_cheap_reject_skips_claude(self):
        calls: list[str] = []

        def fake_complete(prompt, model, system=None):
            calls.append(model)
            return _verdict(False, f"reject via {model}")

        with mock.patch.object(config, "NVIDIA_API_KEY", "nv-test"), \
             mock.patch.object(config, "GEMINI_API_KEY", "gm-test"), \
             mock.patch.object(config, "ANTHROPIC_API_KEY", "sk-ant-test"):
            result = claim_verifier.verify_claim_cascade(
                "Withania somnifera cures cancer",
                _ARTICLE,
                prefer_adjudication=False,
                complete_json=fake_complete,
            )
        self.assertFalse(result["supported"])
        self.assertFalse(result["escalated"])
        self.assertEqual(len(calls), 2)  # nim + gemini only
        self.assertFalse(any(c.startswith("claude") for c in calls))

    def test_disagreement_escalates_to_claude(self):
        calls: list[str] = []

        def fake_complete(prompt, model, system=None):
            calls.append(model)
            if model.startswith("claude"):
                return _verdict(False, "claude hard reject")
            if (
                model.startswith("nim/")
                or model.startswith("meta/")
                or model.startswith("nvidia/")
                or "nemotron" in model.lower()
            ):
                return _verdict(False, "nim reject")
            return _verdict(True, "gemini support")  # disagreement

        with mock.patch.object(config, "NVIDIA_API_KEY", "nv-test"), \
             mock.patch.object(config, "GEMINI_API_KEY", "gm-test"), \
             mock.patch.object(config, "ANTHROPIC_API_KEY", "sk-ant-test"), \
             mock.patch.object(config, "ESCALATE_MODEL", "claude-sonnet-4-6"):
            result = claim_verifier.verify_claim_cascade(
                "Withania somnifera reduces stress",
                _ARTICLE,
                prefer_adjudication=False,
                complete_json=fake_complete,
            )
        self.assertTrue(result["escalated"])
        self.assertFalse(result["supported"])
        self.assertTrue(any(c.startswith("claude") for c in calls))
        self.assertIn("claude", result["verifier_path"])

    def test_disagreement_escalates_to_nim_super_by_default(self):
        """A_CLAUDE_ESCALATE off → escalate uses Nemotron Super, not Claude."""
        calls: list[str] = []

        def fake_complete(prompt, model, system=None):
            calls.append(model)
            if "super" in model.lower() or model == config.NIM_MODEL_FALLBACK:
                return _verdict(True, "super support")
            if (
                model.startswith("nim/")
                or model.startswith("meta/")
                or model.startswith("nvidia/")
                or "ultra" in model.lower()
            ):
                return _verdict(False, "ultra reject")
            return _verdict(True, "gemini support")

        with mock.patch.object(config, "NVIDIA_API_KEY", "nv-test"), \
             mock.patch.object(config, "GEMINI_API_KEY", "gm-test"), \
             mock.patch.object(config, "ANTHROPIC_API_KEY", "sk-ant-test"), \
             mock.patch.object(
                 config, "ESCALATE_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1"
             ):
            result = claim_verifier.verify_claim_cascade(
                "Withania somnifera reduces stress",
                _ARTICLE,
                prefer_adjudication=False,
                complete_json=fake_complete,
            )
        self.assertTrue(result["escalated"])
        self.assertFalse(any(c.startswith("claude") for c in calls))
        self.assertIn("nim_escalate", result["verifier_path"])
    def test_force_hard_reject_escalates_even_without_second_cheap(self):
        calls: list[str] = []

        def fake_complete(prompt, model, system=None):
            calls.append(model)
            if model.startswith("claude"):
                return _verdict(False, "confirmed reject")
            return _verdict(False, "gemini reject")

        with mock.patch.object(config, "NVIDIA_API_KEY", None), \
             mock.patch.object(config, "GEMINI_API_KEY", "gm-test"), \
             mock.patch.object(config, "ANTHROPIC_API_KEY", "sk-ant-test"), \
             mock.patch.object(config, "ESCALATE_MODEL", "claude-sonnet-4-6"):
            result = claim_verifier.verify_claim_cascade(
                "claim",
                _ARTICLE,
                force_hard_reject=True,
                prefer_adjudication=False,
                complete_json=fake_complete,
            )
        self.assertTrue(result["escalated"])
        self.assertTrue(any(c.startswith("claude") for c in calls))


class AdjudicationPrimaryTests(unittest.TestCase):
    def test_prefers_blue_service_when_client_provided(self):
        class FakeClient:
            def adjudicate(self, **kwargs):
                return {
                    "verdict": "support",
                    "note": "lexical support",
                    "reason_codes": ["subject_present"],
                    "path": "lexical",
                    "flags": [],
                    "llm": {},
                    "legacy_verdict": "AUTHENTICATED",
                }

            def is_reachable(self):
                return True

        result = claim_verifier.verify_claim_cascade(
            "Withania somnifera reduces stress",
            _ARTICLE,
            prefer_adjudication=True,
            adjudication_client=FakeClient(),  # type: ignore[arg-type]
            complete_json=lambda *a, **k: (_ for _ in ()).throw(AssertionError("local")),
        )
        self.assertTrue(result["supported"])
        self.assertTrue(result["verifier_path"].startswith("adjudication:"))
        self.assertEqual(result["adjudication"]["path"], "lexical")

    def test_falls_back_to_local_when_adjudication_errors(self):
        class BrokenClient:
            def adjudicate(self, **kwargs):
                raise RuntimeError("down")

            def is_reachable(self):
                return True

        def fake_complete(prompt, model, system=None):
            return _verdict(True, "gemini")

        with mock.patch.object(config, "NVIDIA_API_KEY", None), \
             mock.patch.object(config, "GEMINI_API_KEY", "gm-test"):
            result = claim_verifier.verify_claim_cascade(
                "claim",
                _ARTICLE,
                prefer_adjudication=True,
                adjudication_client=BrokenClient(),  # type: ignore[arg-type]
                complete_json=fake_complete,
            )
        self.assertTrue(result["supported"])
        self.assertEqual(result["verifier_provider"], "gemini")


class AdjudicationClientSmokeTests(unittest.TestCase):
    def test_client_posts_adjudicate_payload(self):
        class FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"verdict": "reject", "path": "lexical", "reason_codes": ["x"]}

        session = mock.Mock()
        session.post.return_value = FakeResp()
        client = AdjudicationClient(
            base_url="http://127.0.0.1:8011", session=session, timeout_s=1.0
        )
        out = client.adjudicate("c", "p", "1", article={"pmid": "1", "title": "t"})
        self.assertEqual(out["verdict"], "reject")
        session.post.assert_called_once()
        args, kwargs = session.post.call_args
        self.assertTrue(args[0].endswith("/adjudicate"))
        self.assertEqual(kwargs["json"]["pmid"], "1")


if __name__ == "__main__":
    unittest.main()
