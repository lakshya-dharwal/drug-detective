"use client";

/**
 * The single front-door control: one disease input + one action.
 * On submit it POSTs to the backend, gets a search_id, and routes to the
 * progress/results screen. Example chips prefill the box (optional convenience).
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { startSearch } from "@/lib/api";
import { supabase } from "@/lib/supabaseClient";

const EXAMPLES = ["glioblastoma", "rheumatoid arthritis", "pulmonary hypertension"];

export default function SearchBox() {
  const router = useRouter();
  const [disease, setDisease] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(name: string) {
    const q = name.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    try {
      const userId = supabase ? (await supabase.auth.getUser()).data.user?.id ?? null : null;
      const { search_id } = await startSearch(q, userId);
      router.push(`/search/${search_id}?disease=${encodeURIComponent(q)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="w-full max-w-xl">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(disease);
        }}
        className="relative"
      >
        <input
          autoFocus
          value={disease}
          onChange={(e) => setDisease(e.target.value)}
          placeholder="Enter a disease  —  e.g. glioblastoma"
          className="w-full rounded-2xl border border-neutral-300 bg-white px-6 py-5 text-lg text-neutral-900 shadow-sm outline-none transition placeholder:text-neutral-400 focus:border-accent focus:shadow-md dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:placeholder:text-neutral-500"
          disabled={busy}
        />
        <button
          type="submit"
          disabled={busy || !disease.trim()}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-xl bg-accent px-5 py-3 text-sm font-medium text-white transition hover:bg-accent-hover disabled:opacity-40 dark:text-black"
        >
          {busy ? "Searching…" : "Search"}
        </button>
      </form>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-xs text-neutral-400 dark:text-neutral-500">Try:</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => {
              setDisease(ex);
              run(ex);
            }}
            disabled={busy}
            className="rounded-full border border-neutral-200 px-3 py-1 text-xs text-neutral-600 transition hover:border-accent hover:bg-accent-soft hover:text-accent disabled:opacity-40 dark:border-neutral-700 dark:text-neutral-300"
          >
            {ex}
          </button>
        ))}
      </div>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
    </div>
  );
}
