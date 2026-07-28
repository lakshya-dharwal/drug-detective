# Supabase setup — Drug Detective Phase 2

This directory holds the database schema (auth is managed by Supabase Auth
automatically; no migration needed for `auth.users`).

## 1. Create a project
Create a project at [supabase.com](https://supabase.com). From
**Project Settings → API**, note:

- **Project URL** → `SUPABASE_URL` (backend) and `NEXT_PUBLIC_SUPABASE_URL` (frontend)
- **anon public** key → `NEXT_PUBLIC_SUPABASE_ANON_KEY` (frontend, browser-safe)
- **service_role** key → `SUPABASE_SERVICE_ROLE_KEY` (**backend only — never ship to the browser**)

## 2. Apply the migration

### Option A — Supabase CLI (recommended)
```bash
supabase link --project-ref <your-project-ref>
supabase db push
```

### Option B — SQL editor
Open **SQL Editor** in the Supabase dashboard, paste the contents of
`migrations/001_init.sql`, and run it.

## 3. Enable auth methods
**Authentication → Providers**: enable **Email** (password) and, for magic
links, ensure "Confirm email" / email OTP is on. Set the **Site URL** to your
frontend origin (e.g. `http://localhost:3000` in dev, your Vercel URL in prod)
so magic-link redirects work.

## What the migration creates
- `searches` — one row per search (nullable `user_id`; anonymous allowed).
- `search_results_cache` — whole-result cache keyed by normalized disease name, 30-day expiry.
- **RLS**: logged-in users can read only their own searches; the cache is
  world-readable (non-sensitive public data). All backend writes use the
  **service role** key, which bypasses RLS — so the policies only constrain
  direct browser access (used from Phase 5 onward).
