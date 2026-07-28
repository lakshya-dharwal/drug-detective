"""Request/response models for the Phase 2 API layer.

These are deliberately thin: the ranked-result payload itself is Phase 1's
PipelineResult serialized to a dict, so we don't restate its schema here and
risk it drifting from Phase 1.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    disease: str = Field(min_length=1, description="Disease name as typed by the user")


class SearchResponse(BaseModel):
    search_id: str
    cache_hit: bool = Field(description="True if served from the Supabase result cache")


class JobStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ProgressEvent(BaseModel):
    """One SSE progress event payload (data of a named event)."""

    stage: str
    status: str  # "started" | "done"
    message: str
    counts: dict[str, Any] = Field(default_factory=dict)


class ResultResponse(BaseModel):
    search_id: str
    status: JobStatus
    cache_hit: bool = False
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
