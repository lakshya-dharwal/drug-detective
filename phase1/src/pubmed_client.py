"""PubMed E-utilities client (NCBI eutils): esearch + esummary + efetch.

Used by literature_scorer (deterministic scoring from counts) and, in Phase 3
step 2, by llm_summarizer (abstracts, display-only). All calls are throttled to
respect NCBI rate limits (~3 req/s without a key, ~10 req/s with NCBI_API_KEY)
and cached aggressively via the Phase 1 JSON cache.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Optional

import requests

from src.cache_manager import get_cached, set_cached

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_API_KEY = os.getenv("NCBI_API_KEY") or None
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))

SOURCE_NAME = "PubMed (NCBI)"
PUBMED_QUERY_URL = "https://pubmed.ncbi.nlm.nih.gov"

# Throttle: min seconds between requests. With a key NCBI permits 10/s; without,
# 3/s. We stay slightly under the ceiling to be safe.
_MIN_INTERVAL = 0.11 if NCBI_API_KEY else 0.35
_throttle_lock = threading.Lock()
_last_request_ts = 0.0

RECENCY_WINDOW_YEARS = 5


class PubMedAPIError(Exception):
    """Raised when a PubMed call fails after all retries."""


def _throttle() -> None:
    global _last_request_ts
    with _throttle_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _last_request_ts)
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


def _params(extra: dict[str, Any]) -> dict[str, Any]:
    base = {"db": "pubmed", "retmode": "json"}
    if NCBI_API_KEY:
        base["api_key"] = NCBI_API_KEY
    base.update(extra)
    return base


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            _throttle()
            resp = requests.get(f"{EUTILS_BASE}/{path}", params=_params(params), timeout=REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            logger.warning("PubMed call failed (attempt %d/%d): %s", attempt + 1, MAX_RETRIES + 1, exc)
            if attempt < MAX_RETRIES:
                time.sleep(2**attempt)
    raise PubMedAPIError(f"PubMed call failed after {MAX_RETRIES + 1} attempts") from last_exc


def _term(drug_name: str, disease_name: str) -> str:
    # Quote each concept so multi-word names match as phrases.
    return f'"{drug_name}" AND "{disease_name}"'


def get_publication_counts(drug_name: str, disease_name: str, use_cache: bool = True) -> dict[str, Any]:
    """Return {total, recent, top_pmids} for a drug-disease pair (for scoring).

    `total`  = all PubMed hits for the pair.
    `recent` = hits within the last RECENCY_WINDOW_YEARS years.
    `top_pmids` = up to 20 most relevant PMIDs (for later display/LLM).
    Never raises: on failure returns zeros so the pipeline degrades gracefully.
    """
    cache_key = f"pubmed_counts::{drug_name.lower()}::{disease_name.lower()}"
    if use_cache:
        cached = get_cached(cache_key)
        if cached is not None:
            return cached

    term = _term(drug_name, disease_name)
    current_year = datetime.utcnow().year
    result = {"total": 0, "recent": 0, "top_pmids": [], "term": term}

    try:
        total_resp = _get("esearch.fcgi", {"term": term, "retmax": 20, "sort": "relevance"})
        esr = total_resp.get("esearchresult", {})
        result["total"] = int(esr.get("count", 0))
        result["top_pmids"] = esr.get("idlist", []) or []

        recent_resp = _get(
            "esearch.fcgi",
            {
                "term": term,
                "retmax": 0,
                "datetype": "pdat",
                "mindate": current_year - RECENCY_WINDOW_YEARS,
                "maxdate": current_year,
            },
        )
        result["recent"] = int(recent_resp.get("esearchresult", {}).get("count", 0))
    except PubMedAPIError as exc:
        logger.error("PubMed counts failed for '%s' / '%s': %s", drug_name, disease_name, exc)
        stale = get_cached(cache_key, allow_expired=True)
        if stale is not None:
            return stale
        return result  # zeros; treated as "no literature signal", not an error

    set_cached(cache_key, result)
    return result


def get_summaries(pmids: list[str], use_cache: bool = True) -> list[dict[str, Any]]:
    """Return [{pmid, title, journal, year, url}] for the given PMIDs (for display)."""
    if not pmids:
        return []
    cache_key = f"pubmed_summaries::{','.join(sorted(pmids))}"
    if use_cache:
        cached = get_cached(cache_key)
        if cached is not None:
            return cached

    try:
        resp = _get("esummary.fcgi", {"id": ",".join(pmids)})
    except PubMedAPIError as exc:
        logger.error("PubMed esummary failed: %s", exc)
        return []

    result_block = resp.get("result", {})
    out: list[dict[str, Any]] = []
    for uid in result_block.get("uids", []):
        rec = result_block.get(uid, {})
        pubdate = rec.get("pubdate", "") or ""
        year = pubdate.split(" ")[0] if pubdate else ""
        out.append(
            {
                "pmid": uid,
                "title": rec.get("title", "").rstrip("."),
                "journal": rec.get("fulljournalname") or rec.get("source", ""),
                "year": year,
                "url": f"{PUBMED_QUERY_URL}/{uid}/",
            }
        )
    set_cached(cache_key, out)
    return out


def get_abstracts(pmids: list[str], use_cache: bool = True) -> list[dict[str, Any]]:
    """Return [{pmid, title, abstract}] via efetch (used by the LLM summarizer only)."""
    if not pmids:
        return []
    cache_key = f"pubmed_abstracts::{','.join(sorted(pmids))}"
    if use_cache:
        cached = get_cached(cache_key)
        if cached is not None:
            return cached

    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            _throttle()
            resp = requests.get(
                f"{EUTILS_BASE}/efetch.fcgi",
                params=_params({"id": ",".join(pmids), "retmode": "xml", "rettype": "abstract"}),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            parsed = _parse_abstract_xml(resp.text)
            set_cached(cache_key, parsed)
            return parsed
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(2**attempt)
    logger.error("PubMed efetch failed: %s", last_exc)
    return []


def _parse_abstract_xml(xml_text: str) -> list[dict[str, Any]]:
    """Minimal, dependency-free extraction of PMID/title/abstract from efetch XML."""
    import xml.etree.ElementTree as ET

    out: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("Failed to parse PubMed abstract XML: %s", exc)
        return out

    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        title_el = article.find(".//ArticleTitle")
        # Abstracts may be split into multiple labeled sections.
        abstract_parts = [el.text or "" for el in article.findall(".//AbstractText")]
        out.append(
            {
                "pmid": pmid_el.text if pmid_el is not None else "",
                "title": (title_el.text or "").rstrip(".") if title_el is not None else "",
                "abstract": " ".join(p.strip() for p in abstract_parts if p).strip(),
            }
        )
    return out
