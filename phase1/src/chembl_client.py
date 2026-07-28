"""ChEMBL REST client, used as a fallback for drug metadata when Open Targets'
drug data is thin (missing drug type or approval/phase info).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import requests

from src.cache_manager import get_cached, set_cached

logger = logging.getLogger(__name__)

API_URL = os.getenv("CHEMBL_API_URL", "https://www.ebi.ac.uk/chembl/api/data")
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))

SOURCE_NAME = "ChEMBL"

# ChEMBL max_phase -> our TrialPhase string values (see models.TrialPhase)
CHEMBL_PHASE_MAP = {
    4.0: "approved",
    3.0: "phase3",
    2.0: "phase2",
    1.0: "phase1",
    0.5: "preclinical",
    0.0: "preclinical",
}


class ChEMBLAPIError(Exception):
    """Raised when a ChEMBL API call fails after all retries."""


def _get(path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(
                f"{API_URL}/{path}",
                params={**(params or {}), "format": "json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            logger.warning("ChEMBL API call failed (attempt %d/%d): %s", attempt + 1, MAX_RETRIES + 1, exc)
            if attempt < MAX_RETRIES:
                time.sleep(2**attempt)
    raise ChEMBLAPIError(f"ChEMBL API call failed after {MAX_RETRIES + 1} attempts") from last_exc


def get_molecule(chembl_id: str, use_cache: bool = True) -> Optional[dict[str, Any]]:
    """Return raw ChEMBL molecule metadata for a ChEMBL ID, or None on failure."""
    cache_key = f"chembl_molecule::{chembl_id}"

    if use_cache:
        cached = get_cached(cache_key)
        if cached is not None:
            return cached

    try:
        data = _get(f"molecule/{chembl_id}.json")
        set_cached(cache_key, data)
        return data
    except ChEMBLAPIError as exc:
        logger.error("Live ChEMBL call failed for %s: %s", chembl_id, exc)
        stale = get_cached(cache_key, allow_expired=True)
        if stale is not None:
            logger.warning("Falling back to stale ChEMBL cache for %s", chembl_id)
            return stale
        return None


def get_drug_type(chembl_id: str) -> Optional[str]:
    molecule = get_molecule(chembl_id)
    if not molecule:
        return None
    return molecule.get("molecule_type")


def get_trial_phase(chembl_id: str) -> Optional[str]:
    """Return a TrialPhase-compatible string derived from ChEMBL's max_phase, or None."""
    molecule = get_molecule(chembl_id)
    if not molecule or molecule.get("max_phase") is None:
        return None
    try:
        max_phase = float(molecule["max_phase"])
    except (TypeError, ValueError):
        return None
    return CHEMBL_PHASE_MAP.get(max_phase, "unknown")
