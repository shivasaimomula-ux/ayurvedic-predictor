"""Thin LLM wrapper: NVIDIA NIM, Gemini, and Anthropic (Claude).

Provider is chosen by model name:
  - starts with "claude" → Anthropic
  - starts with "nim/" or looks like an NVIDIA NIM id (meta/, nvidia/) → NIM
  - otherwise → Gemini

Cost guardrail: volume verification should use NIM/Gemini; Claude is escalate-only.
"""
from __future__ import annotations

import json
from typing import Optional

import requests

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


def is_nim_model(model: str) -> bool:
    name = (model or "").lower()
    return (
        name.startswith("nim/")
        or name.startswith("meta/")
        or name.startswith("nvidia/")
        or name.startswith("microsoft/")
    )


def is_claude_model(model: str) -> bool:
    return (model or "").lower().startswith("claude")


def resolve_nim_model(model: str) -> str:
    """Strip optional nim/ prefix; default to config.NIM_MODEL."""
    if not model or model.lower() in {"nim", "nvidia"}:
        return config.NIM_MODEL
    if model.lower().startswith("nim/"):
        return model[4:]
    return model


def complete(prompt: str, model: str, json_mode: bool = False,
             system: Optional[str] = None) -> str:
    """Return raw text from the chosen model."""
    if is_claude_model(model):
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not set but a claude model was requested.")
        msg = _anthropic().messages.create(
            model=model,
            max_tokens=2048,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    if is_nim_model(model):
        if not config.NVIDIA_API_KEY:
            raise RuntimeError("NVIDIA_API_KEY not set but a NIM model was requested.")
        nim_model = resolve_nim_model(model)
        payload = {
            "model": nim_model,
            "messages": [
                {"role": "system", "content": system or ""},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,
        }
        resp = requests.post(
            f"{config.NIM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.NVIDIA_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        body = resp.json()
        return body["choices"][0]["message"]["content"] or ""

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
