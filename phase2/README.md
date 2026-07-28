# Drug Detective — Phase 2 (Web App)

A web front-end + API wrapping the working Phase 1 pipeline. One search box →
real, SSE-streamed progress → ranked drug-repurposing results, with Supabase
for auth and result caching.

- **Frontend:** Next.js 14 (App Router) + TypeScript + Tailwind, on Vercel.
  White background, single green accent `#17A320`. Name: **Drug Detective**.
- **Backend:** FastAPI + uvicorn, on Render or Railway. Imports the Phase 1
  pipeline as a module (unmodified) and exposes it over REST + SSE.
- **DB/Auth/Cache:** Supabase (Postgres + Auth).

Phase 1 is **not rewritten**. The only change made to it is an *optional*
`progress_callback` hook at its existing stage boundaries; with no callback it
behaves exactly as before (its CLI and tests are unaffected).

```
Browser (Vercel)  ──POST /api/search──▶  FastAPI (Render/Railway)  ──imports──▶  Phase 1 pipeline
      │                                        │                                     │
      └──── SSE /stream ◀── real progress ─────┘                                     │
                                               └── writes result → Supabase cache ◀──┘
```

---

## Architecture / separation of concerns

- **Next.js = UI only.** No business logic; it calls FastAPI over HTTPS.
- **FastAPI = orchestration.** Wraps Phase 1, streams progress, writes cache.
- **Supabase = auth + Postgres cache** (+ storage for later phases).

### Real streaming (not fake timers)
Phase 1's pipeline invokes a synchronous `progress_callback(stage, status,
message, **counts)` at each real stage boundary (resolve disease → fetch genes
→ fetch drugs → rank). The backend runs the blocking pipeline in a threadpool
(`asyncio.to_thread`) and marshals each callback onto the event loop via
`loop.call_soon_threadsafe`, into a per-job `asyncio.Queue`. The SSE generator
yields from that queue. So every event on the UI checklist corresponds to
actual pipeline progress — a slow stage genuinely sits in "in progress".

### Job state (single-instance) — scaling note
In-flight job state + results live in a **process-local dict** (`sse.JOBS`).
This is correct for a single backend instance (Phase 2). **Horizontal scaling**
(multiple instances behind a load balancer) would need the job queue/state in
**Redis**, so the instance holding a client's SSE connection can see events
from the instance running that job. Documented here and in `backend/sse.py`.

---

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/search` | Body `{disease}`. Returns `{search_id, cache_hit}` immediately, kicks off async job. Checks Supabase cache first. |
| GET | `/api/search/{id}/stream` | SSE. Named events `progress` / `complete` / `failed`, plus keep-alive comments. |
| GET | `/api/search/{id}/result` | Final ranked results JSON (reload / non-SSE fallback). |
| GET | `/api/health` | Healthcheck for Render/Railway. |

SSE event data shape: `{stage, status: "started"|"done", message, counts}`.
Cache hits replay the same checklist quickly from cached counts (no re-run).

---

## Local development

### 1. Backend
```bash
cd phase2/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # works as-is locally (Supabase optional)
uvicorn main:app --reload --port 8000
```
The adapter finds Phase 1 at `../../phase1` by default (override with
`PHASE1_ROOT`). Without Supabase env vars set, the backend runs in
no-cache / no-persistence mode — search still works fully.

Quick check:
```bash
curl -s localhost:8000/api/health
SID=$(curl -s -X POST localhost:8000/api/search -H 'Content-Type: application/json' \
  -d '{"disease":"glioblastoma"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["search_id"])')
curl -N localhost:8000/api/search/$SID/stream     # watch real events stream
```

### 2. Frontend
```bash
cd phase2/frontend
npm install
cp .env.example .env.local   # set NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                  # http://localhost:3000
```

### 3. Supabase (optional locally, required in prod for cache/auth)
See [`supabase/README.md`](./supabase/README.md): create a project, apply
`supabase/migrations/001_init.sql`, enable Email + magic-link auth. Then fill
in the env vars below.

---

## Environment variables — which key goes where, and why

| Variable | Where | Exposed to browser? | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | frontend | yes | FastAPI base URL. |
| `NEXT_PUBLIC_SUPABASE_URL` | frontend | yes | Supabase project URL. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | frontend | yes | Anon key is **designed** to be public; gated by RLS. |
| `SUPABASE_URL` | backend | no | Same URL, server side. |
| `SUPABASE_SERVICE_ROLE_KEY` | backend | **NO — never** | Bypasses RLS. Backend-only; used for cache writes. Never put in any `NEXT_PUBLIC_*`. |
| `ALLOWED_ORIGINS` | backend | no | Comma-separated CORS allowlist (your Vercel URL + localhost). |
| `PHASE1_ROOT` | backend | no | Optional path override to the Phase 1 project. |

The **service role key** is backend-only because it bypasses Row Level
Security entirely — anything holding it can read/write all rows. The **anon
key** is safe in the browser because every table access it makes is filtered
by the RLS policies in the migration.

---

## Deployment

### Backend — Render (Docker)
1. New → **Web Service** → connect the repo.
2. **Root Directory:** repo root (the Dockerfile copies both `phase1/` and
   `phase2/backend/`). **Runtime:** Docker.
   **Dockerfile path:** `phase2/backend/Dockerfile`.
3. Render provides `$PORT`; the image's `CMD` already uses it.
4. Env vars: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
   `ALLOWED_ORIGINS=https://<your-app>.vercel.app`.
5. Health check path: `/api/health`.

### Backend — Railway (Docker)
1. New Project → **Deploy from repo**.
2. Set the service to build with **`phase2/backend/Dockerfile`** and build
   context = repo root (Railway: "Root Directory" = repo root, custom
   Dockerfile path). Start command is baked into the image
   (`uvicorn main:app --host 0.0.0.0 --port $PORT`); Railway injects `$PORT`.
3. Add the same env vars as Render.

> Both platforms build the **same Dockerfile** with the **repo root** as build
> context — that's required so Phase 1 can be copied alongside the backend.
> `docker build -f phase2/backend/Dockerfile -t drug-detective-api .`

### Frontend — Vercel
1. Import the repo; set **Root Directory** to `phase2/frontend`.
2. Env vars: `NEXT_PUBLIC_API_BASE_URL=https://<backend-host>`,
   `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
3. Build command `next build` (default). Deploy.

### CORS
FastAPI's `ALLOWED_ORIGINS` **must** include the exact Vercel origin
(`https://<app>.vercel.app`) and any custom domain, plus `http://localhost:3000`
for dev. Set it as a comma-separated list. SSE is a normal cross-origin GET, so
the same allowlist covers `/stream`.

---

## Auth (additive, non-gating)
Search works fully **without** logging in. Login (email/password or magic link
via Supabase Auth) is a small corner affordance; when present, the frontend
forwards the user id (`X-User-Id`) so searches are stamped with `user_id` for
Phase 5 history. RLS lets a user read only their own searches.

---

## What Phase 2 deliberately does **not** build
No PubMed / OpenFDA / ClinicalTrials.gov (Phase 3), no LangGraph / LLM (Phase
4), no save/compare/export/chat (Phase 5). The literature & safety score
components remain Phase 1 placeholders — the UI shows them as **"not yet
assessed (Phase 3)"** rather than faking values.

## File structure
```
phase2/
  backend/
    main.py              FastAPI app + routes (CORS, /search, /stream, /result, /health)
    sse.py               Job registry + thread→async SSE plumbing
    pipeline_adapter.py  Imports & wraps Phase 1 (adds no logic, just the progress bridge)
    supabase_client.py   Server-side Supabase (service role)
    cache.py             Supabase-backed result cache + search records
    models.py            Request/response models
    Dockerfile, requirements.txt, .env.example
  frontend/
    app/                 layout, landing (page.tsx), search/[id] (progress+results)
    components/          SearchBox, ProgressStream, ResultCard, AuthButton, Disclaimer, DnaMotif, Wordmark
    lib/                 supabaseClient.ts, api.ts, sse.ts
    tailwind.config.ts, .env.example
  supabase/
    migrations/001_init.sql   searches + cache tables + RLS
    README.md
```
