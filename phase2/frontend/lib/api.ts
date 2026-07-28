/**
 * Typed calls to the FastAPI backend. The base URL comes from
 * NEXT_PUBLIC_API_BASE_URL (e.g. http://localhost:8000 in dev, the Render/Railway
 * URL in prod). All business logic lives in the backend; this is a thin client.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface StartSearchResponse {
  search_id: string;
  cache_hit: boolean;
}

// ---- Result payload types (mirror Phase 1's PipelineResult serialization) ----

export interface ComponentScore {
  raw_score: number;
  weight_pct: number;
  weighted_contribution: number;
  note: string | null;
}

export interface SourceLink {
  source_name: string;
  url: string;
}

export interface PubMedPaper {
  pmid: string;
  title: string;
  journal: string;
  year: string;
  url: string;
}

export interface LiteratureInfo {
  literature_strength: number;
  total_papers: number;
  recent_papers: number;
  top_pmids: string[];
  papers: PubMedPaper[];
  summary: string | null;
  summary_pmids: string[];
}

export interface SafetyFlag {
  kind: string;
  label: string;
  source_url: string;
}

export interface SafetyInfo {
  safety_penalty: number;
  has_boxed_warning: boolean;
  flags: SafetyFlag[];
  data_available: boolean;
}

export interface ClinicalTrial {
  nct_id: string;
  title: string;
  phase: string;
  status: string;
  url: string;
}

export interface TrialsInfo {
  trial_count: number;
  active_count: number;
  completed_count: number;
  trials: ClinicalTrial[];
}

export interface RankResult {
  drug_chembl_id: string;
  drug_name: string;
  disease_efo_id: string;
  disease_name: string;
  target_ensembl_id: string;
  target_hgnc_symbol: string;
  final_score: number;
  component_scores: Record<string, ComponentScore>;
  explanation: string;
  source_links: SourceLink[];
  max_clinical_phase: string;
  drug_type: string | null;
  mechanism_of_action: string | null;
  literature: LiteratureInfo | null;
  safety: SafetyInfo | null;
  trials: TrialsInfo | null;
}

export interface GeneWithoutDrugs {
  ensembl_id: string;
  hgnc_symbol: string;
  association_score: number;
  source_url: string;
}

export interface PipelineResult {
  disease_query: string;
  disease_resolved: { efo_id: string; name: string } | null;
  status_message: string | null;
  gene_count: number;
  ranked_candidates: RankResult[];
  genes_without_drugs: GeneWithoutDrugs[];
  warnings: { stage: string; message: string }[];
  generated_at: string;
}

export interface ResultResponse {
  search_id: string;
  status: "running" | "complete" | "failed";
  cache_hit: boolean;
  result: PipelineResult | null;
  error: string | null;
}

/** Kick off a search. If the user is logged in, forward their id for stamping. */
export async function startSearch(
  disease: string,
  userId?: string | null
): Promise<StartSearchResponse> {
  const res = await fetch(`${API_BASE}/api/search`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(userId ? { "X-User-Id": userId } : {}),
    },
    body: JSON.stringify({ disease }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Search failed (${res.status}): ${detail}`);
  }
  return res.json();
}

/** Non-SSE fallback: fetch the final result directly (used for reload/polling). */
export async function fetchResult(searchId: string): Promise<ResultResponse> {
  const res = await fetch(`${API_BASE}/api/search/${searchId}/result`);
  if (!res.ok) throw new Error(`Result fetch failed (${res.status})`);
  return res.json();
}

export function streamUrl(searchId: string): string {
  return `${API_BASE}/api/search/${searchId}/stream`;
}

export interface ChatResponse {
  answer: string;
  disabled: boolean;
}

/** Grounded Q&A over a search's results. `drugs` is a compact context array. */
export async function askChat(
  disease: string,
  question: string,
  drugs: Record<string, unknown>[]
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ disease, question, drugs }),
  });
  if (!res.ok) throw new Error(`Chat failed (${res.status})`);
  return res.json();
}

/** Build a compact, token-friendly context for the chat from ranked results. */
export function toChatContext(candidates: RankResult[], limit = 15): Record<string, unknown>[] {
  return candidates.slice(0, limit).map((c, i) => ({
    rank: i + 1,
    drug: c.drug_name,
    score: c.final_score,
    target: c.target_hgnc_symbol,
    phase: c.max_clinical_phase,
    mechanism: c.mechanism_of_action,
    papers: c.literature?.total_papers ?? null,
    recent_papers: c.literature?.recent_papers ?? null,
    boxed_warning: c.safety?.has_boxed_warning ?? null,
    trials: c.trials?.trial_count ?? null,
    reason: c.explanation,
  }));
}

/** Client-side CSV export of the ranked results. */
export function resultsToCsv(disease: string, candidates: RankResult[]): string {
  const header = [
    "rank",
    "drug_name",
    "chembl_id",
    "final_score",
    "target",
    "max_clinical_phase",
    "total_papers",
    "recent_papers",
    "boxed_warning",
    "trial_count",
    "mechanism_of_action",
  ];
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = candidates.map((c, i) =>
    [
      i + 1,
      c.drug_name,
      c.drug_chembl_id,
      c.final_score,
      c.target_hgnc_symbol,
      c.max_clinical_phase,
      c.literature?.total_papers ?? "",
      c.literature?.recent_papers ?? "",
      c.safety?.has_boxed_warning ?? "",
      c.trials?.trial_count ?? "",
      c.mechanism_of_action ?? "",
    ]
      .map(esc)
      .join(",")
  );
  return [`# Drug Detective results for: ${disease}`, header.join(","), ...rows].join("\n");
}
