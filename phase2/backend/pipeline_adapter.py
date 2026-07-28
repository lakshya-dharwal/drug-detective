"""Adapter that imports the untouched Phase 1 pipeline and wraps it for the API.

Phase 1 lives at ../../phase1 and is imported as-is. The only Phase 1 change
this relies on is the optional `progress_callback` hook already added at its
stage boundaries; the scoring/orchestration logic is not modified or
re-implemented here.

`run_pipeline_with_progress` runs the (blocking) Phase 1 pipeline and forwards
each real stage event to a callback, then returns the PipelineResult serialized
to a plain dict (via pydantic) so the API layer never depends on Phase 1's
model classes directly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

# --- Make the Phase 1 package importable without copying or refactoring it ----
# Phase 1 imports its own modules as `from src... import ...`, so we add the
# phase1 root (which contains the `src/` package) to sys.path. We APPEND rather
# than insert(0): Phase 1 also has a top-level `main.py`, and the backend has its
# own `main.py`, so appending keeps the backend's modules winning while still
# making Phase 1's `src` package importable.
_PHASE1_ROOT = Path(
    os.getenv("PHASE1_ROOT", Path(__file__).resolve().parent.parent.parent / "phase1")
).resolve()
if str(_PHASE1_ROOT) not in sys.path:
    sys.path.append(str(_PHASE1_ROOT))

# Load Phase 1's own .env (API URLs, cache config) if present, before importing it.
try:
    from dotenv import load_dotenv

    _phase1_env = _PHASE1_ROOT / ".env"
    if _phase1_env.exists():
        load_dotenv(_phase1_env)
except ImportError:
    pass

from src.pipeline import run_pipeline  # noqa: E402  (Phase 1 entry point)

# A stage-progress event forwarded to the API layer.
ProgressEmitter = Callable[[str, str, str, dict[str, Any]], None]


def run_pipeline_with_progress(
    disease_name: str, on_progress: Optional[ProgressEmitter] = None
) -> dict[str, Any]:
    """Run Phase 1 for `disease_name`, forwarding stage events to `on_progress`.

    Returns the PipelineResult as a JSON-serializable dict. This function is
    blocking (Phase 1 makes synchronous HTTP calls); the API layer runs it in a
    threadpool so it doesn't block the event loop.
    """

    def _callback(stage: str, status: str, message: str, **counts: Any) -> None:
        if on_progress is not None:
            on_progress(stage, status, message, counts)

    result = run_pipeline(disease_name, progress_callback=_callback if on_progress else None)
    # pydantic v2 model -> plain dict (datetimes/enums coerced to JSON-friendly types).
    return result.model_dump(mode="json")
