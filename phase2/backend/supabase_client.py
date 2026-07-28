"""Server-side Supabase client using the SERVICE ROLE key.

The service role key bypasses Row Level Security and must NEVER be exposed to
the browser — it lives only here, on the backend. If Supabase env vars are not
set (e.g. local dev without a Supabase project), `get_supabase()` returns None
and all callers degrade gracefully to a no-cache, no-persistence mode.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")


@lru_cache(maxsize=1)
def get_supabase() -> Optional["Client"]:  # noqa: F821 (Client type only when installed)
    """Return a cached service-role Supabase client, or None if not configured."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.warning(
            "Supabase not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing). "
            "Running without cache or search persistence."
        )
        return None
    try:
        from supabase import create_client

        return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to initialize Supabase client: %s", exc)
        return None


def is_configured() -> bool:
    return get_supabase() is not None
