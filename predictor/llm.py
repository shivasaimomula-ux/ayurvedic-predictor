"""Thin LLM wrapper supporting Gemini (default) and Anthropic.

The provider is chosen by model name: anything starting with "claude" routes to
Anthropic, otherwise Gemini. This lets the verifier run on a different model
than the generator with no other code changes.
"""
from __future__ import annotations

import json
from typing import Optional

from . import config

_gemini_client = None
_anthropic_client = None


def _gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _gemini_client


def _anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _anthropic_client


def complete(prompt: str, model: str, json_mode: bool = False,
             system: Optional[str] = None) -> str:
    """Return raw text from the chosen model."""
    if model.startswith("claude"):
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not set but a claude model was requested.")
        msg = _anthropic().messages.create(
            model=model,
            max_tokens=2048,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    # Gemini path
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set.")
    from google.genai import types
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json" if json_mode else "text/plain",
        temperature=0.2,
    )
    resp = _gemini().models.generate_content(model=model, contents=prompt, config=cfg)
    return resp.text or ""


def complete_json(prompt: str, model: str, system: Optional[str] = None) -> dict:
    """Return parsed JSON, tolerating code fences / stray text."""
    raw = complete(prompt, model, json_mode=True, system=system).strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1].lstrip("json").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            return json.loads(raw[start:end + 1])
        raise
