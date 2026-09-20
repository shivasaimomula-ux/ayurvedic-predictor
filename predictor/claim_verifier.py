"""Claim verification cascade with cost guardrail (Audit Finding #11 / Task T15).

Order of preference:
  1. Blue adjudication service on :8011 (when preferred + reachable)
  2. Local cheap LLMs: NVIDIA NIM → Gemini
  3. Claude only on disagreement between cheap providers, or hard-reject force

Never default the high-volume path to Claude.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, llm
from .adjudication_client import AdjudicationClient

_VERIFY_SYS = (
    "You are a strict evidence verifier. You are given a CLAIM and the title + "
    "abstract of ONE real article. Decide ONLY from the supplied text whether "
    "the article supports the claim. Never use outside knowledge. Return JSON: "
    '{"supported": true/false, "support_quote": "<verbatim sentence from the '
    'abstract, or empty>", "evidence_level": one of '
    '["rct","clinical_trial","meta_analysis","cohort","case_report","review",'
    '"animal","in_vitro","in_silico","unknown"], "reason": "<one sentence>"}. '
    "If the abstract is empty or irrelevant, supported=false."
)

# Injectable complete_json for unit tests (signature matches llm.complete_json).
CompleteJsonFn = Callable[..., dict]


def _prompt(claim: str, article: Dict[str, Any]) -> str:
    return (
        f"CLAIM: {claim}\n\n"
        f"ARTICLE TITLE: {article.get('title', '')}\n"
        f"ABSTRACT: {article.get('abstract', '')}\n"
    )


def _product_from_claim(claim: str) -> str:
    """Best-effort product/ingredient label for the blue service."""
    if "(" in claim and ")" in claim:
        inside = claim[claim.find("(") + 1:claim.find(")")].strip()
        if inside:
            return inside
    return " ".join(claim.split()[:3]) or "unknown"


def _article_payload(article: Dict[str, Any]) -> dict[str, Any]:
    return {
        "pmid": str(article.get("pmid", "")),
        "title": article.get("title") or "",
        "abstract": article.get("abstract") or "",
        "mesh_terms": article.get("mesh_terms") or [],
        "publication_types": article.get("publication_types") or [],
    }


def model_for_provider(provider: str) -> str:
    """Map a cost-order provider name to a concrete model id."""
    if provider == "nim":
        return f"nim/{config.NIM_MODEL}"
    if provider == "gemini":
        # Prefer configured VERIFIER_MODEL when it is Gemini; else a strong default.
        if not llm.is_claude_model(config.VERIFIER_MODEL) and not llm.is_nim_model(
            config.VERIFIER_MODEL
        ):
            return config.VERIFIER_MODEL
        return "gemini-2.5-pro"
    if provider == "claude":
        return config.ESCALATE_MODEL
    raise ValueError(f"unknown provider: {provider}")


def available_cheap_providers() -> List[str]:
    """NIM → Gemini among those with keys (Claude never listed)."""
    out: List[str] = []
    for name in ("nim", "gemini"):
        if name == "nim" and config.nim_usable():
            out.append(name)
        elif name == "gemini" and config.gemini_usable():
            out.append(name)
    return out


def _normalize_local(raw: dict, *, model: str, provider: str) -> Dict[str, Any]:
    supported = bool(raw.get("supported"))
    return {
        "supported": supported,
        "support_quote": raw.get("support_quote") or "",
        "evidence_level": raw.get("evidence_level") or "unknown",
        "reason": raw.get("reason") or "",
        "verified_by": model,
        "verifier_provider": provider,
        "verifier_fallback": False,
        "verifier_path": provider,
        "escalated": False,
    }


def _map_adjudication(data: dict, article: Dict[str, Any]) -> Dict[str, Any]:
    verdict = str(data.get("verdict") or "").lower()
    supported = verdict in {"support", "supported", "authenticated"}
    llm_meta = data.get("llm") or {}
    path = str(data.get("path") or "adjudication")
    model = llm_meta.get("model") or path
    quote = ""
    if isinstance(llm_meta.get("raw"), dict):
        quote = str(llm_meta["raw"].get("support_quote") or "")
    return {
        "supported": supported,
        "support_quote": quote,
        "evidence_level": article.get("evidence_level", "unknown"),
        "reason": data.get("note") or ",".join(data.get("reason_codes") or []),
        "verified_by": model,
        "verifier_provider": path,
        "verifier_fallback": False,
        "verifier_path": f"adjudication:{path}",
        "escalated": path == "claude" or "claude" in (data.get("flags") or []),
        "adjudication": {
            "verdict": verdict,
            "reason_codes": data.get("reason_codes") or [],
            "path": path,
            "flags": data.get("flags") or [],
            "legacy_verdict": data.get("legacy_verdict"),
        },
    }


def _call_model(
    *,
    provider: str,
    claim: str,
    article: Dict[str, Any],
    complete_json: CompleteJsonFn,
) -> Dict[str, Any]:
    model = model_for_provider(provider)
    raw = complete_json(_prompt(claim, article), model, system=_VERIFY_SYS)
    return _normalize_local(raw, model=model, provider=provider)


def _local_cascade(
    claim: str,
    article: Dict[str, Any],
    *,
    force_hard_reject: bool,
    complete_json: CompleteJsonFn,
) -> Dict[str, Any]:
    cheap = available_cheap_providers()
    if not cheap:
        # Last resort: configured VERIFIER_MODEL if it is somehow usable, else error.
        if config.verifier_usable() and not llm.is_claude_model(config.VERIFIER_MODEL):
            provider = "gemini" if not llm.is_nim_model(config.VERIFIER_MODEL) else "nim"
            return _call_model(
                provider=provider, claim=claim, article=article, complete_json=complete_json
            )
        raise RuntimeError("No cheap verifier available (need NVIDIA_API_KEY or GEMINI_API_KEY)")

    first = _call_model(
        provider=cheap[0], claim=claim, article=article, complete_json=complete_json
    )

    # Supported on first cheap provider — accept (no Claude).
    if first["supported"] and not force_hard_reject:
        return first

    # Second cheap provider for disagreement detection (still no Claude yet).
    second: Optional[Dict[str, Any]] = None
    if len(cheap) > 1:
        try:
            second = _call_model(
                provider=cheap[1], claim=claim, article=article, complete_json=complete_json
            )
        except Exception as exc:  # noqa: BLE001
            first = {
                **first,
                "reason": f"{first.get('reason', '')} (second cheap failed: {exc})".strip(),
            }

    disagree = (
        second is not None
        and bool(second.get("supported")) != bool(first.get("supported"))
    )
    needs_claude = force_hard_reject or disagree

    if not needs_claude:
        # Both reject / only one cheap rejects — accept unsupported without Claude.
        if second is not None and second.get("supported"):
            return {**second, "verifier_path": f"{cheap[0]}+{cheap[1]}"}
        out = first
        if second is not None:
            out = {
                **first,
                "verifier_path": f"{cheap[0]}+{cheap[1]}",
                "reason": (
                    f"{first.get('reason', '')} "
                    f"[also {cheap[1]}: {second.get('reason', '')}]"
                ).strip(),
            }
        return out

    # Escalate: Claude only on disagreement / hard-reject.
    if not config.claude_usable():
        # Fail closed to unsupported when escalate needed but Claude missing.
        base = first if not (second and second.get("supported")) else second
        return {
            **base,
            "supported": False if force_hard_reject else bool(base.get("supported")),
            "escalated": False,
            "verifier_path": f"{base.get('verifier_path', cheap[0])}+claude_unavailable",
            "reason": (
                f"{base.get('reason', '')} "
                "(Claude escalate needed but ANTHROPIC_API_KEY unset)"
            ).strip(),
        }

    escalated = _call_model(
        provider="claude", claim=claim, article=article, complete_json=complete_json
    )
    prior = f"{cheap[0]}" + (f"+{cheap[1]}" if second is not None else "")
    return {
        **escalated,
        "escalated": True,
        "verifier_path": f"{prior}->claude",
        "verifier_fallback": False,
        "prior_verdicts": {
            cheap[0]: first.get("supported"),
            **({cheap[1]: second.get("supported")} if second is not None else {}),
        },
    }


def verify_claim_cascade(
    claim: str,
    article: Dict[str, Any],
    *,
    product: Optional[str] = None,
    force_hard_reject: bool = False,
    adjudication_client: Optional[AdjudicationClient] = None,
    prefer_adjudication: Optional[bool] = None,
    complete_json: Optional[CompleteJsonFn] = None,
) -> Dict[str, Any]:
    """Run the cost-ordered verification cascade for one (claim, article)."""
    complete_json = complete_json or llm.complete_json
    prefer = (
        config.ADJUDICATION_PREFERRED
        if prefer_adjudication is None
        else prefer_adjudication
    )

    if prefer:
        client = adjudication_client or AdjudicationClient()
        try:
            if adjudication_client is not None or client.is_reachable():
                data = client.adjudicate(
                    claim=claim,
                    product=product or _product_from_claim(claim),
                    pmid=str(article.get("pmid", "")),
                    article=_article_payload(article),
                    force_hard_reject=force_hard_reject,
                )
                return _map_adjudication(data, article)
        except Exception:  # noqa: BLE001 — fall through to local cascade
            pass

    return _local_cascade(
        claim,
        article,
        force_hard_reject=force_hard_reject,
        complete_json=complete_json,
    )


def describe_verifier_config() -> Dict[str, Any]:
    """Health / audit snapshot of the cost-ordered verifier setup."""
    return {
        "cost_order": list(config.VERIFIER_COST_ORDER),
        "generator": config.GENERATOR_MODEL,
        "cheap_verifier": config.VERIFIER_MODEL,
        "escalate_model": config.ESCALATE_MODEL,
        "cheap_available": available_cheap_providers(),
        "claude_escalate_usable": config.claude_usable(),
        "default_verifier_is_claude": config.default_verifier_is_claude(),
        "adjudication_url": config.ADJUDICATION_URL,
        "adjudication_preferred": config.ADJUDICATION_PREFERRED,
    }
