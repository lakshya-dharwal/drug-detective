"""One investigation round over an already-completed Drug Detective search.

Scope note: this layer NEVER recomputes or influences the deterministic ranking
score. It reads the ranked candidates Phase 1 already produced and forms a
separate `investigation_confidence` from the structured evidence attached to
them. Ranking answers "how strong is this candidate?"; investigation answers
"did this line of enquiry pay off, and what should I try next?".

No external evidence is fabricated here. Every number traces back to a field the
existing pipeline populated (PubMed counts, ClinicalTrials.gov counts, openFDA
flags). Sponsor-backed live retrieval slots in later behind the same interface.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from agent import one_client, sandbox as daytona_sandbox, youcom
from agent.crew import narrate_round
from agent.experience import Experience, load_experiences, record_experiences
from agent.strategy import (
    Learning,
    Strategy,
    default_strategy,
    next_strategy,
    strategy_diff,
)

logger = logging.getLogger(__name__)

# Weight applied to an evidence source by its position in `evidence_priority`.
# Reordering the priority list genuinely changes the confidence arithmetic —
# that is what makes the round-2 "evidence_priority" lever a real change.
POSITION_WEIGHTS = [0.5, 0.3, 0.2]

PROMISING_THRESHOLD = 0.60
WEAK_THRESHOLD = 0.40


# --------------------------------------------------------------------------
# Candidate selection
# --------------------------------------------------------------------------
def select_candidates(ranked: list[dict[str, Any]], strategy: Strategy) -> list[dict[str, Any]]:
    """Pick this round's candidates, honouring the strategy's exclusions.

    The ranked list can contain the same drug several times (once per target it
    hits), so we de-duplicate by drug name and keep the highest-ranked entry.
    """
    excluded = {name.upper() for name in strategy.excluded_drugs}
    seen: set[str] = set()
    picked: list[dict[str, Any]] = []
    for cand in ranked:
        name = str(cand.get("drug_name", "")).strip()
        key = name.upper()
        if not name or key in seen:
            continue
        seen.add(key)
        if key in excluded:
            continue
        picked.append(cand)
        if len(picked) >= strategy.candidate_count:
            break
    return picked


# --------------------------------------------------------------------------
# Evidence scoring (per source, 0-1)
# --------------------------------------------------------------------------
def _literature_signal(
    cand: dict[str, Any], ranked: list[dict[str, Any]], formulation: str
) -> tuple[float, list[str], list[str], dict[str, Any]]:
    lit = cand.get("literature") or {}
    total = int(lit.get("total_papers") or 0)
    recent = int(lit.get("recent_papers") or 0)
    strength = float(lit.get("literature_strength") or 0.0)
    worked: list[str] = []
    failed: list[str] = []

    if formulation == "mechanism_pathway":
        # Reframed hypothesis: credit corroboration across every candidate that
        # shares this target, instead of only this drug-disease pair's own papers.
        target = cand.get("target_hgnc_symbol")
        siblings = [
            c for c in ranked
            if c.get("target_hgnc_symbol") == target
            and c.get("drug_name") != cand.get("drug_name")
        ]
        sib_papers = sum(int((c.get("literature") or {}).get("total_papers") or 0) for c in siblings)
        corroboration = min(len(siblings) / 5.0, 1.0)
        score = min(0.6 * strength + 0.4 * corroboration, 1.0)
        detail = {
            "mode": "mechanism_pathway",
            "target": target,
            "sibling_candidates": len(siblings),
            "sibling_papers": sib_papers,
            "own_papers": total,
        }
        if len(siblings) >= 2:
            worked.append("literature_strong")
        else:
            failed.append("literature_thin")
    else:
        recency = (recent / total) if total else 0.0
        score = min(0.7 * strength + 0.3 * recency, 1.0)
        detail = {
            "mode": "drug_disease",
            "total_papers": total,
            "recent_papers": recent,
            "literature_strength": round(strength, 3),
        }
        if total == 0:
            failed.append("literature_absent")
        elif total < 5:
            failed.append("literature_thin")
        else:
            worked.append("literature_strong")
        if recent >= 3:
            worked.append("literature_recent")

    return score, worked, failed, detail


def _trials_signal(cand: dict[str, Any]) -> tuple[float, list[str], list[str], dict[str, Any]]:
    trials = cand.get("trials") or {}
    count = int(trials.get("trial_count") or 0)
    active = int(trials.get("active_count") or 0)
    worked: list[str] = []
    failed: list[str] = []

    score = min(count / 5.0, 1.0) * 0.7 + min(active / 2.0, 1.0) * 0.3
    if count == 0:
        failed.append("trials_absent")
    elif count >= 3:
        worked.append("trials_corroborate")
    if active >= 1:
        worked.append("trials_active")

    return min(score, 1.0), worked, failed, {
        "trial_count": count,
        "active_count": active,
        "completed_count": int(trials.get("completed_count") or 0),
    }


def _safety_signal(cand: dict[str, Any]) -> tuple[float, list[str], list[str], dict[str, Any]]:
    safety = cand.get("safety") or {}
    available = bool(safety.get("data_available"))
    boxed = bool(safety.get("has_boxed_warning"))
    worked: list[str] = []
    failed: list[str] = []

    if not available:
        score = 0.5  # absent FDA data is neutral, never a penalty
        failed.append("safety_no_data")
    elif boxed:
        score = 0.4
        failed.append("safety_boxed_warning")
    else:
        score = 1.0
        worked.append("safety_clean")

    return score, worked, failed, {
        "data_available": available,
        "has_boxed_warning": boxed,
        "flag_count": len(safety.get("flags") or []),
    }


# --------------------------------------------------------------------------
# Per-candidate investigation
# --------------------------------------------------------------------------
def investigate_candidate(
    cand: dict[str, Any], ranked: list[dict[str, Any]], strategy: Strategy
) -> dict[str, Any]:
    """Form an investigation verdict for one candidate under `strategy`.

    Deterministic: same candidate + same strategy always yields the same verdict.
    """
    signals = {
        "literature": _literature_signal(cand, ranked, strategy.query_formulation),
        "trials": _trials_signal(cand),
        "safety": _safety_signal(cand),
    }

    confidence = 0.0
    worked: list[str] = []
    failed: list[str] = []
    breakdown: dict[str, Any] = {}

    for position, source in enumerate(strategy.evidence_priority):
        weight = POSITION_WEIGHTS[position] if position < len(POSITION_WEIGHTS) else 0.0
        score, src_worked, src_failed, detail = signals[source]
        confidence += score * weight
        worked.extend(src_worked)
        failed.extend(src_failed)
        breakdown[source] = {
            "score": round(score, 3),
            "weight": weight,
            "contribution": round(score * weight, 3),
            "detail": detail,
        }

    confidence = round(min(confidence, 1.0), 3)
    if confidence >= PROMISING_THRESHOLD:
        outcome = "promising"
    elif confidence < WEAK_THRESHOLD:
        outcome = "weak"
    else:
        outcome = "inconclusive"

    return {
        "drug_name": cand.get("drug_name"),
        "drug_chembl_id": cand.get("drug_chembl_id"),
        "target": cand.get("target_hgnc_symbol"),
        "rank_score": cand.get("final_score"),
        "max_clinical_phase": cand.get("max_clinical_phase"),
        "investigation_confidence": confidence,
        "outcome": outcome,
        "what_worked": worked,
        "what_failed": failed,
        "evidence_breakdown": breakdown,
    }


# --------------------------------------------------------------------------
# Round orchestration
# --------------------------------------------------------------------------
def run_round(
    search_result: dict[str, Any],
    disease: str,
    round_number: int,
    strategy: Optional[Strategy] = None,
    search_id: Optional[str] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Run one investigation round over an existing search result.

    `strategy` is supplied by the caller (round 1 gets the default, later rounds
    get whatever the strategy engine derived from memory).
    """
    ranked = search_result.get("ranked_candidates") or []
    strat = strategy or default_strategy(round_number)
    selected = select_candidates(ranked, strat)

    findings = [investigate_candidate(cand, ranked, strat) for cand in selected]

    # --- Live web evidence (You.com) + sandboxed screening (Daytona) ---------
    # Both are additive: without keys the round still completes on pipeline
    # evidence alone, and `sources_used` records honestly what actually ran.
    screen_batch: list[dict[str, Any]] = []
    for cand, finding in zip(selected, findings):
        items = youcom.search_evidence(
            drug=finding["drug_name"], disease=disease,
            formulation=strat.query_formulation,
            mechanism=cand.get("mechanism_of_action") or cand.get("target_hgnc_symbol"),
        )
        finding["live_evidence"] = items
        finding["live_evidence_count"] = len(items)
        if items:
            screen_batch.append({
                "drug": finding["drug_name"], "disease": disease, "evidence": items,
            })

    screening = daytona_sandbox.run_screening(screen_batch)
    for finding in findings:
        result = (screening.get("results") or {}).get(finding["drug_name"])
        if result and "error" not in result:
            finding["screening"] = result
            # A contradiction found in LIVE evidence is new information the
            # indexed pipeline could not have known. It downgrades the
            # investigation verdict only — never the Phase 1 ranking score.
            if result.get("flag") == "contradicted":
                finding["outcome"] = "weak"
                finding["what_failed"] = finding["what_failed"] + ["live_contradiction"]
            elif result.get("flag") == "supported":
                finding["what_worked"] = finding["what_worked"] + ["live_corroboration"]
        else:
            finding["screening"] = {}

    if persist and findings:
        record_experiences([
            Experience(
                disease=disease,
                candidate_drug=f["drug_name"],
                round_number=round_number,
                strategy_used=strat.to_dict(),
                evidence_summary=f["evidence_breakdown"],
                confidence=f["investigation_confidence"],
                outcome=f["outcome"],
                what_worked=f["what_worked"],
                what_failed=f["what_failed"],
                search_id=search_id,
            )
            for f in findings
        ])

    confidences = [f["investigation_confidence"] for f in findings]
    mean_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

    return {
        "round_number": round_number,
        "strategy": strat.to_dict(),
        "sources_used": {
            "youcom": youcom.is_configured(),
            "daytona": bool(screening.get("executed")),
            "daytona_detail": screening.get("reason") or screening.get("sandbox_id"),
            "live_evidence_items": sum(f.get("live_evidence_count", 0) for f in findings),
        },
        "candidates_investigated": [f["drug_name"] for f in findings],
        "findings": findings,
        "mean_confidence": mean_conf,
        "promising_count": sum(1 for f in findings if f["outcome"] == "promising"),
        "weak_count": sum(1 for f in findings if f["outcome"] == "weak"),
        "inconclusive_count": sum(1 for f in findings if f["outcome"] == "inconclusive"),
    }


def run_investigation(
    search_result: dict[str, Any],
    disease: str,
    search_id: Optional[str] = None,
    rounds: int = 2,
    persist: bool = True,
    publish: bool = True,
) -> dict[str, Any]:
    """Run round 1, learn from it, then run an adapted round 2.

    Round 2's strategy comes from `next_strategy` reading round 1's persisted
    experiences — the loop genuinely closes through the memory layer rather than
    passing state directly in-process.
    """
    round_1 = run_round(
        search_result, disease, 1,
        strategy=default_strategy(1), search_id=search_id, persist=persist,
    )
    strat_1 = default_strategy(1)

    if persist:
        history = load_experiences(disease=disease, search_id=search_id, round_number=1)
    else:
        # Reconstruct in-memory so a non-persisting caller still exercises the loop.
        history = [
            Experience(
                disease=disease,
                candidate_drug=f["drug_name"],
                round_number=1,
                strategy_used=strat_1.to_dict(),
                evidence_summary=f["evidence_breakdown"],
                confidence=f["investigation_confidence"],
                outcome=f["outcome"],
                what_worked=f["what_worked"],
                what_failed=f["what_failed"],
                search_id=search_id,
            )
            for f in round_1["findings"]
        ]

    strat_2, learning = next_strategy(history, strat_1)
    round_2 = run_round(
        search_result, disease, 2,
        strategy=strat_2, search_id=search_id, persist=persist,
    )

    learning_payload = learning.to_dict()
    diff = strategy_diff(strat_1, strat_2)

    # CrewAI narrates the (already-decided) adaptation for a human reader.
    crew_narrative = narrate_round(disease, round_1, round_2, learning_payload, diff)
    if crew_narrative:
        learning_payload = {
            **learning_payload,
            "crew": crew_narrative,
            "deterministic_what_i_learned": learning.what_i_learned,
            "deterministic_what_i_am_changing": learning.what_i_am_changing,
            "what_i_learned": crew_narrative["what_i_learned"],
            "what_i_am_changing": crew_narrative["what_i_am_changing"],
        }

    investigation = {
        "disease": disease,
        "search_id": search_id,
        "rounds_run": rounds,
        "round_1": round_1,
        "learning": learning_payload,
        "round_2": round_2,
        "strategy_diff": diff,
        "improvement": {
            "mean_confidence_round_1": round_1["mean_confidence"],
            "mean_confidence_round_2": round_2["mean_confidence"],
            "delta": round(round_2["mean_confidence"] - round_1["mean_confidence"], 3),
            "promising_round_1": round_1["promising_count"],
            "promising_round_2": round_2["promising_count"],
        },
    }

    # The loop's external side effect: write the outcome into the user's real
    # Notion workspace via One. Reported honestly whether or not it landed.
    if publish:
        investigation["published"] = one_client.publish_investigation(investigation)
    else:
        investigation["published"] = {"published": False, "reason": "publishing disabled"}

    return investigation
