"""PubMed connector via NCBI E-utilities (free, no key required).

Two calls: esearch (query -> PMIDs) and efetch (PMIDs -> abstracts + metadata).
Publication types are mapped to a coarse evidence level so the verifier can
grade strength of evidence rather than just presence.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import List, Dict

import requests

from .. import config

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_TIMEOUT = 20


def _params(extra: Dict) -> Dict:
    p = {"tool": config.NCBI_TOOL, "email": config.NCBI_EMAIL}
    if config.NCBI_API_KEY:
        p["api_key"] = config.NCBI_API_KEY
    p.update(extra)
    return p


# Map PubMed PublicationType strings -> our evidence vocabulary.
_PUBTYPE_MAP = [
    ("meta-analysis", "meta_analysis"),
    ("randomized controlled trial", "rct"),
    ("clinical trial", "clinical_trial"),
    ("cohort", "cohort"),
    ("case-control", "case_control"),
    ("case reports", "case_report"),
    ("review", "review"),
]


def _evidence_from_pubtypes(pubtypes: List[str]) -> str:
    joined = " ".join(pt.lower() for pt in pubtypes)
    best = "unknown"
    best_rank = -1
    for needle, label in _PUBTYPE_MAP:
        if needle in joined and config.EVIDENCE_RANK.get(label, 0) > best_rank:
            best, best_rank = label, config.EVIDENCE_RANK[label]
    return best


def search(query: str, max_results: int = None) -> List[str]:
    """Return a list of PMIDs for a query (best-match sorted)."""
    max_results = max_results or config.ARTICLES_PER_QUERY
    r = requests.get(
        f"{_BASE}/esearch.fcgi",
        params=_params({
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
        }),
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("esearchresult", {}).get("idlist", [])


def fetch(pmids: List[str]) -> List[Dict]:
    """Return article records: pmid, title, abstract, year, evidence_level."""
    if not pmids:
        return []
    time.sleep(0.34)  # be polite to NCBI (≈3 rps without an api key)
    r = requests.get(
        f"{_BASE}/efetch.fcgi",
        params=_params({"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}),
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out: List[Dict] = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID", default="").strip()
        title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
        # Abstract may be split into multiple labelled sections.
        chunks = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.get("Label")
            text = "".join(ab.itertext()).strip()
            chunks.append(f"{label}: {text}" if label else text)
        abstract = " ".join(c for c in chunks if c)
        year = art.findtext(".//PubDate/Year", default="") or art.findtext(".//PubDate/MedlineDate", default="")[:4]
        pubtypes = [pt.text or "" for pt in art.findall(".//PublicationType")]
        out.append({
            "pmid": pmid,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "title": title.strip(),
            "abstract": abstract,
            "year": year,
            "evidence_level": _evidence_from_pubtypes(pubtypes),
            "pubtypes": pubtypes,
        })
    return out


def search_and_fetch(query: str, max_results: int = None) -> List[Dict]:
    """Convenience: query -> fully populated article records."""
    return fetch(search(query, max_results))
