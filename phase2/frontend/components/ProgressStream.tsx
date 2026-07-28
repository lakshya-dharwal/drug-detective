"use client";

/**
 * SSE consumer + live checklist. Each stage line advances to "done" ONLY when
 * its real SSE event arrives (never on a timer). Slow stages honestly stay in
 * the in-progress state; fast ones flow quickly.
 *
 * Fallbacks: on SSE transport error it polls /result until the job finishes, so
 * a dropped stream still resolves.
 */
import { useEffect, useRef, useState } from "react";
import { openSearchStream, type ProgressPayload } from "@/lib/sse";
import { fetchResult, type PipelineResult } from "@/lib/api";
import DnaMotif from "./DnaMotif";

type StageState = "pending" | "active" | "done";

const STAGES: { key: string; label: string }[] = [
  { key: "resolving_disease", label: "Resolving disease" },
  { key: "fetching_genes", label: "Fetching gene associations" },
  { key: "fetching_drugs", label: "Finding candidate drugs" },
  { key: "fetching_literature", label: "Searching PubMed literature" },
  { key: "checking_safety", label: "Checking FDA safety data" },
  { key: "checking_trials", label: "Finding clinical trials" },
  { key: "summarizing_evidence", label: "Summarizing key findings" },
  { key: "ranking", label: "Ranking candidates" },
];

function countLabel(counts: Record<string, number | string | null>): string | null {
  if (counts.genes_found != null) return `${counts.genes_found} genes`;
  if (counts.candidates_found != null) return `${counts.candidates_found} candidates`;
  if (counts.enriched != null) return `${counts.enriched} assessed`;
  if (counts.boxed_warnings != null) return `${counts.boxed_warnings} warnings`;
  if (counts.with_trials != null) return `${counts.with_trials} with trials`;
  if (counts.ranked_count != null) return `${counts.ranked_count} ranked`;
  if (counts.disease_name != null) return String(counts.disease_name);
  return null;
}

export default function ProgressStream({
  searchId,
  onComplete,
  onFailed,
}: {
  searchId: string;
  onComplete: (result: PipelineResult) => void;
  onFailed: (error: string) => void;
}) {
  const [states, setStates] = useState<Record<string, StageState>>(
    Object.fromEntries(STAGES.map((s) => [s.key, "pending"]))
  );
  const [labels, setLabels] = useState<Record<string, string | null>>({});
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let done = false;

    const applyProgress = (p: ProgressPayload) => {
      setStates((prev) => {
        const next = { ...prev };
        if (p.status === "started") next[p.stage] = "active";
        if (p.status === "done") {
          next[p.stage] = "done";
          // Mark any earlier still-pending stages done (defensive ordering).
          const idx = STAGES.findIndex((s) => s.key === p.stage);
          STAGES.slice(0, idx).forEach((s) => {
            if (next[s.key] !== "done") next[s.key] = "done";
          });
        }
        return next;
      });
      const label = countLabel(p.counts);
      if (label) setLabels((prev) => ({ ...prev, [p.stage]: label }));
    };

    const startPolling = () => {
      if (pollTimer.current) return;
      pollTimer.current = setInterval(async () => {
        try {
          const r = await fetchResult(searchId);
          if (r.status === "complete" && r.result) {
            done = true;
            stopPolling();
            onComplete(r.result);
          } else if (r.status === "failed") {
            done = true;
            stopPolling();
            onFailed(r.error ?? "Pipeline failed");
          }
        } catch {
          /* keep polling */
        }
      }, 2000);
    };
    const stopPolling = () => {
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
    };

    const close = openSearchStream(searchId, {
      onProgress: applyProgress,
      onComplete: (result) => {
        done = true;
        onComplete(result);
      },
      onFailed: (err) => {
        done = true;
        onFailed(err);
      },
      onError: () => {
        // Transport dropped — fall back to polling the result endpoint.
        if (!done) startPolling();
      },
    });

    return () => {
      close();
      stopPolling();
    };
  }, [searchId, onComplete, onFailed]);

  return (
    <div className="relative mx-auto w-full max-w-md">
      <div className="pointer-events-none absolute -right-24 top-1/2 -translate-y-1/2 hidden lg:block">
        <DnaMotif animated />
      </div>

      <ol className="space-y-1">
        {STAGES.map((s) => {
          const state = states[s.key];
          return (
            <li
              key={s.key}
              className="flex items-center gap-3 rounded-xl px-4 py-3.5 transition"
            >
              <StageIcon state={state} />
              <span
                className={
                  state === "done"
                    ? "text-neutral-900 dark:text-neutral-100"
                    : state === "active"
                    ? "text-neutral-900 dark:text-neutral-100"
                    : "text-neutral-400 dark:text-neutral-600"
                }
              >
                {s.label}
              </span>
              {state === "active" && (
                <span className="ml-auto text-xs text-accent animate-pulse-soft">in progress…</span>
              )}
              {state === "done" && labels[s.key] && (
                <span className="ml-auto text-xs font-medium text-accent">{labels[s.key]}</span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function StageIcon({ state }: { state: StageState }) {
  if (state === "done") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-white dark:text-black">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
          <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    );
  }
  if (state === "active") {
    return (
      <span className="flex h-6 w-6 items-center justify-center">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </span>
    );
  }
  return <span className="h-6 w-6 rounded-full border-2 border-neutral-200 dark:border-neutral-700" />;
}
