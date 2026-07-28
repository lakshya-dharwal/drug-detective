"""Pydantic data models shared across the Phase 1 pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Canonical entities
# --------------------------------------------------------------------------


class ResolvedGene(BaseModel):
    """A gene resolved to its canonical Ensembl ID."""

    ensembl_id: str
    hgnc_symbol: str
    synonyms: list[str] = Field(default_factory=list)


class ResolvedDrug(BaseModel):
    """A drug resolved to its canonical ChEMBL ID."""

    chembl_id: str
    drugbank_id: Optional[str] = None
    canonical_name: str
    synonyms: list[str] = Field(default_factory=list)


class ResolvedDisease(BaseModel):
    """A disease resolved to its canonical EFO/MONDO ID via Open Targets search."""

    efo_id: str
    name: str


# --------------------------------------------------------------------------
# Clinical trial phase
# --------------------------------------------------------------------------


class TrialPhase(str, Enum):
    APPROVED = "approved"
    PHASE_3 = "phase3"
    PHASE_2 = "phase2"
    PHASE_1 = "phase1"
    PRECLINICAL = "preclinical"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------
# Raw evidence records (as pulled from the data sources)
# --------------------------------------------------------------------------


class GeneAssociation(BaseModel):
    """A disease -> gene association from Open Targets."""

    ensembl_id: str
    hgnc_symbol: str
    association_score: float = Field(ge=0.0, le=1.0)
    source_url: str


class DrugTargetEvidence(BaseModel):
    """A gene -> drug association from Open Targets, with drug metadata."""

    chembl_id: str
    drug_name: str
    target_ensembl_id: str
    target_hgnc_symbol: str
    max_clinical_phase: TrialPhase
    mechanism_of_action: Optional[str] = None
    drug_type: Optional[str] = None
    is_approved: bool = False
    drug_target_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Our own specificity-derived confidence that this drug meaningfully "
            "targets this gene. Open Targets does not expose a raw numeric "
            "target-drug score, so this is computed as 1 / (number of distinct "
            "targets sharing the drug's mechanism of action entry that names "
            "this gene), falling back to 0.5 if the drug was reached only "
            "through the target's candidate list without an explicit MoA match."
        ),
    )
    source_url: str


# --------------------------------------------------------------------------
# Ranking output
# --------------------------------------------------------------------------


class ComponentScore(BaseModel):
    """A single weighted component of the final rank score."""

    raw_score: float = Field(description="Unweighted, normalized 0-1 input value")
    weight_pct: float = Field(description="Effective weight applied, as a percentage of 100")
    weighted_contribution: float = Field(description="raw_score * (weight_pct / 100), in points")
    note: Optional[str] = None


class SourceLink(BaseModel):
    source_name: str
    url: str


# --------------------------------------------------------------------------
# Phase 3 evidence layers (attached to results for display; scores are the
# deterministic numbers used by the ranking engine).
# --------------------------------------------------------------------------


class PubMedPaper(BaseModel):
    pmid: str
    title: str
    journal: str = ""
    year: str = ""
    url: str


class LiteratureInfo(BaseModel):
    """PubMed literature evidence for one drug-disease pair (Layer 1)."""

    literature_strength: float = Field(ge=0.0, le=1.0, description="Deterministic 0-1 score feeding ranking")
    total_papers: int = 0
    recent_papers: int = 0
    top_pmids: list[str] = Field(default_factory=list)
    papers: list[PubMedPaper] = Field(default_factory=list)
    # Display-only LLM narration (Phase 3 step 2). Never affects scores.
    summary: Optional[str] = None
    summary_pmids: list[str] = Field(default_factory=list)


class SafetyFlag(BaseModel):
    kind: str  # e.g. "boxed_warning", "contraindication"
    label: str  # human-readable
    source_url: str


class SafetyInfo(BaseModel):
    """OpenFDA safety evidence for one drug (Layer 2)."""

    safety_penalty: float = Field(ge=0.0, le=1.0, description="Deterministic 0-1 severity; scaled to the -5% budget")
    has_boxed_warning: bool = False
    flags: list[SafetyFlag] = Field(default_factory=list)
    data_available: bool = False  # False = no FDA data (neutral, not penalized)


class ClinicalTrial(BaseModel):
    nct_id: str
    title: str = ""
    phase: str = ""
    status: str = ""
    url: str


class TrialsInfo(BaseModel):
    """ClinicalTrials.gov evidence for one drug-disease pair (Layer 3)."""

    trial_count: int = 0
    active_count: int = 0
    completed_count: int = 0
    trials: list[ClinicalTrial] = Field(default_factory=list)


class RankResult(BaseModel):
    """Final scored & explained repurposing candidate for one drug/disease pair."""

    drug_chembl_id: str
    drug_name: str
    disease_efo_id: str
    disease_name: str
    target_ensembl_id: str
    target_hgnc_symbol: str

    final_score: float = Field(ge=0.0, le=100.0)
    component_scores: dict[str, ComponentScore]
    explanation: str
    source_links: list[SourceLink]

    max_clinical_phase: TrialPhase
    drug_type: Optional[str] = None
    mechanism_of_action: Optional[str] = None

    # Phase 3 evidence (populated for enriched candidates; None/empty otherwise).
    literature: Optional[LiteratureInfo] = None
    safety: Optional[SafetyInfo] = None
    trials: Optional[TrialsInfo] = None


class RankingInput(BaseModel):
    """Raw inputs handed to `ranking_engine.calculate_rank_score`.

    Kept separate from GeneAssociation/DrugTargetEvidence so the ranking engine
    stays a pure function over plain, already-normalized values with no
    knowledge of where they came from.
    """

    drug_chembl_id: str
    drug_name: str
    disease_efo_id: str
    disease_name: str
    target_ensembl_id: str
    target_hgnc_symbol: str

    gene_disease_score: float = Field(ge=0.0, le=1.0)
    drug_target_score: float = Field(ge=0.0, le=1.0)
    max_clinical_phase: TrialPhase
    drug_type: Optional[str] = None
    mechanism_of_action: Optional[str] = None

    # Phase 3 real evidence signals (0-1). Default 0 = "not assessed / no signal",
    # so an un-enriched candidate scores exactly as it did pre-Phase-3.
    literature_score: float = Field(default=0.0, ge=0.0, le=1.0)
    safety_penalty: float = Field(default=0.0, ge=0.0, le=1.0)

    # Display evidence carried through to the RankResult (not used in scoring).
    literature: Optional[LiteratureInfo] = None
    safety: Optional[SafetyInfo] = None
    trials: Optional[TrialsInfo] = None

    source_links: list[SourceLink] = Field(default_factory=list)


class GeneWithoutDrugs(BaseModel):
    """A disease-associated gene that has no known drugs, surfaced separately."""

    ensembl_id: str
    hgnc_symbol: str
    association_score: float
    source_url: str


class PipelineWarning(BaseModel):
    stage: str
    message: str


class PipelineResult(BaseModel):
    """Top-level output of running the pipeline for one disease."""

    disease_query: str
    disease_resolved: Optional[ResolvedDisease] = None
    status_message: Optional[str] = None

    gene_count: int = 0
    ranked_candidates: list[RankResult] = Field(default_factory=list)
    genes_without_drugs: list[GeneWithoutDrugs] = Field(default_factory=list)
    warnings: list[PipelineWarning] = Field(default_factory=list)

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
