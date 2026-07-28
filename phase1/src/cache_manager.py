"""Local JSON-file cache for raw API responses, keyed by an arbitrary string key.

Each cache entry is a single JSON file containing {"cached_at": <iso ts>, "data": <payload>}.
Expiry is checked on read; expired entries are treated as a cache miss (the file is left
on disk so it can still be used as a last-resort fallback if a live API call fails).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(os.getenv("CACHE_DIR", "data/api_cache"))
CACHE_EXPIRY_DAYS = int(os.getenv("CACHE_EXPIRY_DAYS", "30"))


def _cache_dir() -> Path:
    cache_dir = DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _key_to_path(key: str) -> Path:
    # Keys can contain arbitrary characters (disease names, gene IDs), so hash them
    # into a filesystem-safe filename while keeping a short human-readable prefix.
    safe_prefix = "".join(c if c.isalnum() else "_" for c in key)[:60]
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return _cache_dir() / f"{safe_prefix}_{digest}.json"


def get_cached(key: str, *, allow_expired: bool = False) -> Optional[Any]:
    """Return the cached payload for `key`, or None if missing/expired.

    If `allow_expired` is True, an expired entry is still returned (used as a
    last-resort fallback when a live API call has just failed).
    """
    path = _key_to_path(key)
    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            envelope = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read cache file %s: %s", path, exc)
        return None

    cached_at = datetime.fromisoformat(envelope["cached_at"])
    is_expired = datetime.now(timezone.utc) - cached_at > timedelta(days=CACHE_EXPIRY_DAYS)

    if is_expired and not allow_expired:
        return None

    return envelope["data"]


def set_cached(key: str, data: Any) -> None:
    path = _key_to_path(key)
    envelope = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "key": key,
        "data": data,
    }
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, default=str)
    except OSError as exc:
        logger.warning("Failed to write cache file %s: %s", path, exc)


def is_cached_and_fresh(key: str) -> bool:
    return get_cached(key) is not None
