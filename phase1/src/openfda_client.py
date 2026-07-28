"""OpenFDA client — drug label (boxed warnings, contraindications) and, optionally,
adverse-event signal. Used by safety_scorer.

Many drugs (especially non-US or investigational) are simply not in OpenFDA;
that absence is treated as "no data" (neutral), never as a safety problem.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import requests

from src.cache_manager import get_cached, set_cached

logger = logging.getLogger(__name__)

OPENFDA_BASE = "https://api.fda.gov"
OPENFDA_API_KEY = os.getenv("OPENFDA_API_KEY") or None
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))

SOURCE_NAME = "openFDA"
LABEL_UI_URL = "https://labels.fda.gov"


class OpenFDAError(Exception):
    pass


def _get(path: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
    if OPENFDA_API_KEY:
        params = {**params, "api_key": OPENFDA_API_KEY}
    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(f"{OPENFDA_BASE}/{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code == 404:
                # openFDA returns 404 when a search matches nothing — that's "no data".
                return None
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            logger.warning("openFDA call failed (attempt %d/%d): %s", attempt + 1, MAX_RETRIES + 1, exc)
            if attempt < MAX_RETRIES:
                time.sleep(2**attempt)
    raise OpenFDAError(f"openFDA call failed after {MAX_RETRIES + 1} attempts") from last_exc


def get_drug_label(drug_name: str, use_cache: bool = True) -> Optional[dict[str, Any]]:
    """Return raw label fields for a drug, or None when openFDA has no record.

    Searches generic then brand name. Never raises: returns None on hard failure
    (so "no data" and "lookup failed" both degrade to a neutral safety result).
    """
    cache_key = f"openfda_label::{drug_name.lower()}"
    if use_cache:
        cached = get_cached(cache_key)
        if cached is not None:
            # We cache a sentinel {"_absent": true} for confirmed no-data, to avoid re-querying.
            return None if cached.get("_absent") else cached

    name = drug_name.replace('"', "").strip()
    label: Optional[dict[str, Any]] = None
    try:
        for field in ("generic_name", "brand_name"):
            data = _get(
                "drug/label.json",
                {"search": f'openfda.{field}:"{name}"', "limit": 1},
            )
            if data and data.get("results"):
                label = data["results"][0]
                break
    except OpenFDAError as exc:
        logger.error("openFDA label lookup failed for '%s': %s", drug_name, exc)
        stale = get_cached(cache_key, allow_expired=True)
        return None if (stale is None or stale.get("_absent")) else stale

    if label is None:
        set_cached(cache_key, {"_absent": True})
        return None

    # Keep only the fields we use, to bound cache size.
    trimmed = {
        "boxed_warning": label.get("boxed_warning"),
        "contraindications": label.get("contraindications"),
        "warnings_and_cautions": label.get("warnings_and_cautions"),
        "warnings": label.get("warnings"),
        "openfda": {
            "generic_name": (label.get("openfda", {}) or {}).get("generic_name", []),
            "brand_name": (label.get("openfda", {}) or {}).get("brand_name", []),
            "spl_set_id": (label.get("openfda", {}) or {}).get("spl_set_id", []),
        },
    }
    set_cached(cache_key, trimmed)
    return trimmed


def label_url(label: dict[str, Any]) -> str:
    """Best-effort link to the FDA label (DailyMed via SPL set id, else search)."""
    spl_ids = (label.get("openfda", {}) or {}).get("spl_set_id") or []
    if spl_ids:
        return f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={spl_ids[0]}"
    generic = (label.get("openfda", {}) or {}).get("generic_name") or [""]
    return f"https://labels.fda.gov/#!search/{generic[0]}"
