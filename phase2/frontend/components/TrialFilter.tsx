"use client";

/**
 * Minimal, on-brand filter for the results list. Filters by clinical status /
 * evidence, driven entirely by data already present on each RankResult (no
 * extra requests). Purely client-side.
 */
import type { RankResult } from "@/lib/api";

export type TrialFilterValue = "all" | "in_trials" | "approved" | "has_trials" | "preclinical";

export const FILTERS: { value: TrialFilterValue; label: string }[] = [
  { value: "all", label: "All" },
  { value: "approved", label: "Approved" },
  { value: "in_trials", label: "In trials (Ph 1–3)" },
  { value: "has_trials", label: "Has trials for this disease" },
  { value: "preclinical", label: "Preclinical only" },
];

export function matchesFilter(r: RankResult, f: TrialFilterValue): boolean {
  switch (f) {
    case "all":
      return true;
    case "approved":
      return r.max_clinical_phase === "approved";
    case "in_trials":
      return ["phase1", "phase2", "phase3"].includes(r.max_clinical_phase);
    case "has_trials":
      return (r.trials?.trial_count ?? 0) > 0;
    case "preclinical":
      return r.max_clinical_phase === "preclinical" || r.max_clinical_phase === "unknown";
    default:
      return true;
  }
}

export default function TrialFilter({
  value,
  onChange,
  counts,
}: {
  value: TrialFilterValue;
  onChange: (v: TrialFilterValue) => void;
  counts: Record<TrialFilterValue, number>;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {FILTERS.map((f) => {
        const active = value === f.value;
        return (
          <button
            key={f.value}
            onClick={() => onChange(f.value)}
            className={`rounded-full border px-3 py-1 text-xs transition ${
              active
                ? "border-accent bg-accent text-white dark:text-black"
                : "border-neutral-200 text-neutral-600 hover:border-accent hover:text-accent dark:border-neutral-700 dark:text-neutral-300"
            }`}
          >
            {f.label} <span className={active ? "opacity-80" : "text-neutral-400"}>({counts[f.value]})</span>
          </button>
        );
      })}
    </div>
  );
}
