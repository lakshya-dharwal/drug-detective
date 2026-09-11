<div align="center">

# 🔬 Drug Detective

### A Self-Improving Research Agent for Drug Repurposing

*The agent doesn't just rank candidates — it investigates them, learns which lines of enquiry
failed, changes its own strategy, and writes what it found into a real system.*

</div>

---

## The problem

Most disease→drug tools answer once and stop. Ask again and you get the same answer, whether or
not the last one was any good.

Drug Detective runs an investigation **loop**. It picks candidates, gathers live evidence, screens
it, records what worked and what didn't, then **changes exactly one thing about how it
investigates** and goes again — so round 2 is measurably a different experiment from round 1.

## The loop

```
Completed search (64 ranked candidates)
        │
        ▼
  ROUND 1  ── pick top-ranked candidates
        │    ├─ You.com      → live web evidence, newer than any index
        │    └─ Daytona      → sandboxed screening (corroboration / quality / CONTRADICTION)
        ▼
  EXPERIENCE  ── append what worked + what failed to persistent memory
        │
        ▼
  STRATEGY   ── pure deterministic function reads memory, moves ONE lever:
        │       candidate_selection │ evidence_priority │ query_formulation
        ▼
  ROUND 2  ── genuinely different experiment
        │
        ▼
  ONE → writes the outcome into the user's real Notion workspace
```

Round 2's strategy is derived **by reading the memory file back**, not by passing state in
process. The loop really closes.

## The line we don't cross

> **No LLM touches the score, and no LLM chooses the adaptation.**

- **Ranking** is Phase 1's deterministic weighted sum (gene 35 / drug-target 30 / literature 20 /
  trials 10, safety −5). Unchanged by this project.
- **The strategy change** is a pure function in [`agent/strategy.py`](phase2/backend/agent/strategy.py) —
  same history in, same strategy out, every time. Unit-tested for exactly that.
- **CrewAI narrates** the decision for a human reader. It does not make it.
- A contradiction found in fresh evidence downgrades the **investigation verdict only** — never the
  scientific score.

That boundary is the point. It's what makes the adaptation reproducible and auditable instead of
vibes from a language model.

## Sponsor integrations

Each has exactly one defensible job. All four degrade to a skipped status rather than failing a round.

| | Role | Where |
|---|---|---|
| **You.com** | Live web evidence per hypothesis, every item stamped with source URL, query used, retrieval time. Makes the `query_formulation` lever real — it literally changes the search. | [`agent/youcom.py`](phase2/backend/agent/youcom.py) |
| **CrewAI** | 3 agents — Research, Evidence, Critic — narrate the round. The Critic explains an already-made deterministic decision. | [`agent/crew.py`](phase2/backend/agent/crew.py) |
| **Daytona** | Runs the screening script off-box. It executes untrusted scraped text, so it does not belong in the API process. Arithmetic stays deterministic. | [`agent/sandbox.py`](phase2/backend/agent/sandbox.py) |
| **One** | The external side effect: publishes the round's learning + strategy change to a real Notion workspace via the passthrough API. | [`agent/one_client.py`](phase2/backend/agent/one_client.py) |

**Clean Data** is the provenance layer, not a bolt-on: every evidence item carries `source`,
`url`, `query_used` and `retrieved_at`, and `sources_used` on each round reports honestly which
integrations actually ran.

## A real run

Live, ALS, ~20 seconds, nothing mocked:

```
ROUND 1   top_ranked · drug_disease framing · You.com 15 items · Daytona sandbox 7a2cc4d7
  TOFERSEN          conf 0.997  promising   screen 0.55 supported
  DEXTROMETHORPHAN  conf 0.755  promising   screen 0.39 weak
  CARBETAPENTANE    conf 0.100  weak        gaps: literature absent, trials absent

WHAT I LEARNED     1 of 3 candidates produced weak or inconclusive evidence.
WHAT I'M CHANGING  Deprioritize CARBETAPENTANE, investigate the next-ranked candidate.
                   Evidence sources and framing stay fixed, so any change in
                   confidence is attributable to the candidate switch.

LEVER  candidate_selection:  top_ranked → skip_unproductive
                             excluded:  [] → [CARBETAPENTANE]

ROUND 2   skip_unproductive · excluded CARBETAPENTANE
  TOFERSEN          conf 0.997  promising
  DEXTROMETHORPHAN  conf 0.755  promising
  DACOMITINIB       conf 0.100  weak

DELTA  0.000 — no confidence change
→ Logged to Notion ↗
```

**We are not dressing that up.** The agent correctly abandoned a dead end; the next-ranked
replacement happened to be weak too, so the mean didn't move. The UI shows `No confidence change`
in neutral grey. A demo that always shows improvement isn't demonstrating learning, it's
demonstrating a hardcoded string. `run_investigation(rounds=N)` keeps walking down the list.

## Architecture

```mermaid
flowchart LR
    U(["disease<br/>query"]) --> P

    subgraph EXISTING["Existing pipeline — UNTOUCHED"]
        direction LR
        P["Open Targets · PubMed<br/>openFDA · trials"] --> RANK["<b>Deterministic ranking</b><br/>35·30·20·10 −5<br/><b>no LLM</b>"]
    end

    RANK -->|"ranked<br/>candidates"| R1

    subgraph LOOP["Self-improving investigation loop — POST /api/investigate/:id"]
        direction LR
        R1["<b>ROUND N</b><br/>select<br/>candidates"] --> YOU["<b>You.com</b><br/>live evidence<br/>+ provenance"]
        YOU --> DAY["<b>Daytona</b><br/>sandboxed screen<br/>CONTRADICTION"]
        DAY --> EVAL["investigation<br/>confidence"]
        EVAL --> MEM[("<b>Experience</b><br/>worked /<br/>failed")]
        MEM --> STRAT["<b>strategy.py</b><br/>ONE lever<br/><b>no LLM</b>"]
        STRAT -.->|"<b>adapt & re-run</b>"| R1
    end

    STRAT --> ONE["<b>One</b>"] --> NOTION[("📝 <b>Real Notion page</b><br/>external side effect")]
    STRAT --> CREW["<b>CrewAI</b> · 3 agents<br/><i>narrates, does not decide</i>"]

    classDef untouched fill:#1e293b,stroke:#64748b,color:#e2e8f0
    classDef loop fill:#052e16,stroke:#22c55e,color:#dcfce7,stroke-width:2px
    classDef sponsor fill:#1e1b4b,stroke:#818cf8,color:#e0e7ff
    classDef sink fill:#422006,stroke:#f59e0b,color:#fef3c7
    class P,RANK untouched
    class R1,EVAL,STRAT loop
    class YOU,DAY,CREW,ONE sponsor
    class MEM,NOTION sink
```

**Read the diagram for two things.** First, the grey box is untouched — the scientific score is
still Phase 1's deterministic arithmetic. Second, follow the memory node: round 2's strategy is
derived by **reading experience back out of storage**, not by passing state in process. That is
what makes it a closed loop rather than a two-step script.

### Code layout

Additive. The existing pipeline was not rewritten.

```
phase1/src/            Phase 1 pipeline + deterministic ranking   ← UNTOUCHED
phase2/backend/
  main.py              FastAPI. + POST /api/investigate/{id}      ← 1 endpoint added
  agent/
    experience.py      persistent JSONL memory (Supabase-swappable)
    strategy.py        experiences → next strategy (pure, deterministic)
    rounds.py          round orchestration
    youcom.py  sandbox.py  one_client.py  crew.py
  tests/               15 local tests, no network, 0.06s
phase2/frontend/
  components/AgentInvestigation.tsx    the loop, made visible
```

`/api/investigate/{search_id}` reuses an **already-completed** search, so the multi-minute disease
pipeline never re-runs.

## Run it

```bash
# Backend — needs Python ≤3.12 (crewai's tiktoken has no 3.14 wheel)
cd phase2/backend
python3.12 -m venv .venv312 && ./.venv312/bin/pip install -r requirements.txt
cp .env.example .env        # add your keys
ENABLE_CREWAI=1 ./.venv312/bin/python -m uvicorn main:app --port 8000

# Frontend
cd phase2/frontend && npm install && npm run dev
```

Then search a disease, and hit **Run Agent Investigation** at the top of the results.

Every integration is optional. With no keys at all, the loop still runs on pipeline evidence —
you just lose live retrieval, sandboxed screening, narration and the Notion write.

## Tests

```bash
cd phase2/backend && ./.venv312/bin/python -m pytest tests/ -q     # 15 passed in 0.06s
```

Covers persistence, the default round-1 strategy, each adaptation lever, **the one-lever-per-round
invariant**, determinism, and full round orchestration. No network.

---

> ⚕️ **Research-support prototype.** Outputs are drug repurposing **hypotheses for investigation**,
> never treatment recommendations. Not medical advice.
