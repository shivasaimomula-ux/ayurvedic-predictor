"""A PubMed connector read-through against shared PMID cache (Task T16)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from herbenzo_pubmed_cache import PmidDiskCache

from predictor.connectors import pubmed


ARTICLE = {
    "pmid": "12345678",
    "title": "Shared title",
    "abstract": "Shared abstract",
    "year": "2024",
    "publication_types": ["Journal Article"],
    "pubtypes": ["Journal Article"],
    "journal": "J",
    "doi": "",
    "mesh_terms": [],
    "retracted": False,
}


def test_fetch_hit_skips_network(tmp_path: Path) -> None:
    cache = PmidDiskCache(cache_dir=tmp_path, ttl_seconds=3600)
    cache.put_pmid("12345678", ARTICLE)
    pubmed.reset_cache_for_tests(cache)

    with patch.object(pubmed.requests, "get") as get:
        out = pubmed.fetch(["12345678"])
        get.assert_not_called()

    assert len(out) == 1
    assert out[0]["pmid"] == "12345678"
    assert out[0]["title"] == "Shared title"
    assert out[0]["url"].endswith("/12345678/")
    assert pubmed.cache_stats()["hits"] >= 1
    pubmed.reset_cache_for_tests(None)


def test_fetch_miss_then_hit(tmp_path: Path) -> None:
    cache = PmidDiskCache(cache_dir=tmp_path, ttl_seconds=3600)
    pubmed.reset_cache_for_tests(cache)

    xml = """<?xml version="1.0"?>
    <PubmedArticleSet><PubmedArticle>
      <MedlineCitation><PMID>999</PMID>
        <Article>
          <ArticleTitle>Live</ArticleTitle>
          <Abstract><AbstractText>Body</AbstractText></Abstract>
          <Journal><Title>J</Title>
            <JournalIssue><PubDate><Year>2022</Year></PubDate></JournalIssue>
          </Journal>
          <PublicationTypeList>
            <PublicationType>Review</PublicationType>
          </PublicationTypeList>
        </Article>
      </MedlineCitation>
    </PubmedArticle></PubmedArticleSet>"""

    resp = MagicMock()
    resp.text = xml
    resp.raise_for_status = MagicMock()

    with patch.object(pubmed.requests, "get", return_value=resp) as get:
        with patch.object(pubmed.time, "sleep"):
            first = pubmed.fetch(["999"])
        assert get.call_count == 1

    assert first[0]["title"] == "Live"
    assert cache.get_pmid("999") is not None

    with patch.object(pubmed.requests, "get") as get2:
        second = pubmed.fetch(["999"])
        get2.assert_not_called()
    assert second[0]["title"] == "Live"
    pubmed.reset_cache_for_tests(None)
