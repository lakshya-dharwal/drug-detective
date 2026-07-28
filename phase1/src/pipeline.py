"""Main orchestration: disease name -> ranked drug repurposing candidates.

disease_name -> resolve_disease -> get_disease_gene_associations -> for each
gene, get_target_drugs -> calculate_rank_score for each drug -> sorted PipelineResult.

Never raises on data-source failure; every failure mode degrades to a
PipelineWarning and, where possible, partial results.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from src import chembl_client
from src.clinicaltrials_client import get_trials
from src.entity_resolver import resolve_disease
from src.literature_scorer import score_literature
from src.llm_summarizer import summarize_evidence
from src.models import (
    GeneWithoutDrugs,
    LiteratureInfo,
    PipelineResult,
    PipelineWarning,
    PubMedPaper,
    RankingInput,
    SourceLink,
    TrialPhase,
)
from src.open_targets_client import OpenTargetsAPIError, get_disease_gene_associations, get_target_drugs
from src.pubmed_client import get_summaries
from src.ranking_engine import calculate_rank_score
from src.safety_scorer import score_safety

logger = logging.getLogger(__name__)

# A stage-boundary progress hook: (stage, status, human_message, **counts) -> None.
# Optional everywhere; when absent the pipeline behaves exactly as before.
ProgressCallback = Callable[..., None]

# How many top disease-associated genes to pull drug candidates for, and how
# many drug candidates to consider per gene. Kept modest to bound API/cache
# volume per run; tune as needed.
MAX_GENES_TO_QUERY = 25
MAX_DRUGS_PER_GENE = 50

# Phase 3 evidence enrichment. Fetching PubMed/OpenFDA/CT.gov for every candidate
# is too many calls, so the top-N candidates by provisional biology score are
# enriched and the list is re-ranked. Tunable via env for benchmarking.
MAX_EVIDENCE_ENRICHMENT = int(os.getenv("MAX_EVIDENCE_ENRICHMENT", "40"))
# Display-only paper list + LLM summary are generated for the final top-N cards.
DISPLAY_TOP_N = int(os.getenv("DISPLAY_TOP_N", "10"))
ENABLE_LITERATURE = os.getenv("ENABLE_LITERATURE", "1") != "0"
ENABLE_SAFETY = os.getenv("ENABLE_SAFETY", "1") != "0"
ENABLE_TRIALS = os.getenv("ENABLE_TRIALS", "1") != "0"

OPEN_TARGETS_UI_BASE = "https://platform.opentargets.org"

# --- Drug-target confidence tuning -------------------------------------------
# Open Targets exposes no raw numeric target-drug confidence, so we derive one
# from mechanism-of-action specificity. A drug whose MoA entry names ONLY this
# gene is the most confident signal (1.0); one whose MoA entry lists several
# targets is less specific but still a real, direct binder. The confidence for
# an explicit MoA match with n co-listed targets is:
#     CONFIDENCE_FLOOR + (1 - CONFIDENCE_FLOOR) / n
# so n=1 -> 1.0, n=2 -> 0.70, n=4 -> 0.55, decaying gently toward the floor
# instead of the old harsh 1/n (which sent 4-target drugs to 0.25).
CONFIDENCE_FLOOR = 0.40
# A drug reached only via the target's candidate list, with no MoA entry that
# names this gene, carries genuine uncertainty. It must sit BELOW an explicit
# multi-target match (fixing the old inversion where "no info" 0.5 outscored an
# explicit 4-target match 0.25), so we pin it under the floor.
NO_MOA_MATCH_CONFIDENCE = 0.30

CLINICAL_STAGE_MAP: dict[str, TrialPhase] = {
    "APPROVED": TrialPhase.APPROVED,
    "PHASE_4": TrialPhase.APPROVED,
    "PHASE_3": TrialPhase.PHASE_3,
    "PHASE_2": TrialPhase.PHASE_2,
    "PHASE_1": TrialPhase.PHASE_1,
    "PHASE_0": TrialPhase.PRECLINICAL,
    "PRECLINICAL": TrialPhase.PRECLINICAL,
}


def _map_clinical_stage(raw_stage: str | None) -> TrialPhase:
    if not raw_stage:
        return TrialPhase.UNKNOWN
    return CLINICAL_STAGE_MAP.get(raw_stage.upper(), TrialPhase.UNKNOWN)


def _drug_target_confidence(moa_rows: list[dict], target_ensembl_id: str) -> float:
    """Specificity-derived confidence that a drug meaningfully targets this gene.

    For each mechanism-of-action entry that explicitly names this target, the
    confidence is CONFIDENCE_FLOOR + (1 - CONFIDENCE_FLOOR) / n, where n is the
    number of distinct targets sharing that MoA entry - a drug hitting this gene
    alone in one MoA line is the most confident signal, and confidence decays
    gently (not as a harsh 1/n) as the entry names more co-targets, since a
    multi-target drug still genuinely binds this gene. We take the best (max)
    confidence across matching MoA entries. If no MoA entry names this gene at
    all (the drug only reached us via the target's candidate list), we return
    NO_MOA_MATCH_CONFIDENCE, which is pinned below any explicit match.
    """
    best = None
    for row in moa_rows or []:
        target_ids = [t.get("id") for t in (row.get("targets") or [])]
        if target_ensembl_id in target_ids and target_ids:
            n = len(target_ids)
            confidence = CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) / n
            if best is None or confidence > best:
                best = confidence
    return best if best is not None else NO_MOA_MATCH_CONFIDENCE


def run_pipeline(disease_name: str, progress_callback: ProgressCallback | None = None) -> PipelineResult:
    """Disease name -> ranked repurposing candidates.

    `progress_callback`, if provided, is invoked at each real stage boundary as
    progress_callback(stage, status, message, **counts). It is purely a
    notification hook: the pipeline's behaviour and return value are identical
    whether or not it is supplied, so the CLI and tests call it with no callback.
    """

    def emit(stage: str, status: str, message: str, **counts) -> None:
        if progress_callback is not None:
            progress_callback(stage, status, message, **counts)

    warnings: list[PipelineWarning] = []

    emit("resolving_disease", "started", f"Resolving '{disease_name}' to a canonical disease ID")
    resolved_disease = resolve_disease(disease_name)
    if resolved_disease is None:
        emit("resolving_disease", "done", f"Could not resolve '{disease_name}'")
        return PipelineResult(
            disease_query=disease_name,
            disease_resolved=None,
            status_message=(
                f"Could not resolve '{disease_name}' to a known disease in Open Targets. "
                "Check spelling, or try a broader/alternate name."
            ),
        )
    emit(
        "resolving_disease",
        "done",
        f"Resolved to {resolved_disease.name} ({resolved_disease.efo_id})",
        disease_id=resolved_disease.efo_id,
        disease_name=resolved_disease.name,
    )

    emit("fetching_genes", "started", "Fetching disease-gene associations from Open Targets")
    try:
        disease_data = get_disease_gene_associations(resolved_disease.efo_id, max_genes=MAX_GENES_TO_QUERY)
    except OpenTargetsAPIError as exc:
        logger.error("Disease-gene association lookup failed: %s", exc)
        emit("fetching_genes", "done", "Open Targets unavailable and no cached data", genes_found=0)
        return PipelineResult(
            disease_query=disease_name,
            disease_resolved=resolved_disease,
            status_message="Open Targets API is currently unavailable and no cached data exists for this disease.",
            warnings=[PipelineWarning(stage="disease_gene_associations", message=str(exc))],
        )

    gene_rows = (disease_data or {}).get("associatedTargets", {}).get("rows", [])
    if not gene_rows:
        emit("fetching_genes", "done", "No gene associations found", genes_found=0)
        return PipelineResult(
            disease_query=disease_name,
            disease_resolved=resolved_disease,
            status_message=(
                "No gene associations found in Open Targets for this disease. "
                "This may be a rare or non-genetic condition."
            ),
        )
    emit("fetching_genes", "done", f"{len(gene_rows)} associated genes found", genes_found=len(gene_rows))

    disease_source_url = f"{OPEN_TARGETS_UI_BASE}/disease/{resolved_disease.efo_id}"

    inputs_by_drug: dict[str, RankingInput] = {}
    best_candidate_score: dict[str, float] = {}
    genes_without_drugs: list[GeneWithoutDrugs] = []

    emit(
        "fetching_drugs",
        "started",
        f"Finding candidate drugs across {len(gene_rows)} genes",
        genes_total=len(gene_rows),
    )
    for row in gene_rows:
        target = row.get("target") or {}
        ensembl_id = target.get("id")
        hgnc_symbol = target.get("approvedSymbol")
        gene_score = row.get("score", 0.0)
        if not ensembl_id or not hgnc_symbol:
            continue

        target_source_url = f"{OPEN_TARGETS_UI_BASE}/target/{ensembl_id}"

        try:
            target_data = get_target_drugs(ensembl_id, max_drugs=MAX_DRUGS_PER_GENE)
        except OpenTargetsAPIError as exc:
            logger.warning("Drug lookup failed for target %s (%s): %s", ensembl_id, hgnc_symbol, exc)
            warnings.append(
                PipelineWarning(
                    stage="target_drug_associations",
                    message=f"Could not fetch drug candidates for gene {hgnc_symbol}: {exc}",
                )
            )
            continue

        drug_rows = (target_data or {}).get("drugAndClinicalCandidates", {}).get("rows", [])
        if not drug_rows:
            genes_without_drugs.append(
                GeneWithoutDrugs(
                    ensembl_id=ensembl_id,
                    hgnc_symbol=hgnc_symbol,
                    association_score=gene_score,
                    source_url=target_source_url,
                )
            )
            continue

        for drug_row in drug_rows:
            drug = drug_row.get("drug") or {}
            chembl_id = drug.get("id")
            drug_name = drug.get("name")
            if not chembl_id or not drug_name:
                continue

            # Collapse salt/hydrate/ester child molecules onto their parent active
            # molecule so, e.g., FILGOTINIB and FILGOTINIB MALEATE don't occupy two
            # separate ranked slots. The parent carries the canonical identity; the
            # child's evidence (target link, clinical stage) is attributed to it.
            parent = drug.get("parentMolecule")
            if parent and parent.get("id"):
                chembl_id = parent["id"]
                drug_name = parent.get("name") or drug_name

            moa_rows = (drug.get("mechanismsOfAction") or {}).get("rows", [])
            confidence = _drug_target_confidence(moa_rows, ensembl_id)

            mechanism_of_action = None
            for moa in moa_rows:
                if ensembl_id in [t.get("id") for t in (moa.get("targets") or [])]:
                    mechanism_of_action = moa.get("mechanismOfAction")
                    break

            drug_type = drug.get("drugType")
            if not drug_type:
                drug_type = chembl_client.get_drug_type(chembl_id)
                if drug_type:
                    warnings.append(
                        PipelineWarning(
                            stage="chembl_fallback",
                            message=f"Drug type for {drug_name} filled in from ChEMBL (Open Targets data was thin).",
                        )
                    )

            raw_stage = drug_row.get("maxClinicalStage") or drug.get("maximumClinicalStage")
            max_phase = _map_clinical_stage(raw_stage)
            if max_phase == TrialPhase.UNKNOWN:
                chembl_phase = chembl_client.get_trial_phase(chembl_id)
                if chembl_phase:
                    max_phase = TrialPhase(chembl_phase)

            drug_source_url = f"{OPEN_TARGETS_UI_BASE}/drug/{chembl_id}"

            candidate = RankingInput(
                drug_chembl_id=chembl_id,
                drug_name=drug_name,
                disease_efo_id=resolved_disease.efo_id,
                disease_name=resolved_disease.name,
                target_ensembl_id=ensembl_id,
                target_hgnc_symbol=hgnc_symbol,
                gene_disease_score=gene_score,
                drug_target_score=confidence,
                max_clinical_phase=max_phase,
                drug_type=drug_type,
                mechanism_of_action=mechanism_of_action,
                source_links=[
                    SourceLink(source_name="Open Targets - Disease", url=disease_source_url),
                    SourceLink(source_name="Open Targets - Target", url=target_source_url),
                    SourceLink(source_name="Open Targets - Drug", url=drug_source_url),
                ],
            )

            # Provisional (biology-only) score is used for de-duplication and to
            # decide which candidates are worth the cost of literature enrichment.
            provisional = calculate_rank_score(candidate).final_score

            # A drug may be reachable via multiple genes; keep its best occurrence.
            if chembl_id not in best_candidate_score or provisional > best_candidate_score[chembl_id]:
                best_candidate_score[chembl_id] = provisional
                inputs_by_drug[chembl_id] = candidate

    emit(
        "fetching_drugs",
        "done",
        f"{len(inputs_by_drug)} candidate drugs found",
        candidates_found=len(inputs_by_drug),
        genes_without_drugs=len(genes_without_drugs),
    )

    # --- Phase 3 evidence enrichment (two-pass) ------------------------------
    # Enriching every candidate is too many API calls, so we enrich the top-N by
    # provisional biology score, then re-rank. Candidates outside the window keep
    # literature/safety at 0 (documented as "not assessed"), scoring exactly as
    # they did before Phase 3.
    to_enrich: list[RankingInput] = []
    if inputs_by_drug:
        to_enrich = sorted(
            inputs_by_drug.values(), key=lambda ri: best_candidate_score[ri.drug_chembl_id], reverse=True
        )[:MAX_EVIDENCE_ENRICHMENT]

    # Layer 1: PubMed literature (feeds the 20% literature component).
    if ENABLE_LITERATURE and to_enrich:
        emit("fetching_literature", "started",
             f"Searching PubMed for supporting studies (top {len(to_enrich)} candidates)", enriching=len(to_enrich))
        n = 0
        for ri in to_enrich:
            try:
                lit = score_literature(ri.drug_name, ri.disease_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Literature scoring failed for %s: %s", ri.drug_name, exc)
                continue
            ri.literature_score = lit.literature_strength
            ri.literature = LiteratureInfo(
                literature_strength=lit.literature_strength,
                total_papers=lit.total_papers,
                recent_papers=lit.recent_papers,
                top_pmids=lit.top_pmids,
            )
            n += 1
        emit("fetching_literature", "done", f"Literature assessed for {n} candidates", enriched=n)

    # Layer 2: OpenFDA safety (feeds the -5% safety penalty).
    if ENABLE_SAFETY and to_enrich:
        emit("checking_safety", "started", "Checking FDA safety data")
        flagged = 0
        for ri in to_enrich:
            try:
                safety = score_safety(ri.drug_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Safety scoring failed for %s: %s", ri.drug_name, exc)
                continue
            ri.safety_penalty = safety.safety_penalty
            ri.safety = safety
            if safety.has_boxed_warning:
                flagged += 1
        emit("checking_safety", "done", f"Safety checked ({flagged} with boxed warnings)", boxed_warnings=flagged)

    # Layer 3: ClinicalTrials.gov (enriches/verifies the trial signal; display + filter).
    if ENABLE_TRIALS and to_enrich:
        emit("checking_trials", "started", "Finding relevant clinical trials")
        with_trials = 0
        for ri in to_enrich:
            try:
                trials = get_trials(ri.drug_name, ri.disease_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Trials lookup failed for %s: %s", ri.drug_name, exc)
                continue
            ri.trials = trials
            if trials.trial_count > 0:
                with_trials += 1
        emit("checking_trials", "done", f"Trials found for {with_trials} candidates", with_trials=with_trials)

    emit("ranking", "started", f"Scoring {len(inputs_by_drug)} candidates")
    ranked_candidates = sorted(
        (calculate_rank_score(ri) for ri in inputs_by_drug.values()),
        key=lambda r: r.final_score,
        reverse=True,
    )
    emit("ranking", "done", f"Ranked {len(ranked_candidates)} candidates", ranked_count=len(ranked_candidates))

    # --- Display-only enrichment for the final top-N: paper list + LLM summary.
    # This never affects scores; it decorates the highest-ranked cards.
    if ENABLE_LITERATURE and ranked_candidates:
        top = [c for c in ranked_candidates[:DISPLAY_TOP_N] if c.literature and c.literature.top_pmids]
        if top:
            emit("summarizing_evidence", "started", "Summarizing key findings")
            for c in top:
                try:
                    c.literature.papers = [PubMedPaper(**p) for p in get_summaries(c.literature.top_pmids[:5])]
                    summ = summarize_evidence(c.drug_name, c.disease_name, c.literature.top_pmids[:6])
                    if summ is not None:
                        c.literature.summary = summ.summary
                        c.literature.summary_pmids = summ.pmids
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Display summary failed for %s: %s", c.drug_name, exc)
            emit("summarizing_evidence", "done", f"Summarized top {len(top)} candidates")

    return PipelineResult(
        disease_query=disease_name,
        disease_resolved=resolved_disease,
        gene_count=len(gene_rows),
        ranked_candidates=ranked_candidates,
        genes_without_drugs=genes_without_drugs,
        warnings=warnings,
    )
