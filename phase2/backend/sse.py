"""In-memory job registry + SSE plumbing.

Bridges Phase 1's *synchronous* progress callback (invoked from a worker thread
via run_in_threadpool) to an *async* SSE generator, using a per-job asyncio.Queue
that the worker thread feeds through loop.call_soon_threadsafe.

NOTE ON SCALING: job state lives in a process-local dict, which is correct for a
single backend instance (Phase 2). Horizontal scaling (multiple Render/Railway
instances behind a load balancer) would require moving this queue/state to Redis
so that the instance holding the SSE connection can see events from the instance
running the job. Documented in the README.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

from cache import normalize_disease, record_search, set_cached_result
from models import JobStatus
from pipeline_adapter import run_pipeline_with_progress

logger = logging.getLogger(__name__)

# A sentinel pushed onto a job's queue to signal the stream to close.
_STREAM_DONE = object()


@dataclass
class Job:
    search_id: str
    disease_raw: str
    disease_normalized: str
    user_id: Optional[str] = None
    status: JobStatus = JobStatus.RUNNING
    cache_hit: bool = False
    result: Optional[dict[str, Any]] = None
    disease_id: Optional[str] = None
    error: Optional[str] = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    _consumed: bool = False  # guards against duplicate stream consumption


# Process-local registry. search_id -> Job.
JOBS: dict[str, Job] = {}


def get_job(search_id: str) -> Optional[Job]:
    return JOBS.get(search_id)


def create_job(search_id: str, disease_raw: str, user_id: Optional[str]) -> Job:
    job = Job(
        search_id=search_id,
        disease_raw=disease_raw,
        disease_normalized=normalize_disease(disease_raw),
        user_id=user_id,
    )
    JOBS[search_id] = job
    return job


def _sse_format(event: str, data: dict[str, Any]) -> str:
    """Render a named SSE event with a JSON data line."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def run_job(job: Job) -> None:
    """Run the Phase 1 pipeline for a job, streaming real progress into its queue.

    Executed as an asyncio task. The blocking pipeline runs in a threadpool; its
    synchronous progress callback marshals events back onto the event loop.
    """
    loop = asyncio.get_running_loop()

    def on_progress(stage: str, status: str, message: str, counts: dict[str, Any]) -> None:
        # Called from the worker thread -> hop back to the loop thread safely.
        payload = {"stage": stage, "status": status, "message": message, "counts": counts}
        loop.call_soon_threadsafe(job.queue.put_nowait, ("progress", payload))

    try:
        result = await asyncio.to_thread(run_pipeline_with_progress, job.disease_raw, on_progress)
        job.result = result
        job.status = JobStatus.COMPLETE
        resolved = result.get("disease_resolved") or {}
        job.disease_id = resolved.get("efo_id")

        # Persist to Supabase cache + searches (best-effort, no-op if unconfigured).
        set_cached_result(job.disease_normalized, job.disease_id, result)
        record_search(
            search_id=job.search_id,
            disease_raw=job.disease_raw,
            disease_normalized=job.disease_normalized,
            disease_id=job.disease_id,
            user_id=job.user_id,
            status=job.status.value,
            result_count=len(result.get("ranked_candidates", [])),
        )
        job.queue.put_nowait(("complete", {"result": result}))
    except Exception as exc:  # noqa: BLE001 - pipeline should not raise, but never crash the server
        logger.exception("Job %s failed", job.search_id)
        job.status = JobStatus.FAILED
        job.error = str(exc)
        record_search(
            search_id=job.search_id,
            disease_raw=job.disease_raw,
            disease_normalized=job.disease_normalized,
            disease_id=None,
            user_id=job.user_id,
            status=job.status.value,
            result_count=0,
        )
        job.queue.put_nowait(("failed", {"error": str(exc)}))
    finally:
        job.queue.put_nowait(_STREAM_DONE)


async def replay_cached_job(job: Job) -> None:
    """For a cache-hit job, quickly emit the same checklist stages from cached counts.

    Keeps the UI experience identical (a checklist that advances) without
    re-running the pipeline. Small sleeps make the flow legible, not fake timing —
    there is genuinely no work to do, so we say so quickly.
    """
    result = job.result or {}
    resolved = result.get("disease_resolved") or {}
    genes = result.get("gene_count", 0)
    candidates = result.get("ranked_candidates", []) or []
    no_drug_genes = result.get("genes_without_drugs", []) or []

    stages = [
        ("resolving_disease", f"Resolved to {resolved.get('name', job.disease_raw)}",
         {"disease_id": resolved.get("efo_id"), "disease_name": resolved.get("name")}),
        ("fetching_genes", f"{genes} associated genes found (cached)", {"genes_found": genes}),
        ("fetching_drugs", f"{len(candidates)} candidate drugs found (cached)",
         {"candidates_found": len(candidates), "genes_without_drugs": len(no_drug_genes)}),
        ("ranking", f"Ranked {len(candidates)} candidates (cached)", {"ranked_count": len(candidates)}),
    ]
    for stage, message, counts in stages:
        job.queue.put_nowait(("progress", {"stage": stage, "status": "started", "message": "Loading from cache", "counts": {}}))
        await asyncio.sleep(0.12)
        job.queue.put_nowait(("progress", {"stage": stage, "status": "done", "message": message, "counts": counts}))
        await asyncio.sleep(0.05)

    job.queue.put_nowait(("complete", {"result": result, "cache_hit": True}))
    job.queue.put_nowait(_STREAM_DONE)


async def event_stream(job: Job, is_disconnected) -> AsyncGenerator[str, None]:
    """Yield SSE strings from a job's queue until completion or client disconnect.

    `is_disconnected` is an async callable (request.is_disconnected) polled so we
    stop promptly if the browser closes the tab.
    """
    job._consumed = True
    # Kick things off: an immediate 'open' comment keeps some proxies from buffering.
    yield ": stream open\n\n"

    while True:
        if await is_disconnected():
            logger.info("Client disconnected from stream %s", job.search_id)
            break
        try:
            item = await asyncio.wait_for(job.queue.get(), timeout=15.0)
        except asyncio.TimeoutError:
            # Heartbeat comment so idle connections (slow stages) aren't dropped.
            yield ": keep-alive\n\n"
            continue

        if item is _STREAM_DONE:
            break

        event_name, payload = item
        yield _sse_format(event_name, payload)

        if event_name in ("complete", "failed"):
            # The final payload has been sent; wait for the DONE sentinel to close.
            continue
