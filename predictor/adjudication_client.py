"""Thin HTTP client for the blue citation adjudication service (:8011).

Primary path when ADJUDICATION_PREFERRED and the service is reachable.
Does not import herbenzo-adjudication — keep Stage A free of a hard package dep.
"""
from __future__ import annotations

from typing import Any, Optional

import requests

from . import config

DEFAULT_BASE_URL = "http://127.0.0.1:8011"


class AdjudicationClient:
    """Minimal POST /adjudicate + GET /health against the blue service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_s: Optional[float] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = (base_url or config.ADJUDICATION_URL or DEFAULT_BASE_URL).rstrip("/")
        self.timeout_s = (
            timeout_s if timeout_s is not None else config.ADJUDICATION_TIMEOUT_S
        )
        self._session = session or requests.Session()

    def health(self) -> dict[str, Any]:
        resp = self._session.get(
            f"{self.base_url}/health", timeout=min(self.timeout_s, 3.0)
        )
        resp.raise_for_status()
        return resp.json()

    def is_reachable(self) -> bool:
        try:
            data = self.health()
            return bool(data.get("status") == "ok" or data.get("port_contract") == 8011)
        except Exception:  # noqa: BLE001
            return False

    def adjudicate(
        self,
        claim: str,
        product: str,
        pmid: str,
        *,
        product_aliases: Optional[list[str]] = None,
        claim_domain: str = "general",
        article: Optional[dict[str, Any]] = None,
        mode: str = "auto",
        force_hard_reject: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "claim": claim,
            "product": product,
            "pmid": str(pmid),
            "product_aliases": product_aliases or [],
            "claim_domain": claim_domain,
            "article": article,
            "mode": mode,
            "force_hard_reject": force_hard_reject,
        }
        resp = self._session.post(
            f"{self.base_url}/adjudicate",
            json=payload,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()
