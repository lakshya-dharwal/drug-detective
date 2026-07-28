"use client";

/**
 * Progress + results, on one continuous screen. While the job runs, the SSE-driven
 * checklist shows. On completion it swaps inline to the ranked results. Handles
 * empty results (friendly Phase 1 message), failures (retry), and reload (the
 * page re-opens the stream; if the job already finished the /result fallback in
 * ProgressStream resolves it).
 */
import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import ProgressStream from "@/components/ProgressStream";
import ResultCard from "@/components/ResultCard";
import Wordmark from "@/components/Wordmark";
import DnaMotif from "@/components/DnaMotif";
import ThemeToggle from "@/components/ThemeToggle";
import TrialFilter, { FILTERS, matchesFilter, type TrialFilterValue } from "@/components/TrialFilter";
import ChatBox from "@/components/ChatBox";
import { resultsToCsv, type PipelineResult } from "@/lib/api";

type View = "progress" | "results" | "failed";

export default function SearchPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const disease = searchParams.get("disease") ?? "";

  const [view, setView] = useState<View>("progress");
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleComplete = useCallback((r: PipelineResult) => {
    setResult(r);
    setView("results");
  }, []);
  const handleFailed = useCallback((e: string) => {
    setError(e);
    setView("failed");
  }, []);

  return (
    <main className="relative mx-auto min-h-screen w-full max-w-3xl px-4 pb-28">
      <header className="flex items-center justify-between py-6">
        <Link href="/">
          <Wordmark size="sm" />
        </Link>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <Link
            href="/"
            className="rounded-full border border-neutral-300 px-4 py-1.5 text-sm text-neutral-700 transition hover:border-accent hover:text-accent dark:border-neutral-700 dark:text-neutral-300"
          >
            New search
          </Link>
        </div>
      </header>

      <div className="mb-8">
        <p className="text-sm text-neutral-400 dark:text-neutral-500">Searching for</p>
        <h1 className="text-2xl font-semibold capitalize text-neutral-900 dark:text-neutral-100">
          {result?.disease_resolved?.name ?? disease}
        </h1>
      </div>

      {view === "progress" && (
        <div className="py-10">
          <ProgressStream
            searchId={params.id}
            onComplete={handleComplete}
            onFailed={handleFailed}
          />
        </div>
      )}

      {view === "failed" && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center dark:border-red-900/50 dark:bg-red-950/40">
          <p className="text-red-700 dark:text-red-400">{error ?? "Something went wrong."}</p>
          <Link
            href="/"
            className="mt-4 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover dark:text-black"
          >
            Try another search
          </Link>
        </div>
      )}

      {view === "results" && result && <Results result={result} />}
    </main>
  );
}

function Results({ result }: { result: PipelineResult }) {
  const candidates = result.ranked_candidates;
  const [filter, setFilter] = useState<TrialFilterValue>("all");

  const counts = useMemo(() => {
    const c = {} as Record<TrialFilterValue, number>;
    for (const f of FILTERS) c[f.value] = candidates.filter((r) => matchesFilter(r, f.value)).length;
    return c;
  }, [candidates]);

  const visible = useMemo(() => candidates.filter((r) => matchesFilter(r, filter)), [candidates, filter]);

  const diseaseName = result.disease_resolved?.name ?? result.disease_query;
  function downloadCsv() {
    const csv = resultsToCsv(diseaseName, candidates);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `drug-detective-${diseaseName.replace(/\s+/g, "-").toLowerCase()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Empty-but-successful case (e.g. no gene associations) — styled as intentional.
  if (candidates.length === 0) {
    return (
      <div className="animate-fade-up rounded-2xl border border-neutral-200 bg-white p-8 text-center dark:border-neutral-800 dark:bg-neutral-900">
        <div className="mx-auto mb-4 w-fit opacity-70">
          <DnaMotif />
        </div>
        <p className="text-neutral-600 dark:text-neutral-300">
          {result.status_message ??
            "No candidate drugs were found for this disease."}
        </p>
      </div>
    );
  }

  return (
    <div className="animate-fade-up">
      <div className="mb-4 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            <span className="font-semibold text-neutral-900 dark:text-neutral-100">{candidates.length}</span>{" "}
            ranked candidates · {result.gene_count} associated genes
          </p>
          <button
            onClick={downloadCsv}
            className="shrink-0 rounded-full border border-neutral-300 px-3 py-1 text-xs text-neutral-600 transition hover:border-accent hover:text-accent dark:border-neutral-700 dark:text-neutral-300"
          >
            ↓ Export CSV
          </button>
        </div>
        <TrialFilter value={filter} onChange={setFilter} counts={counts} />
      </div>

      <div className="space-y-2.5">
        {visible.map((c) => (
          <ResultCard key={c.drug_chembl_id} result={c} rank={candidates.indexOf(c) + 1} />
        ))}
        {visible.length === 0 && (
          <p className="rounded-2xl border border-neutral-200 p-6 text-center text-sm text-neutral-500 dark:border-neutral-800 dark:text-neutral-400">
            No candidates match this filter.
          </p>
        )}
      </div>

      {result.genes_without_drugs.length > 0 && (
        <details className="mt-8 rounded-2xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
          <summary className="cursor-pointer text-sm font-medium text-neutral-600 dark:text-neutral-300">
            Associated genes with no known drugs ({result.genes_without_drugs.length})
          </summary>
          <div className="mt-3 flex flex-wrap gap-2">
            {result.genes_without_drugs.map((g) => (
              <a
                key={g.ensembl_id}
                href={g.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-full border border-neutral-200 px-3 py-1 text-xs text-neutral-600 transition hover:border-accent hover:text-accent dark:border-neutral-700 dark:text-neutral-300"
                title={`Association score ${g.association_score.toFixed(2)}`}
              >
                {g.hgnc_symbol} ↗
              </a>
            ))}
          </div>
        </details>
      )}

      {result.warnings.length > 0 && (
        <details className="mt-3 rounded-2xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
          <summary className="cursor-pointer text-sm font-medium text-neutral-500 dark:text-neutral-400">
            {result.warnings.length} data warning(s)
          </summary>
          <ul className="mt-3 space-y-1 text-xs text-neutral-500 dark:text-neutral-400">
            {result.warnings.map((w, i) => (
              <li key={i}>
                <span className="font-medium">[{w.stage}]</span> {w.message}
              </li>
            ))}
          </ul>
        </details>
      )}

      <ChatBox result={result} />
    </div>
  );
}
