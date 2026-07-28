"""ClinicalTrials.gov API v2 client.

Enriches the existing trial-phase signal with real, linkable trials for a
drug-disease pair (counts, phases, statuses, NCT ids). Used for display and to
verify/enrich the Phase 1 trial-stage score.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import requests

from src.cache_manager import get_cached, set_cached
from src.models import ClinicalTrial, TrialsInfo

logger = logging.getLogger(__name__)

CT_BASE = "https://clinicaltrials.gov/api/v2"
CT_UI = "https://clinicaltrials.gov/study"
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))

SOURCE_NAME = "ClinicalTrials.gov"

_ACTIVE_STATUSES = {"RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING"}
_COMPLETED_STATUSES = {"COMPLETED"}


class ClinicalTrialsError(Exception):
    pass


def get_trials(drug_name: str, disease_name: str, max_display: int = 5, use_cache: bool = True) -> TrialsInfo:
    """Return trial counts + a few linkable trials for a drug-disease pair.

    Never raises: returns an empty TrialsInfo on failure so ranking/display
    degrade gracefully.
    """
    cache_key = f"ctgov::{drug_name.lower()}::{disease_name.lower()}"
    if use_cache:
        cached = get_cached(cache_key)
        if cached is not None:
            return TrialsInfo(**cached)

    params = {
        "query.term": f"{drug_name} AND {disease_name}",
        "fields": "NCTId,BriefTitle,Phase,OverallStatus",
        "pageSize": 20,
        "countTotal": "true",
    }

    last_exc: Optional[Exception] = None
    data: Optional[dict[str, Any]] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(f"{CT_BASE}/studies", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            logger.warning("CT.gov call failed (attempt %d/%d): %s", attempt + 1, MAX_RETRIES + 1, exc)
            if attempt < MAX_RETRIES:
                time.sleep(2**attempt)

    if data is None:
        logger.error("CT.gov lookup failed for '%s'/'%s': %s", drug_name, disease_name, last_exc)
        stale = get_cached(cache_key, allow_expired=True)
        return TrialsInfo(**stale) if stale else TrialsInfo()

    studies = data.get("studies", []) or []
    active = completed = 0
    trials: list[ClinicalTrial] = []
    for s in studies:
        proto = s.get("protocolSection", {})
        idm = proto.get("identificationModule", {})
        dm = proto.get("designModule", {})
        sm = proto.get("statusModule", {})
        status = sm.get("overallStatus", "") or ""
        if status in _ACTIVE_STATUSES:
            active += 1
        elif status in _COMPLETED_STATUSES:
            completed += 1
        nct = idm.get("nctId", "")
        if nct and len(trials) < max_display:
            phases = dm.get("phases") or []
            trials.append(
                ClinicalTrial(
                    nct_id=nct,
                    title=(idm.get("briefTitle") or "")[:140],
                    phase=", ".join(phases) if phases else "N/A",
                    status=status.replace("_", " ").title(),
                    url=f"{CT_UI}/{nct}",
                )
            )

    info = TrialsInfo(
        trial_count=int(data.get("totalCount", len(studies))),
        active_count=active,
        completed_count=completed,
        trials=trials,
    )
    set_cached(cache_key, info.model_dump())
    return info
