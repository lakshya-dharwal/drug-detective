"""FastAPI app wrapping the Phase 1 pipeline with REST + SSE.

Endpoints:
  POST /api/search                 -> {search_id, cache_hit}   (kicks off async job)
  GET  /api/search/{id}/stream     -> text/event-stream        (real progress SSE)
  GET  /api/search/{id}/result     -> final ranked results JSON (non-SSE fallback)
  GET  /api/health                 -> {status: ok}
"""

from __future__ import annotations

import logging
import os
import uuid

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from cache import get_cached_result, normalize_disease  # noqa: E402
from chat import answer_question  # noqa: E402
from models import (  # noqa: E402
    ChatRequest,
    ChatResponse,
    JobStatus,
    ResultResponse,
    SearchRequest,
    SearchResponse,
)
from sse import create_job, event_stream, get_job, replay_cached_job, run_job  # noqa: E402
import asyncio  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("drug_detective.api")

app = FastAPI(title="Drug Detective API", version="2.0.0")

# --- CORS --------------------------------------------------------------------
# Explicit allowlist (localhost + any set via ALLOWED_ORIGINS), PLUS a regex that
# matches every Vercel URL for this project. Vercel mints a new hostname per
# deployment (drug-detective-<hash>-<org>.vercel.app), so a static list can't
# keep up — the regex lets all of them (production, preview, per-deploy) through.
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]
# e.g. https://drug-detective.vercel.app, https://drug-detective-ahhwg4roi-...vercel.app
ALLOWED_ORIGIN_REGEX = os.getenv("ALLOWED_ORIGIN_REGEX", r"https://drug-detective[a-z0-9-]*\.vercel\.app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/search", response_model=SearchResponse)
async def start_search(body: SearchRequest, request: Request) -> SearchResponse:
    """Create a search job. Returns a search_id immediately and runs work async.

    Optionally stamps the search with the authenticated user id if the frontend
    forwarded one via `X-User-Id` (derived from a verified Supabase session).
    """
    disease = body.disease.strip()
    if not disease:
        raise HTTPException(status_code=400, detail="disease must not be empty")

    user_id = request.headers.get("X-User-Id") or None
    search_id = str(uuid.uuid4())
    job = create_job(search_id, disease, user_id)

    # Cache check: if a fresh cached result exists, serve it as a cache-hit job.
    cached = get_cached_result(normalize_disease(disease))
    if cached is not None:
        job.status = JobStatus.COMPLETE
        job.cache_hit = True
        job.result = cached
        resolved = cached.get("disease_resolved") or {}
        job.disease_id = resolved.get("efo_id")
        logger.info("Cache hit for '%s' (search %s)", disease, search_id)
        return SearchResponse(search_id=search_id, cache_hit=True)

    # Cache miss: launch the pipeline as a background task feeding the SSE queue.
    asyncio.create_task(run_job(job))
    return SearchResponse(search_id=search_id, cache_hit=False)


@app.get("/api/search/{search_id}/stream")
async def stream_search(search_id: str, request: Request) -> StreamingResponse:
    job = get_job(search_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown search_id")

    # For a cache hit, replay the checklist quickly instead of re-running.
    if job.cache_hit and job.result is not None:
        asyncio.create_task(replay_cached_job(job))

    generator = event_stream(job, request.is_disconnected)
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx/proxy buffering so events flush live
        },
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    """Grounded Q&A over one search's ranked results (display-only, never scores)."""
    result = await run_in_threadpool(answer_question, body.disease, body.question, body.drugs)
    return ChatResponse(answer=result["answer"], disabled=bool(result.get("disabled")))


@app.get("/api/search/{search_id}/result", response_model=ResultResponse)
async def get_result(search_id: str) -> ResultResponse:
    job = get_job(search_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown search_id")
    return ResultResponse(
        search_id=search_id,
        status=job.status,
        cache_hit=job.cache_hit,
        result=job.result,
        error=job.error,
    )
