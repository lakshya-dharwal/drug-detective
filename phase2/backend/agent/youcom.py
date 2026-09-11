"""You.com live web evidence retrieval, with provenance stamped on every item.

Role in the loop: the existing pipeline's evidence (PubMed, ClinicalTrials.gov,
openFDA) is indexed and therefore lags. You.com is how a round can discover
material newer than those indexes — a preprint, a trial readout, a retraction.

Never scores anything. It returns provenance-stamped items the deterministic
evaluator consumes. Degrades to an empty list (not an error) without a key, so
the loop keeps working offline.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

SEARCH_URL = "https://ydc-index.io/v1/search"
TIMEOUT = float(os.getenv("YOUCOM_TIMEOUT_SECONDS", "12"))


def is_configured() -> bool:
    return bool(os.getenv("YOUCOM_API_KEY"))


def build_query(drug: str, disease: str, formulation: str, mechanism: str | None = None) -> str:
    """The query formulation lever, made concrete.

    This is what the strategy engine is actually changing between rounds: round 1
    asks about the drug-disease pair directly, a reframed round asks about the
    shared mechanism instead.
    """
    if formulation == "mechanism_pathway" and mechanism:
        return f"{mechanism} pathway {disease} drug repurposing evidence"
    return f"{drug} {disease} drug repurposing clinical evidence"


def search_evidence(
    drug: str, disease: str, formulation: str = "drug_disease",
    mechanism: str | None = None, count: int = 5,
) -> list[dict[str, Any]]:
    """Fetch live web evidence for one drug-disease hypothesis.

    Returns provenance-stamped items: every one carries its source URL and the
    timestamp it was retrieved, so a claim can always be traced back.
    """
    api_key = os.getenv("YOUCOM_API_KEY")
    if not api_key:
        return []

    query = build_query(drug, disease, formulation, mechanism)
    try:
        resp = requests.post(
            SEARCH_URL,
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            json={"query": query, "count": count},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("You.com retrieval failed for '%s': %s", query, exc)
        return []

    retrieved_at = datetime.now(timezone.utc).isoformat()
    items: list[dict[str, Any]] = []
    for hit in (payload.get("results") or {}).get("web", [])[:count]:
        url = hit.get("url") or ""
        if not url:
            continue
        snippets = hit.get("snippets") or []
        items.append({
            "title": hit.get("title") or "",
            "url": url,
            "description": hit.get("description") or "",
            "snippet": (snippets[0] if snippets else "")[:500],
            # --- provenance ---
            "source": "you.com",
            "query_used": query,
            "retrieved_at": retrieved_at,
        })
    return items
