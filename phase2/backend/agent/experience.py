"""Append-only experience memory for the investigation agent.

Round N writes what it tried and how it went; round N+1 reads it back and adapts.
Storage is a JSONL file today. The public surface here is deliberately narrow —
`record_experience` / `load_experiences` / `clear_experiences` — so a Supabase
table can back it later without any caller changing.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default under backend/data/, which is already gitignored.
_DEFAULT_STORE = Path(__file__).resolve().parent.parent / "data" / "agent_experience.jsonl"

# JSONL appends from concurrent requests must not interleave mid-line.
_write_lock = threading.Lock()


def _store_path() -> Path:
    """Resolved on each call so tests can point AGENT_EXPERIENCE_PATH elsewhere."""
    return Path(os.getenv("AGENT_EXPERIENCE_PATH", str(_DEFAULT_STORE)))


@dataclass
class Experience:
    """One candidate investigated in one round, and what came of it."""

    disease: str
    candidate_drug: str
    round_number: int
    strategy_used: dict[str, Any]
    evidence_summary: dict[str, Any]
    confidence: float
    outcome: str  # "promising" | "weak" | "inconclusive"
    what_worked: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    search_id: Optional[str] = None
    # Groups every round of ONE investigation. Without it, round-2 records from
    # separate runs share a round_number and get read back as a single round.
    run_id: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def record_experience(exp: Experience) -> None:
    """Append one experience. Best-effort: memory loss must never fail a round."""
    path = _store_path()
    try:
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(exp.to_dict()) + "\n")
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("Could not persist experience: %s", exc)


def record_experiences(experiences: list[Experience]) -> None:
    for exp in experiences:
        record_experience(exp)


def load_experiences(
    disease: Optional[str] = None,
    search_id: Optional[str] = None,
    round_number: Optional[int] = None,
    run_id: Optional[str] = None,
) -> list[Experience]:
    """Read back experiences, oldest first, filtered by whatever is supplied.

    Corrupt lines are skipped rather than raising — a half-written line from a
    killed process should not brick the agent's memory.
    """
    path = _store_path()
    if not path.exists():
        return []

    out: list[Experience] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if disease is not None and row.get("disease") != disease:
                    continue
                if search_id is not None and row.get("search_id") != search_id:
                    continue
                if round_number is not None and row.get("round_number") != round_number:
                    continue
                if run_id is not None and row.get("run_id") != run_id:
                    continue
                try:
                    out.append(Experience(**row))
                except TypeError:
                    # Row written by an older/newer schema — ignore rather than crash.
                    continue
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("Could not read experience store: %s", exc)
        return []
    return out


def latest_run(experiences: list[Experience]) -> list[Experience]:
    """Return only the most recent investigation's records, highest round first.

    Experiences from different runs interleave in the log and reuse round
    numbers, so a naive "highest round_number" read mixes them. Grouping by
    run_id and taking the newest group is what makes a prior run readable as a
    single coherent memory.
    """
    if not experiences:
        return []

    by_run: dict[Optional[str], list[Experience]] = {}
    for exp in experiences:
        by_run.setdefault(exp.run_id, []).append(exp)

    # Newest run = the one containing the latest timestamp.
    newest = max(by_run.values(), key=lambda rows: max(r.timestamp for r in rows))
    top_round = max(r.round_number for r in newest)
    return [r for r in newest if r.round_number == top_round]


def clear_experiences() -> None:
    """Wipe the store. Used by tests and by a demo reset."""
    path = _store_path()
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("Could not clear experience store: %s", exc)
