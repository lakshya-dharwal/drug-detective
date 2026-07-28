# Drug Repurposing Research Tool — Phase 1

A deterministic, explainable data pipeline that takes a disease name and
returns a ranked list of drug repurposing candidates with full score
breakdowns and source citations. No UI, no LLM calls — pure backend logic,
run via CLI.

## What it does

```
disease name
  -> resolve to canonical disease ID (Open Targets search)
  -> disease -> associated genes (Open Targets disease-target associations)
  -> gene -> known/candidate drugs (Open Targets target-drug associations)
  -> weighted, explainable rank score per drug (ranking_engine.py)
  -> sorted candidate list + genes with no known drugs + warnings
```

Every gene is resolved to an **Ensembl gene ID** and every drug to a
**ChEMBL ID** before anything else happens (`src/entity_resolver.py`), so all
downstream joins are keyed on stable canonical identifiers rather than
free-text names.

## Setup

```bash
cd phase1
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # defaults work out of the box; edit if needed
```

## Usage

```bash
python main.py "glioblastoma"
```

Prints: resolved disease name/ID, number of associated genes found, a ranked
drug table (name, score, top reason, trial phase), genes with no known
drugs, and any warnings (missing data, API failures, cache fallbacks used).

## Ranking algorithm

Implemented as a pure function, `ranking_engine.calculate_rank_score`. Full
weights (tunable constants at the top of `ranking_engine.py`):

| Component               | Weight | Phase 1 status                                  |
|--------------------------|-------:|--------------------------------------------------|
| gene_disease_evidence    |    35% | live (Open Targets disease-target score)          |
| drug_target_evidence     |    30% | live (specificity-derived, see below)             |
| literature_strength      |    20% | **placeholder = 0**, weight redistributed (Phase 3: PubMed) |
| clinical_trial_stage     |    10% | live (mapped from max clinical trial phase)       |
| safety_penalty           | -5% max | **placeholder = 0** (Phase 3: OpenFDA)            |

**Literature redistribution:** Open Targets has no PubMed integration yet, so
`literature_strength` always scores 0 in Phase 1. Rather than let that
artificially deflate every score, its 20% weight is redistributed
*proportionally* across the three components that are actually scored this
phase, so their effective Phase 1 weights become ~44.3% / 38% / ~12.7%
(summing to the same 95-point positive budget). This is computed once at
import time as `PHASE1_EFFECTIVE_WEIGHTS`.

**Drug-target confidence:** Open Targets doesn't expose a raw numeric
confidence score for a specific gene-drug pair (only per-drug clinical
stage). We derive one ourselves: for each of a drug's mechanism-of-action
entries that names our target gene, confidence = 1 / (number of distinct
targets sharing that MoA entry) — a drug hitting one gene per MoA line is a
more specific, confident association than one hitting ten genes at once. We
take the best (max) specificity across matching entries, falling back to a
flat 0.5 if the drug reached us only through the target's candidate list
with no explicit MoA link.

Every `RankResult` includes `component_scores` (raw + weighted contribution
per factor), a human-readable `explanation`, and `source_links` for every
data point used.

## Graceful degradation

- Zero gene associations for a disease -> empty list + explanatory status message, no crash.
- A gene with zero known drugs -> excluded from ranking, listed separately under "genes with no known drugs".
- API failures: retry once with exponential backoff (2 retries total = 3 attempts), then fall back to cached data (even if stale) if available, then surface a `PipelineWarning` and continue with partial results. The pipeline never raises out of `run_pipeline`.
- Thin drug metadata from Open Targets (missing drug type or trial phase) falls back to ChEMBL.

## Caching

`src/cache_manager.py` caches every raw API response as a JSON file under
`data/api_cache/`, keyed by a hash of the request key, with a 30-day expiry
(`CACHE_EXPIRY_DAYS` in `.env`). Expired entries are still usable as a
last-resort fallback if a live call fails. Resolved entities (gene/drug/
disease name -> canonical ID) are cached indefinitely in
`data/entity_cache.json` since that mapping doesn't go stale.

## Benchmark

`benchmark/benchmark_dataset.json` has 17 real, documented drug repurposing
cases (e.g. thalidomide for multiple myeloma, sildenafil for pulmonary
arterial hypertension, dexamethasone for COVID-19) with source citations.

```bash
python benchmark/evaluate_benchmark.py --top-n 10
```

Runs the pipeline against every benchmark disease, resolves the known drug
to a ChEMBL ID (so name variants don't cause false negatives), and reports
`X/17 known drugs appeared in top 10 (Y%)`. Full per-case results are
written to `benchmark/benchmark_results.json`.

A real run of this benchmark currently scores **3/17 = ~18% top-10 recall**.
That's a genuine measurement, and the misses have been diagnosed to two
distinct, well-understood causes rather than a bug:

1. **Candidate-recall gap (7 of 14 misses).** metformin, minoxidil,
   dexamethasone, ivermectin, onabotulinumtoxinA, canakinumab, and
   thalidomide-for-leprosy never appear as candidates *at all*, because their
   drug target isn't among the disease's Open Targets associated-gene set.
   The target-centric path (disease -> gene -> drug) structurally cannot reach
   a drug whose mechanism isn't captured by a top gene association. A bigger
   gene window does not help (25 -> 50 gave identical results); reaching these
   needs a complementary disease -> known-drug path or the Phase 3 evidence
   layers.

2. **Crowding (the remaining misses).** The known drug *is* in the list with a
   strong score, but competes against dozens of other approved drugs that
   target the disease's high-association genes and look equally plausible on
   the only signals Phase 1 has (gene-association x target-confidence x trial
   phase). E.g. methotrexate for RA scores 78/100 but ranks ~83, because RA
   has that many higher-scoring approved candidates. The distinguishing
   signal — disease-specific clinical/literature evidence — is exactly the
   Phase 3 signal not yet built.

Two Phase-1 improvements were made off the back of this analysis, and both are
kept because they improve output quality (even though neither moved top-10
recall on this harsh metric):

- **Gentler drug-target confidence curve.** The original `1/n` specificity
  formula sent a drug that names this gene among 4 co-targets to 0.25 — *below*
  the 0.5 fallback given to a drug with no mechanism info at all, an inverted
  ranking. It's now `CONFIDENCE_FLOOR + (1 - CONFIDENCE_FLOOR)/n` with the
  no-mechanism case pinned below any explicit match. (thalidomide's target
  confidence went 0.25 -> 0.55.)
- **Parent-molecule de-duplication.** Salt/hydrate/ester child molecules
  (FILGOTINIB MALEATE, RUXOLITINIB PHOSPHATE, ...) are collapsed onto their
  parent active molecule via Open Targets' `parentMolecule`, so one drug no
  longer occupies several ranked slots. This tightened the near-misses
  (baricitinib for COVID-19 moved from rank 15 to 11, one slot from top-10;
  sildenafil for PAH 19 -> 14) without gaming the metric.

The headline recall is unchanged at 18% because the dominant limitation is
missing evidence signal, not scoring mechanics — which is the intended finding
of building the benchmark *alongside* Phase 1 rather than after.

## Tests

```bash
pytest tests/                    # unit tests only (fast, mocked)
pytest tests/ -m integration      # + integration tests (real APIs, slower)
pytest tests/ -m ""                # everything
```

- `test_ranking_engine.py` — verifies the weighted-sum math against manual calculations, using mock component scores.
- `test_entity_resolver.py` — resolves known gene/drug synonyms against mocked Open Targets responses.
- `test_pipeline.py` — end-to-end integration test against the real APIs for glioblastoma and pulmonary hypertension, plus an unresolvable-disease graceful-failure case.

## File structure

```
phase1/
  src/
    entity_resolver.py     # name/symbol -> canonical Ensembl/ChEMBL ID, cached
    open_targets_client.py # Open Targets GraphQL client (search, disease-target, target-drug)
    chembl_client.py       # ChEMBL REST fallback for thin drug metadata
    cache_manager.py       # local JSON cache with 30-day expiry
    ranking_engine.py       # pure weighted scoring function
    models.py               # all pydantic models
    pipeline.py              # orchestration: disease name -> ranked candidates
  data/
    entity_cache.json       # resolved entity lookup table (created on first run)
    api_cache/               # cached raw API responses
  benchmark/
    benchmark_dataset.json
    evaluate_benchmark.py
  tests/
  main.py                    # CLI entry point
```

## What's deliberately not here

No FastAPI, no frontend, no Supabase, no LangGraph, no PubMed, no OpenFDA, no
LLM calls. Phase 1 is a 100% deterministic data pipeline and scoring engine.
Those integrations are Phase 2/3.
