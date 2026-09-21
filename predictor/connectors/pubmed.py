"""PubMed connector via NCBI E-utilities (free, no key required).

Two calls: esearch (query -> PMIDs) and efetch (PMIDs -> abstracts + metadata).
Publication types are mapped to a coarse evidence level so the verifier can
grade strength of evidence rather than just presence.

Task T16: EFetch is read-through against the shared ``herbenzo-pubmed-cache``
disk store (same layout / env as Stage B) so A does not re-hit NCBI for PMIDs
already hydrated by B or adjudication.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

import requests

from herbenzo_pubmed_cache import PmidDiskCache

from .. import config

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_TIMEOUT = 20

_CACHE: Optional[PmidDiskCache] = None


def _cache() -> PmidDiskCache:
    global _CACHE
    if _CACHE is None:
        # Prefer shared env dir; otherwise stage-local cache/pubmed under cwd.
        _CACHE = PmidDiskCache(
            cache_dir=getattr(config, "PUBMED_CACHE_DIR", None),
            ttl_seconds=getattr(config, "PUBMED_CACHE_TTL_S", None),
        )
    return _CACHE


def reset_cache_for_tests(cache: Optional[PmidDiskCache] = None) -> None:
    """Test hook to inject / clear the process-wide cache singleton."""
    global _CACHE
    _CACHE = cache


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


def _normalize_article(raw: Dict) -> Dict:
    """Map shared-cache / B-shaped records onto A's article dict."""
    pmid = str(raw.get("pmid", "")).strip()
    pubtypes = list(raw.get("publication_types") or raw.get("pubtypes") or [])
    evidence = raw.get("evidence_level") or _evidence_from_pubtypes(pubtypes)
    return {
        "pmid": pmid,
        "url": raw.get("url") or f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "title": (raw.get("title") or "").strip(),
        "abstract": raw.get("abstract") or "",
        "year": raw.get("year") or "",
        "evidence_level": evidence,
        "pubtypes": pubtypes,
        "journal": raw.get("journal") or "",
        "doi": raw.get("doi") or "",
        "mesh_terms": list(raw.get("mesh_terms") or []),
        "retracted": bool(raw.get("retracted", False)),
    }


def search(query: str, max_results: int = None) -> List[str]:
    """Return a list of PMIDs for a query (best-match sorted)."""
    max_results = max_results or config.ARTICLES_PER_QUERY
    cached = _cache().get_search(query, max_results)
    if cached is not None:
        return list(cached.get("pmids") or [])

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
    res = r.json().get("esearchresult", {})
    pmids = list(res.get("idlist", []))
    _cache().put_search(query, max_results, {
        "query": query,
        "total": int(res.get("count", len(pmids)) or 0),
        "pmids": pmids,
    })
    return pmids


def fetch(pmids: List[str]) -> List[Dict]:
    """Return article records: pmid, title, abstract, year, evidence_level."""
    if not pmids:
        return []

    cache = _cache()
    ordered = [str(p) for p in pmids]
    found: Dict[str, Dict] = {}
    missing: List[str] = []
    for p in ordered:
        hit = cache.get_pmid(p)
        if hit is not None:
            found[p] = _normalize_article(hit)
        else:
            missing.append(p)

    if missing:
        time.sleep(0.34)  # be polite to NCBI (≈3 rps without an api key)
        r = requests.get(
            f"{_BASE}/efetch.fcgi",
            params=_params({"db": "pubmed", "id": ",".join(missing), "retmode": "xml"}),
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
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
            journal = art.findtext(".//Journal/Title", default="") or ""
            doi = ""
            for aid in art.findall(".//ArticleId"):
                if aid.get("IdType") == "doi" and aid.text:
                    doi = aid.text
            mesh = [
                m.text for m in art.findall(".//MeshHeading/DescriptorName") if m.text
            ]
            retracted = any("Retracted" in (p or "") for p in pubtypes)
            record = {
                "pmid": pmid,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "title": title.strip(),
                "abstract": abstract,
                "year": year,
                "evidence_level": _evidence_from_pubtypes(pubtypes),
                "pubtypes": pubtypes,
                "publication_types": pubtypes,
                "journal": journal,
                "doi": doi,
                "mesh_terms": mesh,
                "retracted": retracted,
            }
            cache.put_pmid(pmid, record)
            found[pmid] = _normalize_article(record)

    return [found[p] for p in ordered if p in found]


def search_and_fetch(query: str, max_results: int = None) -> List[Dict]:
    """Convenience: query -> fully populated article records."""
    return fetch(search(query, max_results))


def cache_stats() -> Dict[str, int]:
    return _cache().stats.as_dict()
