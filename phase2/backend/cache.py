"""Supabase-backed result cache + search record persistence.

Replaces Phase 1's local-JSON API cache at the *result* level: an entire
PipelineResult for a disease is cached in `search_results_cache`, keyed by the
normalized disease name, with a 30-day expiry. (Phase 1's own per-API-call JSON
cache still operates underneath on the backend host; this layer avoids re-running
the whole pipeline for a repeated disease.)

Every function degrades to a safe no-op / cache-miss when Supabase is not
configured, so the API works locally without a Supabase project.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from supabase_client import get_supabase

logger = logging.getLogger(__name__)

CACHE_EXPIRY_DAYS = 30


def normalize_disease(name: str) -> str:
    return name.strip().lower()


def get_cached_result(disease_normalized: str) -> Optional[dict[str, Any]]:
    """Return a fresh cached PipelineResult dict for this disease, or None."""
    supabase = get_supabase()
    if supabase is None:
        return None
    try:
        resp = (
            supabase.table("search_results_cache")
            .select("result_json, expires_at")
            .eq("disease_normalized", disease_normalized)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        row = rows[0]
        expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) >= expires_at:
            logger.info("Cache entry for '%s' is expired", disease_normalized)
            return None
        return row["result_json"]
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Cache lookup failed for '%s': %s", disease_normalized, exc)
        return None


def set_cached_result(disease_normalized: str, disease_id: Optional[str], result_json: dict[str, Any]) -> None:
    """Upsert a PipelineResult into the cache with a fresh 30-day expiry."""
    supabase = get_supabase()
    if supabase is None:
        return
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=CACHE_EXPIRY_DAYS)
    try:
        supabase.table("search_results_cache").upsert(
            {
                "disease_normalized": disease_normalized,
                "disease_id": disease_id,
                "result_json": result_json,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
            on_conflict="disease_normalized",
        ).execute()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Cache write failed for '%s': %s", disease_normalized, exc)


def get_evidence(evidence_type: str, cache_key: str) -> Optional[dict[str, Any]]:
    """Fetch a fresh cached evidence payload (literature/llm_summary/safety/trials).

    Cross-instance evidence cache backed by Supabase's evidence_cache table.
    Phase 1's pipeline also keeps a fast local-JSON cache per (drug,disease);
    this Supabase layer lets multiple backend instances share evidence and
    survives restarts. Returns None on miss/expiry/unconfigured.
    """
    supabase = get_supabase()
    if supabase is None:
        return None
    try:
        resp = (
            supabase.table("evidence_cache")
            .select("payload, expires_at")
            .eq("evidence_type", evidence_type)
            .eq("cache_key", cache_key)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        expires_at = datetime.fromisoformat(rows[0]["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) >= expires_at:
            return None
        return rows[0]["payload"]
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Evidence cache lookup failed (%s/%s): %s", evidence_type, cache_key, exc)
        return None


def set_evidence(evidence_type: str, cache_key: str, payload: dict[str, Any]) -> None:
    """Upsert an evidence payload with a fresh 30-day expiry (best-effort)."""
    supabase = get_supabase()
    if supabase is None:
        return
    now = datetime.now(timezone.utc)
    try:
        supabase.table("evidence_cache").upsert(
            {
                "evidence_type": evidence_type,
                "cache_key": cache_key,
                "payload": payload,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(days=CACHE_EXPIRY_DAYS)).isoformat(),
            },
            on_conflict="evidence_type,cache_key",
        ).execute()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Evidence cache write failed (%s/%s): %s", evidence_type, cache_key, exc)


def record_search(
    search_id: str,
    disease_raw: str,
    disease_normalized: str,
    disease_id: Optional[str],
    user_id: Optional[str],
    status: str,
    result_count: int,
) -> None:
    """Insert/update a row in `searches` for history & analytics (best-effort)."""
    supabase = get_supabase()
    if supabase is None:
        return
    try:
        supabase.table("searches").upsert(
            {
                "id": search_id,
                "disease_raw": disease_raw,
                "disease_normalized": disease_normalized,
                "disease_id": disease_id,
                "user_id": user_id,
                "status": status,
                "result_count": result_count,
            },
            on_conflict="id",
        ).execute()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Search record write failed for %s: %s", search_id, exc)
