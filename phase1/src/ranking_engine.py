"""Deterministic, explainable ranking of drug repurposing candidates.

No AI/LLM involvement — this is pure weighted-sum arithmetic over normalized
evidence scores. See `calculate_rank_score` for the entry point.
"""

from __future__ import annotations

from src.models import ComponentScore, RankingInput, RankResult, TrialPhase

# --------------------------------------------------------------------------
# Tunable weights (points out of 100). As of Phase 3 all four positive
# components are backed by real data, so the intended weights are applied
# directly — the Phase 1 literature-redistribution hack has been removed.
#   gene_disease_evidence 35 + drug_target_evidence 30 + literature_strength 20
#   + clinical_trial_stage 10  = 100 positive points; safety subtracts up to 5.
# --------------------------------------------------------------------------

ACTIVE_WEIGHTS = {
    "gene_disease_evidence": 35.0,
    "drug_target_evidence": 30.0,
    "literature_strength": 20.0,   # Phase 3: REAL (PubMed via literature_scorer)
    "clinical_trial_stage": 10.0,
}
SAFETY_PENALTY_MAX = 5.0  # Phase 3: REAL (OpenFDA via safety_scorer). Max points deducted.

# Clinical trial phase -> normalized 0-1 score.
TRIAL_PHASE_SCORES: dict[TrialPhase, float] = {
    TrialPhase.APPROVED: 1.0,
    TrialPhase.PHASE_3: 0.75,
    TrialPhase.PHASE_2: 0.5,
    TrialPhase.PHASE_1: 0.25,
    TrialPhase.PRECLINICAL: 0.1,
    TrialPhase.UNKNOWN: 0.0,
}


def calculate_rank_score(candidate: RankingInput) -> RankResult:
    """Pure function: normalized evidence in, fully explained RankResult out."""

    trial_score = TRIAL_PHASE_SCORES.get(candidate.max_clinical_phase, 0.0)
    literature_score = candidate.literature_score   # Phase 3: real 0-1 from PubMed.
    safety_penalty_raw = candidate.safety_penalty   # Phase 3: real 0-1 severity from OpenFDA.

    raw_scores = {
        "gene_disease_evidence": candidate.gene_disease_score,
        "drug_target_evidence": candidate.drug_target_score,
        "literature_strength": literature_score,
        "clinical_trial_stage": trial_score,
    }

    component_scores: dict[str, ComponentScore] = {}
    final_score = 0.0

    for key, raw in raw_scores.items():
        weight_pct = ACTIVE_WEIGHTS[key]
        contribution = raw * weight_pct  # raw in 0-1, weight in points-per-100
        final_score += contribution
        note = None
        if key == "literature_strength" and candidate.literature is None:
            note = "No literature enrichment for this candidate (outside the top-N evidence window)."
        component_scores[key] = ComponentScore(
            raw_score=raw,
            weight_pct=weight_pct,
            weighted_contribution=contribution,
            note=note,
        )

    safety_contribution = -safety_penalty_raw * SAFETY_PENALTY_MAX
    final_score += safety_contribution
    safety_note = None
    if candidate.safety is None or not candidate.safety.data_available:
        safety_note = "No FDA safety data available (neutral — not penalized)."
    component_scores["safety_penalty"] = ComponentScore(
        raw_score=safety_penalty_raw,
        weight_pct=-SAFETY_PENALTY_MAX,
        weighted_contribution=safety_contribution,
        note=safety_note,
    )

    final_score = max(0.0, min(100.0, final_score))

    explanation = _build_explanation(candidate, raw_scores, trial_score)

    return RankResult(
        drug_chembl_id=candidate.drug_chembl_id,
        drug_name=candidate.drug_name,
        disease_efo_id=candidate.disease_efo_id,
        disease_name=candidate.disease_name,
        target_ensembl_id=candidate.target_ensembl_id,
        target_hgnc_symbol=candidate.target_hgnc_symbol,
        final_score=round(final_score, 2),
        component_scores=component_scores,
        explanation=explanation,
        source_links=candidate.source_links,
        max_clinical_phase=candidate.max_clinical_phase,
        drug_type=candidate.drug_type,
        mechanism_of_action=candidate.mechanism_of_action,
        literature=candidate.literature,
        safety=candidate.safety,
        trials=candidate.trials,
    )


def _build_explanation(candidate: RankingInput, raw_scores: dict[str, float], trial_score: float) -> str:
    parts: list[str] = []

    gd = raw_scores["gene_disease_evidence"]
    if gd >= 0.7:
        parts.append(f"strong gene-disease association ({gd:.2f})")
    elif gd >= 0.4:
        parts.append(f"moderate gene-disease association ({gd:.2f})")
    else:
        parts.append(f"weak gene-disease association ({gd:.2f})")

    dt = raw_scores["drug_target_evidence"]
    parts.append(f"target-binding confidence of {dt:.2f} for {candidate.target_hgnc_symbol}")

    phase_labels = {
        TrialPhase.APPROVED: "an approved drug",
        TrialPhase.PHASE_3: "Phase 3 trial status",
        TrialPhase.PHASE_2: "Phase 2 trial status",
        TrialPhase.PHASE_1: "Phase 1 trial status",
        TrialPhase.PRECLINICAL: "only preclinical trial status",
        TrialPhase.UNKNOWN: "unknown trial status",
    }
    parts.append(phase_labels.get(candidate.max_clinical_phase, "unknown trial status"))

    # Literature (real, Phase 3).
    if candidate.literature is not None:
        lit = candidate.literature
        if lit.total_papers > 0:
            recent_clause = f" ({lit.recent_papers} since the last 5 years)" if lit.recent_papers else ""
            parts.append(f"{lit.total_papers} supporting publication(s){recent_clause}")
        else:
            parts.append("no direct literature found")

    # Trials (real, Phase 3).
    if candidate.trials is not None and candidate.trials.trial_count > 0:
        parts.append(f"{candidate.trials.trial_count} relevant clinical trial(s)")

    body = "Ranked based on " + ", ".join(parts) + "."

    # Safety (real, Phase 3).
    if candidate.safety is not None and candidate.safety.data_available:
        if candidate.safety.has_boxed_warning:
            body += " Carries an FDA boxed warning (safety penalty applied)."
        elif candidate.safety.flags:
            body += " Has FDA safety flags (minor penalty applied)."
        else:
            body += " No major FDA safety warnings."
    return body
