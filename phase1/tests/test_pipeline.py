"""Integration tests that hit the real Open Targets / ChEMBL APIs end-to-end.

These are slower and require network access. Kept small (MAX_GENES_TO_QUERY
patched down) to bound runtime while still exercising the full pipeline path.
"""

import pytest

from src import pipeline
from src.models import PipelineResult


@pytest.fixture(autouse=True)
def small_gene_limit(monkeypatch):
    # Keep the real-API integration tests fast: only pull drugs for a few genes.
    monkeypatch.setattr(pipeline, "MAX_GENES_TO_QUERY", 5)


@pytest.mark.integration
@pytest.mark.parametrize("disease_name", ["glioblastoma", "pulmonary hypertension"])
def test_pipeline_runs_end_to_end_without_crashing(disease_name):
    result = pipeline.run_pipeline(disease_name)

    assert isinstance(result, PipelineResult)
    assert result.disease_resolved is not None
    assert result.gene_count > 0

    # Every ranked candidate must be internally consistent.
    for candidate in result.ranked_candidates:
        assert 0.0 <= candidate.final_score <= 100.0
        assert candidate.source_links
        assert candidate.explanation

    # Scores should be sorted descending.
    scores = [c.final_score for c in result.ranked_candidates]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.integration
def test_pipeline_handles_unresolvable_disease_gracefully():
    result = pipeline.run_pipeline("zzzznotarealdiseasexyz123")

    assert result.disease_resolved is None
    assert result.ranked_candidates == []
    assert result.status_message is not None
