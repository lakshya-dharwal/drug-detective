"use client";

/**
 * One ranked drug candidate. Collapsed by default: name, score, one-line reason,
 * trial-phase badge. Expands inline (no navigation) to reveal the Phase 1
 * weighted component breakdown and source links.
 *
 * The literature & safety components are Phase 1 placeholders — we surface them
 * honestly as "not yet assessed", never as fabricated values.
 */
import { useState } from "react";
import type { RankResult } from "@/lib/api";

const PHASE_LABEL: Record<string, string> = {
  approved: "Approved",
  phase3: "Phase 3",
  phase2: "Phase 2",
  phase1: "Phase 1",
  preclinical: "Preclinical",
  unknown: "Unknown",
};

const COMPONENT_LABELS: Record<string, string> = {
  gene_disease_evidence: "Gene–disease evidence",
  drug_target_evidence: "Drug–target evidence",
  clinical_trial_stage: "Clinical trial stage",
  literature_strength: "Literature strength",
  safety_penalty: "Safety penalty",
};


export default function ResultCard({ result, rank }: { result: RankResult; rank: number }) {
  const [open, setOpen] = useState(false);
  const reason = result.explanation.split(".")[0];

  return (
    <div className="rounded-2xl border border-neutral-200 bg-white transition hover:border-accent/50 dark:border-neutral-800 dark:bg-neutral-900 dark:hover:border-accent/50">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-4 px-5 py-4 text-left"
      >
        <span className="w-6 shrink-0 text-sm font-medium tabular-nums text-neutral-400">
          {rank}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate font-semibold text-neutral-900 dark:text-neutral-100">{result.drug_name}</h3>
            <PhaseBadge phase={result.max_clinical_phase} />
            {result.safety?.has_boxed_warning && (
              <span className="shrink-0 rounded-full border border-amber-400 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:border-amber-500/50 dark:bg-amber-500/10 dark:text-amber-400">
                ⚠ Boxed warning
              </span>
            )}
            {result.literature && result.literature.total_papers > 0 && (
              <span className="shrink-0 rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-semibold text-accent">
                {result.literature.total_papers} papers
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-sm text-neutral-500 dark:text-neutral-400">{reason}</p>
        </div>

        <ScorePill score={result.final_score} />

        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          className={`shrink-0 text-neutral-400 transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="animate-fade-up border-t border-neutral-100 px-5 py-4 dark:border-neutral-800">
          {result.mechanism_of_action && (
            <p className="mb-4 text-sm text-neutral-600 dark:text-neutral-400">
              <span className="font-medium text-neutral-800 dark:text-neutral-200">Mechanism:</span>{" "}
              {result.mechanism_of_action}
              {result.drug_type ? ` · ${result.drug_type}` : ""}
            </p>
          )}

          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-400">
            Score breakdown
          </h4>
          <div className="space-y-2">
            {Object.entries(result.component_scores).map(([key, cs]) => {
              const isPenalty = key === "safety_penalty";
              // A component with a note and a zero contribution wasn't assessed for this candidate.
              const notAssessed = cs.note != null && cs.weighted_contribution === 0 && cs.raw_score === 0;
              const contribution = cs.weighted_contribution;
              return (
                <div key={key} className="flex items-center gap-3 text-sm">
                  <span className="w-44 shrink-0 text-neutral-600 dark:text-neutral-400">
                    {COMPONENT_LABELS[key] ?? key}
                  </span>
                  {notAssessed ? (
                    <span className="text-xs italic text-neutral-400 dark:text-neutral-500" title={cs.note ?? ""}>
                      {isPenalty ? "no FDA data (neutral)" : "not assessed"}
                    </span>
                  ) : (
                    <>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-neutral-100 dark:bg-neutral-800">
                        <div
                          className={`h-full rounded-full ${isPenalty ? "bg-amber-500" : "bg-accent"}`}
                          style={{ width: `${Math.min(100, Math.max(0, cs.raw_score * 100))}%` }}
                        />
                      </div>
                      <span className="w-28 shrink-0 text-right tabular-nums text-neutral-500 dark:text-neutral-400">
                        {cs.raw_score.toFixed(2)} · {contribution >= 0 ? "+" : ""}
                        {contribution.toFixed(1)} pts
                      </span>
                    </>
                  )}
                </div>
              );
            })}
          </div>

          <EvidenceSections result={result} />

          <h4 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-neutral-400">
            Sources
          </h4>
          <div className="flex flex-wrap gap-2">
            {result.source_links.map((link) => (
              <a
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-full border border-neutral-200 px-3 py-1 text-xs text-neutral-600 transition hover:border-accent hover:text-accent dark:border-neutral-700 dark:text-neutral-300"
              >
                {link.source_name} ↗
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function EvidenceSections({ result }: { result: RankResult }) {
  const lit = result.literature;
  const safety = result.safety;
  const trials = result.trials;

  return (
    <div className="mt-5 space-y-5">
      {/* Literature */}
      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-400">
          Literature (PubMed)
        </h4>
        {lit && lit.total_papers > 0 ? (
          <div className="space-y-2">
            <p className="text-sm text-neutral-600 dark:text-neutral-300">
              <span className="font-semibold text-neutral-900 dark:text-neutral-100">{lit.total_papers}</span>{" "}
              publications ({lit.recent_papers} in the last 5 years).
            </p>
            {lit.summary && (
              <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-950">
                <p className="text-sm text-neutral-700 dark:text-neutral-300">{lit.summary}</p>
                {lit.summary_pmids.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {lit.summary_pmids.map((pmid) => (
                      <a
                        key={pmid}
                        href={`https://pubmed.ncbi.nlm.nih.gov/${pmid}/`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="rounded border border-accent/40 px-1.5 py-0.5 text-[11px] text-accent hover:bg-accent-soft"
                      >
                        PMID {pmid}
                      </a>
                    ))}
                  </div>
                )}
                <p className="mt-2 text-[10px] uppercase tracking-wide text-neutral-400">
                  AI summary of the cited abstracts only · display-only, not used in scoring
                </p>
              </div>
            )}
            {lit.papers.length > 0 && (
              <ul className="space-y-1">
                {lit.papers.map((p) => (
                  <li key={p.pmid} className="text-sm">
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-neutral-700 hover:text-accent dark:text-neutral-300"
                    >
                      {p.title || `PMID ${p.pmid}`}
                    </a>{" "}
                    <span className="text-xs text-neutral-400">
                      {p.journal ? `· ${p.journal}` : ""} {p.year ? `· ${p.year}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <p className="text-sm italic text-neutral-400 dark:text-neutral-500">
            {lit ? "No direct literature found for this drug–disease pair." : "Not assessed (outside evidence window)."}
          </p>
        )}
      </section>

      {/* Safety */}
      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-400">
          Safety (openFDA)
        </h4>
        {safety && safety.data_available ? (
          safety.flags.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {safety.flags.map((f) => (
                <a
                  key={f.kind}
                  href={f.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-full border border-amber-400 bg-amber-50 px-3 py-1 text-xs text-amber-700 hover:bg-amber-100 dark:border-amber-500/50 dark:bg-amber-500/10 dark:text-amber-400"
                >
                  {f.kind === "boxed_warning" ? "⚠ " : ""}
                  {f.label} ↗
                </a>
              ))}
            </div>
          ) : (
            <p className="text-sm text-neutral-600 dark:text-neutral-300">
              No boxed warnings or contraindications found in the FDA label.
            </p>
          )
        ) : (
          <p className="text-sm italic text-neutral-400 dark:text-neutral-500">
            No FDA safety data available (neutral — not penalized).
          </p>
        )}
      </section>

      {/* Trials */}
      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-400">
          Clinical Trials (ClinicalTrials.gov)
        </h4>
        {trials && trials.trial_count > 0 ? (
          <div className="space-y-2">
            <p className="text-sm text-neutral-600 dark:text-neutral-300">
              <span className="font-semibold text-neutral-900 dark:text-neutral-100">{trials.trial_count}</span>{" "}
              trials for this indication ({trials.active_count} active, {trials.completed_count} completed).
            </p>
            <div className="flex flex-wrap gap-2">
              {trials.trials.map((t) => (
                <a
                  key={t.nct_id}
                  href={t.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-full border border-neutral-200 px-3 py-1 text-xs text-neutral-600 transition hover:border-accent hover:text-accent dark:border-neutral-700 dark:text-neutral-300"
                  title={t.title}
                >
                  {t.nct_id} · {t.phase} · {t.status} ↗
                </a>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-sm italic text-neutral-400 dark:text-neutral-500">
            {trials ? "No matching trials found." : "Not assessed (outside evidence window)."}
          </p>
        )}
      </section>
    </div>
  );
}

function PhaseBadge({ phase }: { phase: string }) {
  const isApproved = phase === "approved";
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        isApproved
          ? "bg-accent text-white dark:text-black"
          : "border border-accent/40 bg-accent-soft text-accent"
      }`}
    >
      {PHASE_LABEL[phase] ?? phase}
    </span>
  );
}

function ScorePill({ score }: { score: number }) {
  return (
    <div className="flex shrink-0 flex-col items-end">
      <span className="text-lg font-bold tabular-nums text-accent">{score.toFixed(1)}</span>
      <span className="text-[10px] uppercase tracking-wide text-neutral-400">score</span>
    </div>
  );
}
