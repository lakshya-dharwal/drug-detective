# Phase 3 — Real Evidence Layers

Phase 3 replaces Phase 1's placeholder score components with three real,
source-linked evidence layers, and surfaces them in the Phase 2 UI. Every
displayed claim links to its source; **scores stay 100% deterministic** and the
LLM is used for display narration only — never for scoring, ranking, or facts.

## The three layers

| Layer | Source (real API) | Feeds | Deterministic? |
|---|---|---|---|
| Literature | PubMed E-utilities | `literature_strength` (20%) | Yes — from paper counts |
| Safety | openFDA drug label | `safety_penalty` (−5% max) | Yes — from label fields |
| Trials | ClinicalTrials.gov v2 | enriches trial signal + UI filter | Yes — factual counts |

### Layer 1 — PubMed literature (`pubmed_client.py` + `literature_scorer.py`)
Deterministic score from retrieved metadata, not LLM output:
```
paper_count_score = min(total_papers / 20, 1.0)
recency_score     = min(recent_papers(last 5y) / 10, 1.0)
literature_strength = 0.6*paper_count_score + 0.4*recency_score
```
Throttled to NCBI limits (3/s, or 10/s with `NCBI_API_KEY`), cached per pair.

### Layer 2 — openFDA safety (`openfda_client.py` + `safety_scorer.py`)
`boxed warning → 1.0 severity` (full −5% penalty); `contraindications → 0.4`;
**no FDA record → 0 (neutral, never penalized)**. Factual flags with label links
on the card. No LLM interpretation.

### Layer 3 — ClinicalTrials.gov (`clinicaltrials_client.py`)
Real trial counts, phases, statuses, NCT links per drug-disease pair; drives the
results-screen filter (Approved / In trials / Has trials / Preclinical).

### LLM summarizer (`llm_summarizer.py`) — display-only, hard guardrails
- Summarizes **only the retrieved abstracts**; cites PMIDs; says "Limited
  published evidence" instead of speculating; temperature 0.2; token usage logged.
- No abstracts → no LLM call (fixed "No direct literature found" string).
- **No `OPENAI_API_KEY` → summaries silently disabled**; the paper list still shows.
- Cached per (drug, disease). **Never influences any score.**

## Ranking changes (`ranking_engine.py`)
The Phase 1 literature-redistribution hack is gone; intended weights restored:
`gene 35 + drug-target 30 + literature 20 + trial 10` (= 95) and `safety −5`.
Explanations now read e.g. *"strong gene-disease association (0.68), 221 supporting
publications, 29 relevant clinical trials … Carries an FDA boxed warning."*

## Cost & rate control
- Evidence is fetched only for the **top `MAX_EVIDENCE_ENRICHMENT` (default 40)**
  candidates by biology score, then the list is re-ranked (two-pass). Candidates
  outside the window keep `literature/safety = 0` ("not assessed").
- LLM summaries + paper lists only for the final **`DISPLAY_TOP_N` (default 10)**.
- Everything cached (local JSON per pair; Supabase whole-result + `evidence_cache`
  table via `002_evidence_cache.sql`).

## Benchmark: before → after

Re-running the 17 known-repurposing cases (`benchmark/evaluate_benchmark.py`):

| Metric | Phase 1 baseline | + Literature | + All layers |
|---|---|---|---|
| **Top-10 recall** | **3/17 (17.6%)** | **5/17 (29.4%)** | **5/17 (29.4%)** |

**Newly recovered into the top 10 (by real literature):**

| Disease | Known drug | Phase 1 rank | Phase 3 rank |
|---|---|---:|---:|
| pulmonary arterial hypertension | sildenafil | 14 | **5** |
| COVID-19 | baricitinib | 11 | **1** |

(baricitinib reached #1 once the safety layer penalized boxed-warning competitors
above it — a legitimate re-ordering, not tuning.)

**No regressions:** the safety penalty did not drop any known drug out of the top
10. Adding all layers held recall at 29.4%.

**Why the other 12 still miss — honest, structural (unchanged from Phase 1):**
1. **7 are never candidates** (metformin, minoxidil, dexamethasone, ivermectin,
   canakinumab, onabotulinumtoxinA, leprosy/thalidomide): their target isn't in
   the disease's Open Targets gene set, so no evidence layer can reach them.
2. **5 rank below the top-40 enrichment window** (methotrexate 83, thalidomide 79,
   naltrexone 74, nintedanib 118, brexanolone 219): they never get literature
   scored. Raising `MAX_EVIDENCE_ENRICHMENT` reaches them at more API cost.

No weights were tuned to chase the benchmark. The gain is real evidence doing
real work on candidates the pipeline can actually see.

## New SSE stages (Phase 2 streaming, real progress)
`fetching_literature` → `checking_safety` → `checking_trials` →
`summarizing_evidence`, each fired from actual backend work.

## Keys — all optional
`NCBI_API_KEY` (faster PubMed), `OPENFDA_API_KEY` (higher limits), `OPENAI_API_KEY`
(enables display summaries). The pipeline runs fully without any of them.
