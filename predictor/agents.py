"""The agents: interpretation, retrieval (with escalation), and verification.

Verification is the heart of the design. Its contract:
  1. the article must be real (guaranteed — records come straight from PubMed);
  2. the claim must be SUPPORTED by the article's own text, with a quote;
  3. the evidence is graded by strength.
The verifier is grounded strictly in the supplied abstract — it is told to
judge ONLY from that text, never from prior knowledge.
"""
from __future__ import annotations

import re
from typing import List, Dict

from . import claim_verifier, config, llm
from .connectors import pubmed

# A binomial like "Withania somnifera" / "Piper longum".
_BINOMIAL = re.compile(r"\b([A-Z][a-z]+ [a-z]{3,})\b")


def _subject_term(claim: str) -> str:
    """Extract the best PubMed search subject from a claim.

    Priority: a Latin binomial inside parentheses -> any binomial in the
    claim -> a parenthetical phrase -> the first three words.
    """
    if "(" in claim and ")" in claim:
        inside = claim[claim.find("(") + 1:claim.find(")")].strip()
        m = _BINOMIAL.search(inside)
        if m:
            return m.group(1)
        if 0 < len(inside.split()) <= 3:
            return inside
    m = _BINOMIAL.search(claim)
    if m:
        return m.group(1)
    return " ".join(claim.split()[:3])

# --- Stage 1: dual interpretation -------------------------------------------

_INTERPRET_SYS = (
    "You are a careful biomedical + Ayurvedic analyst. Given a symptom or "
    "problem, produce a JSON object with: normalized_condition (short noun "
    "phrase), modern_targets (list of molecular targets/pathways, may be "
    "empty), ayurvedic_frame (dosha / srotas involved). Be conservative; do "
    "not invent specifics you are unsure of."
)


def interpret(user_input: str) -> Dict:
    if not config.llm_available():
        return {"normalized_condition": user_input, "modern_targets": [],
                "ayurvedic_frame": None, "_llm": False}
    prompt = f"Symptom/problem: {user_input}"
    errors: list[str] = []
    # Prefer Gemini generator; fall back to NIM so Gemini spend caps do not
    # silently skip interpretation (volume path must stay LLM-backed).
    attempts: list[str] = [config.GENERATOR_MODEL]
    if config.nim_usable():
        attempts.append(f"nim/{config.NIM_MODEL}")
        if config.NIM_MODEL_FALLBACK and config.NIM_MODEL_FALLBACK != config.NIM_MODEL:
            attempts.append(f"nim/{config.NIM_MODEL_FALLBACK}")
    for model in attempts:
        try:
            data = llm.complete_json(prompt, model, system=_INTERPRET_SYS)
            data["_llm"] = True
            data["_interpret_model"] = model
            return data
        except Exception as e:  # noqa: BLE001 - try next provider
            errors.append(f"{model}: {e}")
            continue
    return {
        "normalized_condition": user_input,
        "modern_targets": [],
        "ayurvedic_frame": None,
        "_llm": False,
        "_error": " | ".join(errors)[:800],
    }


# --- Stage 2b: open candidate proposal (fallback when KG has no match) -------

_PROPOSE_SYS = (
    "You are an Ayurvedic formulation expert. Given a symptom or condition, "
    "propose ONE plausible classical Ayurvedic formulation worth investigating. "
    "Use only well-established herbs. Return JSON with keys: "
    "formula (a real classical formula name or single herb), "
    "formulation (e.g. Churna, Vati, Kashayam, Taila), "
    "delivery (how it is taken), "
    "ayurvedic_frame (dosha / srotas involved), "
    "herbs (list of strings 'Common name (Genus species)'), "
    "phytochemicals (list of marker compounds), "
    "claims (2-3 SHORT testable statements, EACH beginning with the Latin "
    "binomial 'Genus species', phrased as a pharmacological ACTIVITY or EFFECT, "
    "e.g. 'Curcuma longa has anti-inflammatory activity relevant to <condition>'). "
    "Do NOT phrase claims as disease cures. Be conservative - it is better to "
    "propose fewer, defensible claims than speculative ones."
)


def _frame_to_str(frame) -> str | None:
    """LLM sometimes returns ayurvedic_frame as an object — UI must get a string."""
    if frame is None or frame == "":
        return None
    if isinstance(frame, str):
        return frame
    if isinstance(frame, dict):
        parts = []
        for k, v in frame.items():
            if v is None or v == "":
                continue
            if isinstance(v, (list, tuple)):
                v = ", ".join(str(x) for x in v)
            parts.append(f"{k}: {v}" if not str(k).isdigit() else str(v))
        return "; ".join(parts) if parts else None
    if isinstance(frame, (list, tuple)):
        return "; ".join(str(x) for x in frame if x)
    return str(frame)


def propose_candidate(user_input: str, interpretation: Dict) -> Dict | None:
    """LLM-proposed candidate for symptoms not in the curated knowledge graph.

    The proposal is only a *hypothesis*: every claim it returns is still run
    through the same evidence loop, so an unsupported proposal is refused, not
    trusted. Returns a candidate dict (KG-shaped) or None.
    """
    if not config.llm_available():
        return None
    if not config.gemini_usable() and not config.nim_usable():
        # Need a generator; prefer Gemini, allow NIM if Gemini missing.
        return None
    frame = _frame_to_str(interpretation.get("ayurvedic_frame"))
    targets = interpretation.get("modern_targets")
    prompt = (
        f"Symptom/condition: {user_input}\n"
        f"Modern targets (if known): {targets}\n"
        f"Ayurvedic frame (if known): {frame}\n"
    )
    attempts: list[str] = [config.GENERATOR_MODEL]
    if config.nim_usable():
        attempts.append(f"nim/{config.NIM_MODEL}")
        if config.NIM_MODEL_FALLBACK and config.NIM_MODEL_FALLBACK != config.NIM_MODEL:
            attempts.append(f"nim/{config.NIM_MODEL_FALLBACK}")
    c = None
    for model in attempts:
        try:
            c = llm.complete_json(prompt, model, system=_PROPOSE_SYS)
            if c:
                c["_propose_model"] = model
                break
        except Exception:  # noqa: BLE001 — try next provider
            c = None
            continue
    if not c or not c.get("formula") or not c.get("claims"):
        return None
    claims = [str(x) for x in c.get("claims", []) if str(x).strip()][:3]
    if not claims:
        return None
    return {
        "formula": c.get("formula"),
        "type": "ai_proposed",
        "formulation": c.get("formulation", "Churna"),
        "delivery": c.get("delivery", "Oral"),
        "ayurvedic_frame": _frame_to_str(c.get("ayurvedic_frame")) or frame,
        "herbs": c.get("herbs", []) if isinstance(c.get("herbs"), list) else [],
        "phytochemicals": (
            c.get("phytochemicals", [])
            if isinstance(c.get("phytochemicals"), list)
            else []
        ),
        "claims": claims,
    }


# --- Stage 3a: retrieval agent with an escalation ladder ---------------------

def escalated_query(claim: str, condition: str, iteration: int) -> str:
    """Each iteration changes STRATEGY, it does not just retry the same query."""
    herb = _subject_term(claim)
    ladder = [
        f'{herb} {condition}',                                  # 0 specific
        f'{herb} AND {condition}',                              # 1 boolean
        f'{herb}[Title/Abstract] {condition}[Title/Abstract]', # 2 field-scoped
        f'{herb} mechanism pharmacology',                      # 3 broaden to mechanism
        f'{herb} clinical trial',                              # 4 prioritise strong evidence
        f'{herb} randomized controlled trial',                # 5
        f'{herb} systematic review',                          # 6
        f'{herb} anti-inflammatory OR therapeutic',           # 7 widen predicate
        f'{herb}',                                             # 8 last-resort broad
    ]
    return ladder[min(iteration, len(ladder) - 1)]


# --- Stage 3b: verification agent (cost-ordered cascade) --------------------
# Default: local NIM Ultra → Gemini. Blue Adj (:8011) only if ADJUDICATION_PREFERRED=1.
# See claim_verifier.py (Task T15 / Audit Finding #11).


def verify_claim_against_article(claim: str, article: Dict) -> Dict:
    """Return a verdict dict for a single (claim, article) pair."""
    if not article.get("abstract"):
        return {"supported": False, "support_quote": "", "reason": "no abstract",
                "evidence_level": "unknown", "pmid": article["pmid"],
                "verified_by": None, "verifier_fallback": False,
                "verifier_path": None, "escalated": False}
    try:
        v = claim_verifier.verify_claim_cascade(
            claim, article, product=_subject_term(claim)
        )
    except Exception as e:  # noqa: BLE001
        # Last-chance: generator model only (never silent Claude default).
        try:
            raw = llm.complete_json(
                (
                    f"CLAIM: {claim}\n\n"
                    f"ARTICLE TITLE: {article['title']}\n"
                    f"ABSTRACT: {article['abstract']}\n"
                ),
                config.GENERATOR_MODEL,
                system=claim_verifier._VERIFY_SYS,
            )
            v = {
                "supported": bool(raw.get("supported")),
                "support_quote": raw.get("support_quote") or "",
                "evidence_level": raw.get("evidence_level") or "unknown",
                "reason": raw.get("reason") or "",
                "verified_by": config.GENERATOR_MODEL,
                "verifier_fallback": True,
                "verifier_path": "generator_fallback",
                "escalated": False,
            }
        except Exception:  # noqa: BLE001
            return {"supported": False, "support_quote": "",
                    "reason": f"verifier error: {e}",
                    "evidence_level": "unknown", "pmid": article["pmid"],
                    "verified_by": None, "verifier_fallback": False,
                    "verifier_path": None, "escalated": False}
    # Prefer the PubMed-derived publication-type grade if it is stronger /known.
    pub_level = article.get("evidence_level", "unknown")
    model_level = v.get("evidence_level", "unknown")
    if config.EVIDENCE_RANK.get(pub_level, 0) >= config.EVIDENCE_RANK.get(model_level, 0):
        v["evidence_level"] = pub_level
    v["pmid"] = article["pmid"]
    v["url"] = article.get("url", "")
    v["title"] = article.get("title", "")
    v["year"] = article.get("year", "")
    return v


def evidence_loop(claim: str, condition: str) -> Dict:
    """Run the bounded retrieve→verify→escalate loop for one claim.

    Returns the verified supporting evidence, or marks the claim insufficient
    after MAX_ITERATIONS distinct search strategies.
    """
    seen_pmids = set()
    supporting: List[Dict] = []
    trail: List[Dict] = []
    verifiers_seen: set[str] = set()
    n_articles_verified = 0

    for i in range(config.MAX_ITERATIONS):
        query = escalated_query(claim, condition, i)
        try:
            articles = pubmed.search_and_fetch(query)
        except Exception as e:  # noqa: BLE001
            trail.append({"iteration": i, "query": query, "error": str(e)})
            continue

        new_articles = [a for a in articles if a["pmid"] not in seen_pmids]
        for a in new_articles:
            seen_pmids.add(a["pmid"])

        # Cap LLM verify spend per claim (NIM Ultra/Super are slow).
        remaining = max(
            0,
            int(getattr(config, "MAX_ARTICLES_VERIFIED_PER_CLAIM", 8))
            - n_articles_verified,
        )
        if remaining <= 0:
            trail.append({
                "iteration": i,
                "query": query,
                "retrieved": [a["pmid"] for a in new_articles],
                "supported_pmids": [],
                "verified_by": [],
                "n_verified": 0,
                "verify_cap_reached": True,
            })
            break
        to_verify = new_articles[:remaining]

        verdicts = [verify_claim_against_article(claim, a) for a in to_verify]
        n_articles_verified += len(verdicts)
        for v in verdicts:
            vb = v.get("verified_by")
            if vb:
                verifiers_seen.add(str(vb))
            vp = v.get("verifier_path") or v.get("verifier_provider")
            if vp:
                verifiers_seen.add(str(vp))
        hits = [v for v in verdicts
                if v.get("supported")
                and config.EVIDENCE_RANK.get(v.get("evidence_level", "unknown"), 0) >= config.MIN_EVIDENCE_LEVEL]
        supporting.extend(hits)

        trail.append({
            "iteration": i,
            "query": query,
            "retrieved": [a["pmid"] for a in new_articles],
            "supported_pmids": [v["pmid"] for v in hits],
            "verified_by": sorted({
                str(v.get("verified_by")) for v in verdicts if v.get("verified_by")
            }),
            "n_verified": len(verdicts),
        })

        if len(supporting) >= config.MIN_SUPPORTING_ARTICLES:
            return {
                "claim": claim,
                "status": "supported",
                "evidence": supporting,
                "iterations_used": i + 1,
                "trail": trail,
                "verifiers_seen": sorted(verifiers_seen),
                "n_articles_verified": n_articles_verified,
                "retrieved_pmids": sorted(seen_pmids),
            }

    return {
        "claim": claim,
        "status": "insufficient_evidence",
        "evidence": supporting,
        "iterations_used": len(trail) or config.MAX_ITERATIONS,
        "trail": trail,
        "verifiers_seen": sorted(verifiers_seen),
        "n_articles_verified": n_articles_verified,
        "retrieved_pmids": sorted(seen_pmids),
    }
