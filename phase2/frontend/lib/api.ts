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
