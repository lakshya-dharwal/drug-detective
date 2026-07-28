"""Deterministic literature_strength scoring (0-1) from PubMed metadata.

This score feeds the ranking engine's 20% literature component. It is computed
ENTIRELY from retrieved publication counts — never from an LLM. The LLM summary
(llm_summarizer, Phase 3 step 2) is display-only and does not influence this.

Formula (all constants configurable at the top):

    paper_count_score = min(total_papers / PAPER_COUNT_SATURATION, 1.0)
    recency_score     = min(recent_papers / RECENT_COUNT_SATURATION, 1.0)
    literature_strength = ( PAPER_COUNT_WEIGHT * paper_count_score
                          + RECENCY_WEIGHT     * recency_score )

`recent_papers` = publications within the last N years (see pubmed_client.
RECENCY_WINDOW_YEARS). The two sub-weights sum to 1.0.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.pubmed_client import get_publication_counts

# --- Tunable constants -------------------------------------------------------
# Counts at/above the saturation point map to a full 1.0 for that sub-score.
PAPER_COUNT_SATURATION = 20.0   # ~20 papers on a pair is already strong signal
RECENT_COUNT_SATURATION = 10.0  # ~10 recent papers saturates recency

PAPER_COUNT_WEIGHT = 0.6
RECENCY_WEIGHT = 0.4


@dataclass
class LiteratureEvidence:
    """Deterministic literature signal for one drug-disease pair."""

    literature_strength: float  # 0-1, feeds ranking
    total_papers: int
    recent_papers: int
    top_pmids: list[str]
    paper_count_score: float
    recency_score: float

    def to_dict(self) -> dict:
        return {
            "literature_strength": round(self.literature_strength, 4),
            "total_papers": self.total_papers,
            "recent_papers": self.recent_papers,
            "top_pmids": self.top_pmids,
            "paper_count_score": round(self.paper_count_score, 4),
            "recency_score": round(self.recency_score, 4),
        }


def score_literature(drug_name: str, disease_name: str) -> LiteratureEvidence:
    """Compute the deterministic literature evidence for a drug-disease pair."""
    counts = get_publication_counts(drug_name, disease_name)
    total = int(counts.get("total", 0))
    recent = int(counts.get("recent", 0))
    top_pmids = counts.get("top_pmids", []) or []

    paper_count_score = min(total / PAPER_COUNT_SATURATION, 1.0)
    recency_score = min(recent / RECENT_COUNT_SATURATION, 1.0)
    strength = PAPER_COUNT_WEIGHT * paper_count_score + RECENCY_WEIGHT * recency_score

    return LiteratureEvidence(
        literature_strength=strength,
        total_papers=total,
        recent_papers=recent,
        top_pmids=top_pmids,
        paper_count_score=paper_count_score,
        recency_score=recency_score,
    )
