/**
 * Browser Supabase client using the ANON (public) key only.
 * The service role key never touches the frontend — that lives on the backend.
 *
 * Returns null when env vars are absent so the app runs without auth configured
 * (search is not gated behind auth in Phase 2).
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const supabase: SupabaseClient | null =
  url && anonKey ? createClient(url, anonKey) : null;

export const isSupabaseConfigured = Boolean(url && anonKey);
