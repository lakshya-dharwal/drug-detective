-- ============================================================================
-- Drug Detective — Phase 3 evidence cache
-- A unified evidence_cache table for PubMed literature, LLM summaries, OpenFDA
-- safety, and ClinicalTrials.gov results, keyed by (evidence_type, cache_key)
-- with a per-row expiry (default 30 days). Written only by the backend service
-- role; world-readable (non-sensitive public data).
-- ============================================================================

do $$
begin
  if not exists (select 1 from pg_type where typname = 'evidence_type') then
    create type evidence_type as enum ('literature', 'llm_summary', 'safety', 'trials');
  end if;
end$$;

create table if not exists public.evidence_cache (
  evidence_type evidence_type not null,
  cache_key     text not null,          -- e.g. "drug::disease" (normalized) or "drug"
  payload       jsonb not null,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null,
  primary key (evidence_type, cache_key)
);

create index if not exists evidence_cache_expires_at_idx on public.evidence_cache (expires_at);

alter table public.evidence_cache enable row level security;

-- Non-sensitive public bioinformatics data: readable by anyone. Writes are
-- service-role only (which bypasses RLS), so no write policy is granted here.
drop policy if exists "evidence readable by all" on public.evidence_cache;
create policy "evidence readable by all"
  on public.evidence_cache
  for select
  using (true);
