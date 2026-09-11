"use client";

/**
 * The self-improving loop, made visible: Round 1 → what it learned → what it
 * changed → Round 2 → the actual delta.
 *
 * Everything here renders exactly what the backend returned. Round 2 is NOT
 * assumed to be better: a flat or negative delta is shown as such, because the
 * honest result (the agent correctly abandoned a dead end and the replacement
 * was also weak) is more defensible than a manufactured improvement.
 */
import { useState } from "react";
import {
  runInvestigation,
  type InvestigationFinding,
  type InvestigationResponse,
  type InvestigationRound,
} from "@/lib/api";

const OUTCOME_STYLES: Record<string, string> = {
  promising: "border-accent/40 bg-accent-soft text-accent",
  weak: "border-orange-300 bg-orange-50 text-orange-700 dark:border-orange-900/60 dark:bg-orange-950/40 dark:text-orange-400",
  contradicted:
    "border-orange-300 bg-orange-50 text-orange-700 dark:border-orange-900/60 dark:bg-orange-950/40 dark:text-orange-400",
  inconclusive:
    "border-neutral-300 bg-neutral-100 text-neutral-600 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-400",
};

function outcomeClass(outcome: string): string {
  return OUTCOME_STYLES[outcome] ?? OUTCOME_STYLES.inconclusive;
}

/** Turn a snake_case backend token into something readable, without inventing meaning. */
function humanize(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(" › ") : "none";
  return String(value).replace(/_/g, " ");
}

function FindingRow({ finding }: { finding: InvestigationFinding }) {
  const screen = finding.screening ?? {};
  const failed = finding.what_failed ?? [];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-neutral-100 py-2 first:border-t-0 dark:border-neutral-800">
      <span className="font-medium text-neutral-900 dark:text-neutral-100">{finding.drug_name}</span>
      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${outcomeClass(finding.outcome)}`}>
        {finding.outcome}
      </span>
      <span className="text-xs text-neutral-500 dark:text-neutral-400">
        confidence <span className="font-semibold text-neutral-700 dark:text-neutral-200">{finding.investigation_confidence.toFixed(3)}</span>
      </span>
      {finding.target && (
        <span className="text-xs text-neutral-400 dark:text-neutral-500">target {finding.target}</span>
      )}
      {typeof finding.live_evidence_count === "number" && finding.live_evidence_count > 0 && (
        <span className="text-xs text-neutral-400 dark:text-neutral-500">
          {finding.live_evidence_count} live sources
        </span>
      )}
      {typeof screen.screening_score === "number" && (
        <span className="text-xs text-neutral-400 dark:text-neutral-500">
          screen {screen.screening_score.toFixed(2)}
          {screen.flag ? ` · ${screen.flag}` : ""}
        </span>
      )}
      {failed.length > 0 && (
        <span className="w-full text-xs text-neutral-400 dark:text-neutral-500">
          gaps: {failed.map((f) => humanize(f)).join(", ")}
        </span>
      )}
    </div>
  );
}

function RoundBlock({ round, label }: { round: InvestigationRound; label: string }) {
  const s = round.strategy;
  const sources = round.sources_used;
  return (
    <div className="rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">{label}</h4>
        <span className="text-xs text-neutral-500 dark:text-neutral-400">
          mean confidence{" "}
          <span className="font-semibold text-neutral-700 dark:text-neutral-200">
            {round.mean_confidence.toFixed(3)}
          </span>
        </span>
      </div>

      <p className="mb-2 text-xs text-neutral-500 dark:text-neutral-400">
        strategy: {humanize(s.candidate_selection)} · framing {humanize(s.query_formulation)} · evidence{" "}
        {humanize(s.evidence_priority)}
        {s.excluded_drugs.length > 0 && (
          <> · excluded {s.excluded_drugs.join(", ")}</>
        )}
      </p>

      <div>
        {round.findings.map((f) => (
          <FindingRow key={`${f.drug_chembl_id}-${f.drug_name}`} finding={f} />
        ))}
      </div>

      {sources && (sources.youcom || sources.daytona) && (
        <p className="mt-2 border-t border-neutral-100 pt-2 text-[11px] text-neutral-400 dark:border-neutral-800 dark:text-neutral-500">
          {sources.youcom && <>You.com live retrieval · {sources.live_evidence_items ?? 0} items</>}
          {sources.youcom && sources.daytona && " · "}
          {sources.daytona && <>Daytona sandbox screening</>}
        </p>
      )}
    </div>
  );
}

export default function AgentInvestigation({ searchId }: { searchId: string }) {
  const [data, setData] = useState<InvestigationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      setData(await runInvestigation(searchId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The investigation could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  const delta = data?.improvement.delta ?? 0;
  // Honest framing: only a real positive delta reads as improvement.
  const deltaStyle =
    delta > 0
      ? "border-accent/40 bg-accent-soft text-accent"
      : delta < 0
        ? "border-orange-300 bg-orange-50 text-orange-700 dark:border-orange-900/60 dark:bg-orange-950/40 dark:text-orange-400"
        : "border-neutral-300 bg-neutral-100 text-neutral-600 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-400";
  const deltaLabel =
    delta > 0
      ? `Confidence improved +${delta.toFixed(3)}`
      : delta < 0
        ? `Confidence regressed ${delta.toFixed(3)}`
        : "No confidence change";

  const published = data?.published;
  const diff = data?.strategy_diff;
  // Backend returns every round; round_1/round_2 alias first and last.
  const allRounds = data ? (data.rounds ?? [data.round_1, data.round_2]) : [];

  return (
    <div className="mb-5 rounded-2xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
          Self-Improving Investigation
        </h3>
        <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-semibold text-accent">AGENT</span>
      </div>
      <p className="mb-3 text-xs text-neutral-400 dark:text-neutral-500">
        The agent investigates a few candidates, records what worked, then changes its strategy and tries
        again. Ranking above is untouched — this is a separate investigation signal.
      </p>

      {!data && (
        <button
          onClick={run}
          disabled={busy}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent-hover disabled:opacity-60 dark:text-black"
        >
          {busy ? "Investigating…" : "Run Agent Investigation"}
        </button>
      )}

      {busy && !data && (
        <p className="mt-3 animate-pulse-soft text-xs text-neutral-500 dark:text-neutral-400">
          Round 1 → retrieving live evidence → sandboxed screening → learning → Round 2. Takes ~20s.
        </p>
      )}

      {error && (
        <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400">
          <p>{error}</p>
          <button onClick={run} className="mt-2 text-xs font-medium underline hover:no-underline">
            Try again
          </button>
        </div>
      )}

      {data && (
        <div className="animate-fade-up space-y-3">
          {/* Cross-investigation memory: only shown when the agent actually
              recalled a previous run of this disease. */}
          {data.prior_experience?.recalled && (
            <div className="rounded-xl border border-accent/30 bg-accent-soft/30 p-3">
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-accent">
                Recalled from previous investigations
              </p>
              <p className="text-xs text-neutral-600 dark:text-neutral-300">
                {data.prior_experience.what_i_recalled}
              </p>
              {data.prior_experience.carried_exclusions.length > 0 && (
                <p className="mt-1 font-mono text-[11px] text-neutral-500 dark:text-neutral-400">
                  already ruled out: {data.prior_experience.carried_exclusions.join(", ")}
                </p>
              )}
            </div>
          )}

          <RoundBlock round={allRounds[0]} label="Round 1" />

          {/* What I learned */}
          <div className="rounded-xl border-l-2 border-neutral-300 bg-neutral-50 p-4 dark:border-neutral-600 dark:bg-neutral-800/50">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
              What I learned
            </p>
            <p className="text-sm text-neutral-700 dark:text-neutral-200">{data.learning.what_i_learned}</p>
          </div>

          {/* What I'm changing */}
          <div className="rounded-xl border-l-2 border-accent bg-accent-soft/40 p-4">
            <p className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-accent">
              <span aria-hidden>↳</span> What I&apos;m changing
            </p>
            <p className="text-sm text-neutral-700 dark:text-neutral-200">{data.learning.what_i_am_changing}</p>

            {diff?.changed_lever && (
              <div className="mt-2.5 border-t border-accent/20 pt-2.5">
                <p className="font-mono text-xs text-neutral-600 dark:text-neutral-300">
                  {humanize(diff.changed_lever)}:
                </p>
                {Object.entries(diff.changes).map(([field, change]) => (
                  <p key={field} className="font-mono text-xs text-neutral-500 dark:text-neutral-400">
                    {humanize(change.before)} <span className="text-accent">→</span> {humanize(change.after)}
                  </p>
                ))}
              </div>
            )}
          </div>

          {allRounds.slice(1).map((r, i) => (
            <RoundBlock
              key={r.round_number}
              round={r}
              label={`Round ${r.round_number} — adapted${
                i === allRounds.length - 2 && allRounds.length > 2 ? " (final)" : ""
              }`}
            />
          ))}

          {/* Actual outcome — never dressed up */}
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${deltaStyle}`}>
              {deltaLabel}
            </span>
            <span className="text-xs text-neutral-500 dark:text-neutral-400">
              {data.improvement.mean_confidence_round_1.toFixed(3)} →{" "}
              {data.improvement.mean_confidence_round_2.toFixed(3)} · promising{" "}
              {data.improvement.promising_round_1} → {data.improvement.promising_round_2}
            </span>
          </div>

          {/* One / Notion — rendered ONLY on a real success */}
          {published?.published && published.page_url && (
            <a
              href={published.page_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block rounded-full border border-accent/40 bg-accent-soft px-3 py-1 text-xs font-medium text-accent transition hover:border-accent"
            >
              Logged to {published.platform ?? "Notion"} ↗
            </a>
          )}

          {data.learning.crew && (
            <details className="rounded-xl border border-neutral-200 p-3 dark:border-neutral-800">
              <summary className="cursor-pointer text-[11px] text-neutral-400 dark:text-neutral-500">
                AI commentary from {data.learning.crew.agents.length} CrewAI agents — supplementary,
                not the decision
              </summary>
              {data.learning.crew.narrative_learned && (
                <p className="mt-2 text-xs text-neutral-600 dark:text-neutral-300">
                  {data.learning.crew.narrative_learned}
                </p>
              )}
              {data.learning.crew.narrative_changing && (
                <p className="mt-1.5 text-xs text-neutral-600 dark:text-neutral-300">
                  {data.learning.crew.narrative_changing}
                </p>
              )}
              {(data.learning.crew.possibly_unsupported_terms?.length ?? 0) > 0 && (
                <p className="mt-2 text-[11px] text-orange-600 dark:text-orange-400">
                  ⚠ This narrative mentions terms not found in the investigated candidates
                  ({data.learning.crew.possibly_unsupported_terms!.join(", ")}). The strategy change
                  above is the authoritative, deterministic one.
                </p>
              )}
            </details>
          )}
        </div>
      )}
    </div>
  );
}
