import pytest

from src.models import RankingInput, SafetyInfo, TrialPhase
from src.ranking_engine import ACTIVE_WEIGHTS, SAFETY_PENALTY_MAX, TRIAL_PHASE_SCORES, calculate_rank_score


def make_candidate(**overrides) -> RankingInput:
    defaults = dict(
        drug_chembl_id="CHEMBL1",
        drug_name="Test Drug",
        disease_efo_id="EFO_0000001",
        disease_name="test disease",
        target_ensembl_id="ENSG00000000001",
        target_hgnc_symbol="TESTGENE",
        gene_disease_score=0.8,
        drug_target_score=0.6,
        max_clinical_phase=TrialPhase.PHASE_3,
    )
    defaults.update(overrides)
    return RankingInput(**defaults)


def test_active_weights_are_the_restored_real_weights():
    # Phase 3: literature is real, so the redistribution hack is gone and the
    # intended weights are applied directly. Per spec these positive weights sum
    # to 95 (35+30+20+10); safety is a separate penalty of up to -5.
    assert ACTIVE_WEIGHTS["gene_disease_evidence"] == 35.0
    assert ACTIVE_WEIGHTS["drug_target_evidence"] == 30.0
    assert ACTIVE_WEIGHTS["literature_strength"] == 20.0
    assert ACTIVE_WEIGHTS["clinical_trial_stage"] == 10.0
    assert sum(ACTIVE_WEIGHTS.values()) == pytest.approx(95.0)
    assert SAFETY_PENALTY_MAX == 5.0


def test_weighted_math_matches_manual_calculation():
    candidate = make_candidate(
        gene_disease_score=0.8, drug_target_score=0.6, literature_score=0.5, max_clinical_phase=TrialPhase.PHASE_3
    )
    result = calculate_rank_score(candidate)

    expected = (
        0.8 * ACTIVE_WEIGHTS["gene_disease_evidence"]
        + 0.6 * ACTIVE_WEIGHTS["drug_target_evidence"]
        + 0.5 * ACTIVE_WEIGHTS["literature_strength"]
        + TRIAL_PHASE_SCORES[TrialPhase.PHASE_3] * ACTIVE_WEIGHTS["clinical_trial_stage"]
    )
    assert result.final_score == pytest.approx(round(expected, 2), abs=0.01)


def test_literature_score_contributes_when_real():
    low = calculate_rank_score(make_candidate(literature_score=0.0))
    high = calculate_rank_score(make_candidate(literature_score=1.0))
    # A full literature score adds its full 20-point weight.
    assert high.final_score - low.final_score == pytest.approx(20.0, abs=0.01)
    assert high.component_scores["literature_strength"].weighted_contribution == pytest.approx(20.0, abs=0.01)


def test_boxed_warning_safety_penalty_reduces_score():
    no_safety = calculate_rank_score(make_candidate())
    with_warning = calculate_rank_score(
        make_candidate(
            safety_penalty=1.0,
            safety=SafetyInfo(safety_penalty=1.0, has_boxed_warning=True, data_available=True),
        )
    )
    # Full severity subtracts the full -5 point budget.
    assert no_safety.final_score - with_warning.final_score == pytest.approx(SAFETY_PENALTY_MAX, abs=0.01)
    assert with_warning.component_scores["safety_penalty"].weighted_contribution == pytest.approx(-5.0, abs=0.01)


def test_safety_penalty_zero_when_no_data():
    result = calculate_rank_score(make_candidate())
    penalty = result.component_scores["safety_penalty"]
    assert penalty.raw_score == 0.0
    assert penalty.weighted_contribution == 0.0
    assert penalty.note is not None and "No FDA safety data" in penalty.note


def test_approved_drug_scores_higher_than_preclinical_all_else_equal():
    approved = calculate_rank_score(make_candidate(max_clinical_phase=TrialPhase.APPROVED))
    preclinical = calculate_rank_score(make_candidate(max_clinical_phase=TrialPhase.PRECLINICAL))
    assert approved.final_score > preclinical.final_score


def test_final_score_bounded_0_to_100():
    best = calculate_rank_score(
        make_candidate(gene_disease_score=1.0, drug_target_score=1.0, max_clinical_phase=TrialPhase.APPROVED)
    )
    worst = calculate_rank_score(
        make_candidate(gene_disease_score=0.0, drug_target_score=0.0, max_clinical_phase=TrialPhase.UNKNOWN)
    )
    assert 0.0 <= worst.final_score <= 100.0
    assert 0.0 <= best.final_score <= 100.0
    assert best.final_score > worst.final_score


def test_explanation_mentions_key_factors():
    result = calculate_rank_score(
        make_candidate(gene_disease_score=0.82, max_clinical_phase=TrialPhase.PHASE_3)
    )
    assert "0.82" in result.explanation
    assert "Phase 3" in result.explanation


def test_explanation_incorporates_real_literature_and_safety():
    from src.models import LiteratureInfo, SafetyInfo

    result = calculate_rank_score(
        make_candidate(
            literature_score=0.7,
            literature=LiteratureInfo(literature_strength=0.7, total_papers=14, recent_papers=9),
            safety=SafetyInfo(safety_penalty=1.0, has_boxed_warning=True, data_available=True),
        )
    )
    assert "14 supporting publication" in result.explanation
    assert "boxed warning" in result.explanation.lower()
