"use client";

/**
 * Ask-the-results chat. Sends the user's question plus a compact context built
 * from the current ranked results to the backend, which answers ONLY from that
 * data. Display-only — never changes any score. On-brand, minimal.
 */
import { useState } from "react";
import { askChat, toChatContext, type PipelineResult } from "@/lib/api";

interface Turn {
  q: string;
  a: string | null; // null while loading
}

const SUGGESTIONS = [
  "Which drug has the strongest evidence?",
  "Are any of the top drugs unsafe?",
  "Which are already approved vs still in trials?",
];

export default function ChatBox({ result }: { result: PipelineResult }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setInput("");
    setTurns((t) => [...t, { q, a: null }]);
    try {
      const ctx = toChatContext(result.ranked_candidates);
      const { answer } = await askChat(result.disease_resolved?.name ?? result.disease_query, q, ctx);
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, a: answer } : turn)));
    } catch {
      setTurns((t) =>
        t.map((turn, i) => (i === t.length - 1 ? { ...turn, a: "Sorry — that request failed. Try again." } : turn))
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-8 rounded-2xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Ask about these results</h3>
        <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-semibold text-accent">AI</span>
      </div>
      <p className="mb-3 text-xs text-neutral-400 dark:text-neutral-500">
        Answers are grounded only in the ranked results above — not medical advice.
      </p>

      {turns.length > 0 && (
        <div className="mb-3 space-y-3">
          {turns.map((t, i) => (
            <div key={i} className="space-y-1.5">
              <p className="text-sm font-medium text-neutral-800 dark:text-neutral-200">{t.q}</p>
              {t.a === null ? (
                <p className="text-sm text-neutral-400 animate-pulse-soft">Thinking…</p>
              ) : (
                <p className="rounded-lg bg-neutral-50 p-3 text-sm text-neutral-700 dark:bg-neutral-950 dark:text-neutral-300">
                  {t.a}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {turns.length === 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => ask(s)}
              disabled={busy}
              className="rounded-full border border-neutral-200 px-3 py-1 text-xs text-neutral-600 transition hover:border-accent hover:text-accent disabled:opacity-40 dark:border-neutral-700 dark:text-neutral-300"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
        className="flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about the ranked drugs…"
          disabled={busy}
          className="flex-1 rounded-lg border border-neutral-300 px-3 py-2 text-sm outline-none focus:border-accent dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent-hover disabled:opacity-40 dark:text-black"
        >
          Ask
        </button>
      </form>
    </div>
  );
}
