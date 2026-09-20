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
    try:
        data = llm.complete_json(
            f"Symptom/problem: {user_input}", config.GENERATOR_MODEL, system=_INTERPRET_SYS)
        data["_llm"] = True
        return data
    except Exception as e:  # noqa: BLE001 - degrade gracefully
        return {"normalized_condition": user_input, "modern_targets": [],
                "ayurvedic_frame": None, "_llm": False, "_error": str(e)}


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


def propose_candidate(user_input: str, interpretation: Dict) -> Dict | None:
    """LLM-proposed candidate for symptoms not in the curated knowledge graph.

    The proposal is only a *hypothesis*: every claim it returns is still run
    through the same evidence loop, so an unsupported proposal is refused, not
    trusted. Returns a candidate dict (KG-shaped) or None.
    """
    if not config.llm_available():
        return None
    frame = interpretation.get("ayurvedic_frame")
    targets = interpretation.get("modern_targets")
    prompt = (
        f"Symptom/condition: {user_input}\n"
        f"Modern targets (if known): {targets}\n"
        f"Ayurvedic frame (if known): {frame}\n"
    )
    try:
        c = llm.complete_json(prompt, config.GENERATOR_MODEL, system=_PROPOSE_SYS)
    except Exception:  # noqa: BLE001
        return None
    if not c.get("formula") or not c.get("claims"):
        return None
    return {
        "formula": c.get("formula"),
        "type": "ai_proposed",
        "formulation": c.get("formulation", "Churna"),
        "delivery": c.get("delivery", "Oral"),
        "ayurvedic_frame": c.get("ayurvedic_frame", frame),
        "herbs": c.get("herbs", []),
        "phytochemicals": c.get("phytochemicals", []),
        "claims": [str(x) for x in c.get("claims", [])][:3],
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
# Prefer blue adjudication (:8011) → local NIM → Gemini; Claude escalate only.
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

        verdicts = [verify_claim_against_article(claim, a) for a in new_articles]
        hits = [v for v in verdicts
                if v.get("supported")
                and config.EVIDENCE_RANK.get(v.get("evidence_level", "unknown"), 0) >= config.MIN_EVIDENCE_LEVEL]
        supporting.extend(hits)

        trail.append({
            "iteration": i,
            "query": query,
            "retrieved": [a["pmid"] for a in new_articles],
            "supported_pmids": [v["pmid"] for v in hits],
        })

        if len(supporting) >= config.MIN_SUPPORTING_ARTICLES:
            return {"claim": claim, "status": "supported",
                    "evidence": supporting, "iterations_used": i + 1, "trail": trail}

    return {"claim": claim, "status": "insufficient_evidence",
            "evidence": supporting, "iterations_used": config.MAX_ITERATIONS,
            "trail": trail}
