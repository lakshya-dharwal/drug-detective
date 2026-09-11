"""Deterministic strategy adaptation: past experiences in, next strategy out.

This is the core of the self-improvement claim, so it is a pure function with no
LLM, no randomness and no network. Given the same experience history it always
produces the same next strategy, which is what makes the behaviour testable.

Design rule: between consecutive rounds EXACTLY ONE lever changes. Changing
several at once would make it impossible to attribute an improvement to
anything, and would read as noise rather than learning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from agent.experience import Experience

# --- Evidence signal vocabulary ---------------------------------------------
# Tags are machine-readable so the strategy engine can reason over them. Each
# maps to the evidence source that produced (or failed to produce) the signal.
SIGNAL_SOURCE: dict[str, str] = {
    "literature_strong": "literature",
    "literature_recent": "literature",
    "trials_corroborate": "trials",
    "trials_active": "trials",
    "safety_clean": "safety",
    "literature_thin": "literature",
    "literature_absent": "literature",
    "trials_absent": "trials",
    "safety_boxed_warning": "safety",
    "safety_no_data": "safety",
}

DEFAULT_EVIDENCE_PRIORITY = ["literature", "trials", "safety"]
DEFAULT_QUERY_FORMULATION = "drug_disease"
ALT_QUERY_FORMULATION = "mechanism_pathway"
DEFAULT_CANDIDATE_COUNT = 3

# Outcomes that count as "this line of investigation did not pay off".
UNPRODUCTIVE_OUTCOMES = {"weak", "inconclusive"}


@dataclass
class Strategy:
    """The levers the agent can pull for one investigation round."""

    round_number: int
    candidate_selection: str = "top_ranked"      # how candidates are picked
    candidate_count: int = DEFAULT_CANDIDATE_COUNT
    excluded_drugs: list[str] = field(default_factory=list)
    evidence_priority: list[str] = field(default_factory=lambda: list(DEFAULT_EVIDENCE_PRIORITY))
    query_formulation: str = DEFAULT_QUERY_FORMULATION
    changed_lever: Optional[str] = None          # which single lever moved vs last round
    rationale: str = ""                          # why it moved

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "candidate_selection": self.candidate_selection,
            "candidate_count": self.candidate_count,
            "excluded_drugs": list(self.excluded_drugs),
            "evidence_priority": list(self.evidence_priority),
            "query_formulation": self.query_formulation,
            "changed_lever": self.changed_lever,
            "rationale": self.rationale,
        }


@dataclass
class Learning:
    """The human-readable half of adaptation, for the UI and the demo."""

    what_i_learned: str
    what_i_am_changing: str

    def to_dict(self) -> dict[str, str]:
        return {
            "what_i_learned": self.what_i_learned,
            "what_i_am_changing": self.what_i_am_changing,
        }


def default_strategy(round_number: int = 1) -> Strategy:
    """Round 1 has no history to learn from, so it starts from the ranked list."""
    return Strategy(
        round_number=round_number,
        candidate_selection="top_ranked",
        rationale="No prior experience for this disease — starting from the top-ranked candidates.",
    )


def _tally_sources(experiences: list[Experience]) -> tuple[dict[str, int], dict[str, int]]:
    """Count, per evidence source, how often it produced signal vs came up empty."""
    worked: dict[str, int] = {src: 0 for src in DEFAULT_EVIDENCE_PRIORITY}
    failed: dict[str, int] = {src: 0 for src in DEFAULT_EVIDENCE_PRIORITY}
    for exp in experiences:
        for tag in exp.what_worked:
            src = SIGNAL_SOURCE.get(tag)
            if src:
                worked[src] = worked.get(src, 0) + 1
        for tag in exp.what_failed:
            src = SIGNAL_SOURCE.get(tag)
            if src:
                failed[src] = failed.get(src, 0) + 1
    return worked, failed


def next_strategy(
    previous: list[Experience], previous_strategy: Optional[Strategy] = None
) -> tuple[Strategy, Learning]:
    """Read the last round's experiences and move exactly one lever.

    Lever selection is a fixed priority ladder, evaluated against the dominant
    failure mode of the previous round:

      1. Any candidate was unproductive -> change WHICH candidates to look at.
      2. One evidence source kept coming up empty -> change source PRIORITY.
      3. Everything was merely thin -> change the QUERY FORMULATION.
    """
    if not previous:
        return default_strategy(1), Learning(
            what_i_learned="No previous investigation on record for this disease.",
            what_i_am_changing="Running a first pass over the top-ranked candidates to establish a baseline.",
        )

    last_round = max(exp.round_number for exp in previous)
    last = [exp for exp in previous if exp.round_number == last_round]
    base = previous_strategy or default_strategy(last_round)

    # Carry every lever forward unchanged; only one is overwritten below.
    nxt = Strategy(
        round_number=last_round + 1,
        candidate_selection=base.candidate_selection,
        candidate_count=base.candidate_count,
        excluded_drugs=list(base.excluded_drugs),
        evidence_priority=list(base.evidence_priority),
        query_formulation=base.query_formulation,
    )

    unproductive = [exp for exp in last if exp.outcome in UNPRODUCTIVE_OUTCOMES]
    mean_conf = sum(exp.confidence for exp in last) / len(last)
    worked, failed = _tally_sources(last)

    # --- Lever 1: candidate selection ---------------------------------------
    # Any dead end is worth abandoning: re-investigating a candidate that already
    # returned nothing spends a round to re-learn what memory already records.
    if unproductive:
        names = [exp.candidate_drug for exp in unproductive]
        nxt.candidate_selection = "skip_unproductive"
        nxt.excluded_drugs = sorted(set(nxt.excluded_drugs) | set(names))
        nxt.changed_lever = "candidate_selection"
        listed = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
        nxt.rationale = (
            f"{len(unproductive)} of {len(last)} candidates in round {last_round} "
            f"returned weak or inconclusive evidence."
        )
        return nxt, Learning(
            what_i_learned=(
                f"In round {last_round} I investigated {len(last)} candidates and "
                f"{len(unproductive)} of them ({listed}) produced weak or inconclusive "
                f"supporting evidence (mean confidence {mean_conf:.2f})."
            ),
            what_i_am_changing=(
                f"Round {nxt.round_number} will deprioritize {listed} and investigate the "
                f"next-ranked candidates instead. Evidence sources and query formulation stay fixed "
                f"so any change in confidence is attributable to the candidate switch."
            ),
        )

    # --- Lever 2: evidence priority -----------------------------------------
    # The source that failed most, if it actually failed for most candidates.
    worst_src, worst_n = max(failed.items(), key=lambda kv: (kv[1], kv[0]))
    if worst_n * 2 >= len(last) and worst_n > 0:
        best_src, _ = max(worked.items(), key=lambda kv: (kv[1], kv[0]))
        order = [s for s in nxt.evidence_priority if s != worst_src] + [worst_src]
        if best_src != worst_src and best_src in order:
            order.remove(best_src)
            order.insert(0, best_src)
        nxt.evidence_priority = order
        nxt.changed_lever = "evidence_priority"
        nxt.rationale = (
            f"'{worst_src}' produced no usable signal for {worst_n} of {len(last)} "
            f"candidates in round {last_round}."
        )
        return nxt, Learning(
            what_i_learned=(
                f"In round {last_round} the '{worst_src}' evidence source came up empty for "
                f"{worst_n} of {len(last)} candidates, while '{best_src}' carried the signal."
            ),
            what_i_am_changing=(
                f"Round {nxt.round_number} will lead with '{best_src}' and demote '{worst_src}' "
                f"to last in the evidence order ({' > '.join(order)}). The candidate set is "
                f"unchanged so the effect of the reordering is isolated."
            ),
        )

    # --- Lever 3: query formulation -----------------------------------------
    nxt.query_formulation = (
        ALT_QUERY_FORMULATION
        if base.query_formulation == DEFAULT_QUERY_FORMULATION
        else DEFAULT_QUERY_FORMULATION
    )
    nxt.changed_lever = "query_formulation"
    nxt.rationale = (
        f"Round {last_round} candidates were productive (mean confidence {mean_conf:.2f}) "
        f"but the evidence was thin; broadening how the hypothesis is framed."
    )
    return nxt, Learning(
        what_i_learned=(
            f"Round {last_round} candidates held up (mean confidence {mean_conf:.2f}) and no single "
            f"evidence source failed outright, so the limiting factor is how narrowly I framed the question."
        ),
        what_i_am_changing=(
            f"Round {nxt.round_number} will reframe the hypothesis from '{base.query_formulation}' to "
            f"'{nxt.query_formulation}' — investigating the shared mechanism/pathway rather than the "
            f"drug–disease pair directly. Candidates and evidence order stay fixed."
        ),
    )


def strategy_diff(before: Strategy, after: Strategy) -> dict[str, Any]:
    """Field-level diff between two strategies, for the UI's before/after panel."""
    changes: dict[str, dict[str, Any]] = {}
    b, a = before.to_dict(), after.to_dict()
    for key in ("candidate_selection", "candidate_count", "excluded_drugs", "evidence_priority", "query_formulation"):
        if b[key] != a[key]:
            changes[key] = {"before": b[key], "after": a[key]}
    return {
        "changed_lever": after.changed_lever,
        "rationale": after.rationale,
        "changes": changes,
    }
