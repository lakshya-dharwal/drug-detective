"use client";

/**
 * Minimal, non-intrusive auth affordance for the top-right corner.
 * Auth is ADDITIVE in Phase 2 — search works fully without logging in. Logging
 * in simply lets searches be stamped with the user id (for Phase 5 history).
 *
 * Supports email/password and magic link via Supabase Auth. Degrades to a
 * disabled hint when Supabase isn't configured.
 */
import { useEffect, useState } from "react";
import { supabase, isSupabaseConfigured } from "@/lib/supabaseClient";
import type { User } from "@supabase/supabase-js";

export default function AuthButton() {
  const [user, setUser] = useState<User | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getUser().then(({ data }) => setUser(data.user ?? null));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) =>
      setUser(session?.user ?? null)
    );
    return () => sub.subscription.unsubscribe();
  }, []);

  if (!isSupabaseConfigured) {
    return null; // no auth backend configured; keep the corner clean
  }

  if (user) {
    return (
      <div className="flex items-center gap-3">
        <span className="hidden sm:inline text-sm text-neutral-600 dark:text-neutral-400">{user.email}</span>
        <button
          onClick={() => supabase!.auth.signOut()}
          className="rounded-full border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 transition hover:border-accent hover:text-accent dark:border-neutral-700 dark:text-neutral-300"
        >
          Sign out
        </button>
      </div>
    );
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded-full border border-neutral-300 px-4 py-1.5 text-sm text-neutral-700 transition hover:border-accent hover:text-accent dark:border-neutral-700 dark:text-neutral-300"
      >
        Login
      </button>
      {open && <AuthModal onClose={() => setOpen(false)} />}
    </>
  );
}

function AuthModal({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"signin" | "signup" | "magic">("signin");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!supabase) return;
    setBusy(true);
    setMsg(null);
    try {
      if (mode === "magic") {
        const { error } = await supabase.auth.signInWithOtp({ email });
        setMsg(error ? error.message : "Check your email for a magic link.");
      } else if (mode === "signup") {
        const { error } = await supabase.auth.signUp({ email, password });
        setMsg(error ? error.message : "Account created. Check email to confirm, then sign in.");
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) setMsg(error.message);
        else onClose();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-2xl border border-neutral-200 bg-white p-6 shadow-xl dark:border-neutral-800 dark:bg-neutral-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
            {mode === "signup" ? "Create account" : mode === "magic" ? "Magic link" : "Sign in"}
          </h2>
          <button onClick={onClose} className="text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200">
            ✕
          </button>
        </div>

        <div className="space-y-3">
          <input
            type="email"
            placeholder="you@lab.edu"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-accent dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100 dark:placeholder:text-neutral-500"
          />
          {mode !== "magic" && (
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-accent dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100 dark:placeholder:text-neutral-500"
            />
          )}
          <button
            onClick={submit}
            disabled={busy || !email}
            className="w-full rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent-hover disabled:opacity-50 dark:text-black"
          >
            {busy ? "…" : mode === "signup" ? "Sign up" : mode === "magic" ? "Send link" : "Sign in"}
          </button>
        </div>

        {msg && <p className="mt-3 text-xs text-neutral-600 dark:text-neutral-400">{msg}</p>}

        <div className="mt-4 flex justify-between text-xs text-neutral-500 dark:text-neutral-400">
          <button className="hover:text-accent" onClick={() => setMode(mode === "signup" ? "signin" : "signup")}>
            {mode === "signup" ? "Have an account? Sign in" : "Create account"}
          </button>
          <button className="hover:text-accent" onClick={() => setMode(mode === "magic" ? "signin" : "magic")}>
            {mode === "magic" ? "Use password" : "Email magic link"}
          </button>
        </div>
      </div>
    </div>
  );
}
