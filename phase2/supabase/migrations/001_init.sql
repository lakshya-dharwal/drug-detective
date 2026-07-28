-- ============================================================================
-- Drug Detective — Phase 2 initial schema
-- searches + search_results_cache, with Row Level Security.
-- Apply via: supabase db push  (or paste into the Supabase SQL editor).
-- ============================================================================

-- ---- enum: search job status ----------------------------------------------
do $$
begin
  if not exists (select 1 from pg_type where typname = 'search_status') then
    create type search_status as enum ('running', 'complete', 'failed');
  end if;
end$$;

-- ---- table: searches -------------------------------------------------------
-- One row per search request. user_id is nullable: anonymous searches are
-- allowed (Phase 2 does not gate search behind auth). Logged-in searches are
-- stamped with the user so Phase 5 can show history.
create table if not exists public.searches (
  id                 uuid primary key,
  disease_raw        text not null,
  disease_normalized text not null,
  disease_id         text,                       -- EFO/MONDO id (may be null if unresolved)
  user_id            uuid references auth.users(id) on delete set null,
  status             search_status not null default 'running',
  result_count       int not null default 0,
  created_at         timestamptz not null default now()
);

create index if not exists searches_disease_normalized_idx on public.searches (disease_normalized);
create index if not exists searches_user_id_idx           on public.searches (user_id);
create index if not exists searches_created_at_idx        on public.searches (created_at desc);

-- ---- table: search_results_cache ------------------------------------------
-- Whole-PipelineResult cache keyed by normalized disease name, 30-day expiry.
-- Treated as a hit only when now() < expires_at (enforced in app code).
create table if not exists public.search_results_cache (
  disease_normalized text primary key,
  disease_id         text,
  result_json        jsonb not null,
  created_at         timestamptz not null default now(),
  expires_at         timestamptz not null
);

create index if not exists search_results_cache_expires_at_idx on public.search_results_cache (expires_at);

-- ============================================================================
-- Row Level Security
-- ============================================================================
-- The backend uses the SERVICE ROLE key, which BYPASSES RLS entirely — so all
-- cache writes and search inserts from FastAPI work regardless of these policies.
-- These policies govern access from the browser (anon / authenticated keys),
-- e.g. Phase 5's history features using @supabase/supabase-js directly.

alter table public.searches            enable row level security;
alter table public.search_results_cache enable row level security;

-- ---- searches policies -----------------------------------------------------
-- A logged-in user may read only their own searches. Anonymous searches
-- (user_id is null) are NOT readable via the public anon key — they are only
-- retrievable through the backend (service role) by search_id. This satisfies
-- "users can only read their own searches; anonymous searches not exposed
-- broadly."
drop policy if exists "read own searches" on public.searches;
create policy "read own searches"
  on public.searches
  for select
  using (auth.uid() is not null and auth.uid() = user_id);

-- Clients do not insert searches directly (the backend does, via service role),
-- so no INSERT/UPDATE policy is granted to anon/authenticated. Absence of a
-- permissive policy = denied for non-service-role callers.

-- ---- search_results_cache policies ----------------------------------------
-- The cache is non-sensitive (public bioinformatics data) and may be read by
-- anyone, enabling an optional client-side cache peek. Writes remain
-- service-role-only (no write policy granted here).
drop policy if exists "cache readable by all" on public.search_results_cache;
create policy "cache readable by all"
  on public.search_results_cache
  for select
  using (true);
