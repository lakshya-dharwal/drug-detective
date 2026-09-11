"""Fast, fully local tests for the self-improving investigation loop.

No network, no LLM, no sponsor APIs. Every assertion is about deterministic
behaviour of the memory + strategy + round code.
"""

from __future__ import annotations

from agent.experience import (
    Experience,
    clear_experiences,
    load_experiences,
    record_experience,
)
from agent.rounds import investigate_candidate, run_investigation, run_round, select_candidates
from agent.strategy import Strategy, default_strategy, next_strategy, strategy_diff


# --------------------------------------------------------------------------
# Builders — shaped like real Phase 1 ranked_candidates entries.
# --------------------------------------------------------------------------
def make_candidate(
    name: str,
    score: float = 80.0,
    target: str = "SOD1",
    papers: int = 40,
    recent: int = 8,
    strength: float = 0.8,
    trials: int = 5,
    active: int = 2,
    safety_available: bool = True,
    boxed: bool = False,
) -> dict:
    return {
        "drug_name": name,
        "drug_chembl_id": f"CHEMBL_{name}",
        "final_score": score,
        "target_hgnc_symbol": target,
        "max_clinical_phase": "approved",
        "literature": {
            "literature_strength": strength,
            "total_papers": papers,
            "recent_papers": recent,
        },
        "trials": {"trial_count": trials, "active_count": active, "completed_count": 1},
        "safety": {"data_available": safety_available, "has_boxed_warning": boxed, "flags": []},
    }


def strong_candidate(name: str, **kw) -> dict:
    return make_candidate(name, **kw)


def weak_candidate(name: str, **kw) -> dict:
    """No papers, no trials, no FDA data -> should land as 'weak'."""
    defaults = dict(
        papers=0, recent=0, strength=0.0, trials=0, active=0, safety_available=False
    )
    defaults.update(kw)
    return make_candidate(name, **defaults)


def make_experience(name: str, outcome: str, round_number: int = 1, **kw) -> Experience:
    return Experience(
        disease="test disease",
        candidate_drug=name,
        round_number=round_number,
        strategy_used=default_strategy(round_number).to_dict(),
        evidence_summary={},
        confidence=kw.pop("confidence", 0.3),
        outcome=outcome,
        what_worked=kw.pop("what_worked", []),
        what_failed=kw.pop("what_failed", []),
        search_id=kw.pop("search_id", "search-1"),
    )


# --------------------------------------------------------------------------
# 1. Experience persistence
# --------------------------------------------------------------------------
def test_experience_roundtrips_through_the_store():
    record_experience(make_experience("DRUG_A", "weak"))
    record_experience(make_experience("DRUG_B", "promising", confidence=0.9))

    loaded = load_experiences(disease="test disease")
    assert [e.candidate_drug for e in loaded] == ["DRUG_A", "DRUG_B"]
    assert loaded[0].outcome == "weak"
    assert loaded[1].confidence == 0.9
    assert loaded[0].timestamp  # auto-stamped


def test_experience_filters_and_clearing():
    record_experience(make_experience("DRUG_A", "weak", round_number=1))
    record_experience(make_experience("DRUG_B", "promising", round_number=2))

    assert len(load_experiences(round_number=1)) == 1
    assert len(load_experiences(round_number=2)) == 1
    assert load_experiences(disease="other disease") == []
    assert len(load_experiences(search_id="search-1")) == 2

    clear_experiences()
    assert load_experiences() == []


def test_missing_store_reads_as_empty_memory():
    assert load_experiences(disease="never investigated") == []


# --------------------------------------------------------------------------
# 2. Default round-1 strategy
# --------------------------------------------------------------------------
def test_round_1_uses_the_default_strategy():
    strat = default_strategy(1)
    assert strat.round_number == 1
    assert strat.candidate_selection == "top_ranked"
    assert strat.excluded_drugs == []
    assert strat.evidence_priority == ["literature", "trials", "safety"]
    assert strat.query_formulation == "drug_disease"
    assert strat.changed_lever is None


def test_empty_memory_yields_the_default_strategy():
    strat, learning = next_strategy([])
    assert strat.candidate_selection == "top_ranked"
    assert strat.changed_lever is None
    assert "No previous investigation" in learning.what_i_learned


# --------------------------------------------------------------------------
# 3. Round 2 must actually differ after a bad round 1
# --------------------------------------------------------------------------
def test_weak_round_1_switches_the_candidate_selection_lever():
    history = [
        make_experience("DRUG_A", "weak", what_failed=["literature_absent"]),
        make_experience("DRUG_B", "weak", what_failed=["trials_absent"]),
        make_experience("DRUG_C", "promising", confidence=0.8, what_worked=["literature_strong"]),
    ]
    strat, learning = next_strategy(history, default_strategy(1))

    assert strat.round_number == 2
    assert strat.changed_lever == "candidate_selection"
    assert strat.candidate_selection == "skip_unproductive"
    assert strat.excluded_drugs == ["DRUG_A", "DRUG_B"]
    assert "DRUG_C" not in strat.excluded_drugs  # the one that worked is kept in play
    assert "DRUG_A" in learning.what_i_learned
    assert "deprioritize" in learning.what_i_am_changing


def test_a_consistently_empty_source_switches_the_evidence_priority_lever():
    # Every candidate was productive, so lever 1 does not fire; but trials were
    # empty for all of them, so the source ordering is what should change.
    history = [
        make_experience("DRUG_A", "promising", confidence=0.8,
                        what_worked=["literature_strong"], what_failed=["trials_absent"]),
        make_experience("DRUG_B", "promising", confidence=0.75,
                        what_worked=["literature_strong"], what_failed=["trials_absent"]),
        make_experience("DRUG_C", "promising", confidence=0.7,
                        what_worked=["literature_strong"], what_failed=["trials_absent"]),
    ]
    strat, learning = next_strategy(history, default_strategy(1))

    assert strat.changed_lever == "evidence_priority"
    assert strat.evidence_priority[-1] == "trials"      # demoted
    assert strat.evidence_priority[0] == "literature"   # promoted / kept leading
    assert strat.excluded_drugs == []                   # candidates untouched
    assert "trials" in learning.what_i_learned


def test_productive_but_thin_round_switches_the_query_formulation_lever():
    history = [
        make_experience("DRUG_A", "promising", confidence=0.8, what_worked=["literature_strong"]),
        make_experience("DRUG_B", "promising", confidence=0.75, what_worked=["trials_corroborate"]),
        make_experience("DRUG_C", "promising", confidence=0.7, what_worked=["safety_clean"]),
    ]
    strat, learning = next_strategy(history, default_strategy(1))

    assert strat.changed_lever == "query_formulation"
    assert strat.query_formulation == "mechanism_pathway"
    assert strat.excluded_drugs == []
    assert strat.evidence_priority == ["literature", "trials", "safety"]


def test_exactly_one_lever_changes_per_round():
    """The central discipline: adaptation must be attributable to one change."""
    histories = [
        [make_experience("A", "weak"), make_experience("B", "weak")],
        [make_experience("A", "promising", confidence=0.8, what_failed=["trials_absent"]),
         make_experience("B", "promising", confidence=0.8, what_failed=["trials_absent"])],
        [make_experience("A", "promising", confidence=0.8, what_worked=["literature_strong"]),
         make_experience("B", "promising", confidence=0.8, what_worked=["literature_strong"])],
    ]
    for history in histories:
        before = default_strategy(1)
        after, _ = next_strategy(history, before)
        diff = strategy_diff(before, after)
        levers = {
            "candidate_selection": {"candidate_selection", "excluded_drugs"},
            "evidence_priority": {"evidence_priority"},
            "query_formulation": {"query_formulation"},
        }[after.changed_lever]
        assert set(diff["changes"]) <= levers, diff


def test_strategy_adaptation_is_deterministic():
    history = [make_experience("DRUG_A", "weak"), make_experience("DRUG_B", "weak")]
    first, _ = next_strategy(history, default_strategy(1))
    second, _ = next_strategy(history, default_strategy(1))
    assert first.to_dict() == second.to_dict()


# --------------------------------------------------------------------------
# 4. Round orchestration
# --------------------------------------------------------------------------
def test_selection_respects_exclusions_and_dedupes_by_drug():
    ranked = [
        strong_candidate("DRUG_A"),
        strong_candidate("DRUG_A", target="TARDBP"),  # same drug, second target
        strong_candidate("DRUG_B"),
        strong_candidate("DRUG_C"),
        strong_candidate("DRUG_D"),
    ]
    picked = select_candidates(ranked, default_strategy(1))
    assert [c["drug_name"] for c in picked] == ["DRUG_A", "DRUG_B", "DRUG_C"]

    strat = Strategy(round_number=2, excluded_drugs=["DRUG_A", "DRUG_B"])
    picked = select_candidates(ranked, strat)
    assert [c["drug_name"] for c in picked] == ["DRUG_C", "DRUG_D"]


def test_investigation_verdicts_track_evidence_quality():
    strat = default_strategy(1)
    ranked = [strong_candidate("GOOD"), weak_candidate("BAD")]

    good = investigate_candidate(ranked[0], ranked, strat)
    bad = investigate_candidate(ranked[1], ranked, strat)

    assert good["outcome"] == "promising"
    assert good["investigation_confidence"] > bad["investigation_confidence"]
    assert bad["outcome"] == "weak"
    assert "literature_absent" in bad["what_failed"]
    assert "trials_absent" in bad["what_failed"]
    assert "safety_clean" in good["what_worked"]


def test_run_round_persists_one_experience_per_candidate():
    result = {"ranked_candidates": [strong_candidate(n) for n in ("A", "B", "C", "D")]}
    out = run_round(result, "test disease", 1, search_id="s1")

    assert out["candidates_investigated"] == ["A", "B", "C"]
    stored = load_experiences(disease="test disease", round_number=1)
    assert len(stored) == 3
    assert {e.candidate_drug for e in stored} == {"A", "B", "C"}
    assert all(e.strategy_used["round_number"] == 1 for e in stored)


def test_full_loop_learns_and_investigates_different_candidates():
    """End-to-end: weak top candidates -> round 2 moves down the ranked list."""
    result = {
        "ranked_candidates": [
            weak_candidate("WEAK_1", score=90.0),
            weak_candidate("WEAK_2", score=89.0),
            weak_candidate("WEAK_3", score=88.0),
            strong_candidate("STRONG_1", score=70.0),
            strong_candidate("STRONG_2", score=69.0),
            strong_candidate("STRONG_3", score=68.0),
        ]
    }
    out = run_investigation(result, "test disease", search_id="s1")

    # Round 1 took the top-ranked three and they did not pay off.
    assert out["round_1"]["candidates_investigated"] == ["WEAK_1", "WEAK_2", "WEAK_3"]
    assert out["round_1"]["weak_count"] == 3

    # It learned, changed one lever, and investigated different candidates.
    assert out["strategy_diff"]["changed_lever"] == "candidate_selection"
    assert out["round_2"]["candidates_investigated"] == ["STRONG_1", "STRONG_2", "STRONG_3"]
    assert out["round_2"]["candidates_investigated"] != out["round_1"]["candidates_investigated"]

    # And it measurably improved.
    assert out["improvement"]["delta"] > 0
    assert out["round_2"]["promising_count"] > out["round_1"]["promising_count"]

    # Both rounds are in memory, which is how round 2 read round 1.
    assert len(load_experiences(disease="test disease")) == 6


def test_round_2_reads_memory_rather_than_in_process_state():
    """Round 2's strategy must be derivable from the store alone."""
    result = {"ranked_candidates": [weak_candidate(f"W{i}") for i in range(3)]
              + [strong_candidate(f"S{i}") for i in range(3)]}
    run_round(result, "test disease", 1, search_id="s1")

    history = load_experiences(disease="test disease", search_id="s1", round_number=1)
    strat, learning = next_strategy(history, default_strategy(1))

    assert strat.changed_lever == "candidate_selection"
    assert set(strat.excluded_drugs) == {"W0", "W1", "W2"}
    assert learning.what_i_am_changing


# --------------------------------------------------------------------------
# 5. Run isolation — separate investigations must not bleed together
# --------------------------------------------------------------------------
def test_latest_run_isolates_the_most_recent_investigation():
    """Two runs reuse round numbers; memory must read back only the newer one."""
    from agent.experience import latest_run

    old = [make_experience("OLD_A", "weak", round_number=2)]
    old[0].run_id = "run-1"
    old[0].timestamp = "2026-01-01T00:00:00+00:00"
    new = [make_experience("NEW_A", "weak", round_number=2)]
    new[0].run_id = "run-2"
    new[0].timestamp = "2026-06-01T00:00:00+00:00"

    picked = latest_run(old + new)
    assert [e.candidate_drug for e in picked] == ["NEW_A"]


def test_load_experiences_filters_by_run_id():
    a = make_experience("A", "weak")
    a.run_id = "run-1"
    b = make_experience("B", "weak")
    b.run_id = "run-2"
    record_experience(a)
    record_experience(b)

    assert [e.candidate_drug for e in load_experiences(run_id="run-1")] == ["A"]
    assert [e.candidate_drug for e in load_experiences(run_id="run-2")] == ["B"]


def test_rounds_from_one_investigation_share_a_run_id():
    result = {"ranked_candidates": [strong_candidate(n) for n in ("A", "B", "C", "D", "E", "F")]}
    run_investigation(result, "test disease", search_id="s1", publish=False)

    stored = load_experiences(disease="test disease")
    run_ids = {e.run_id for e in stored}
    assert len(run_ids) == 1 and None not in run_ids


# --------------------------------------------------------------------------
# 6. Cross-session recall — a second investigation starts smarter
# --------------------------------------------------------------------------
def test_second_investigation_recalls_the_first_and_starts_adapted():
    """The headline claim: investigate the same disease twice, get smarter."""
    result = {
        "ranked_candidates": [
            weak_candidate("WEAK_1", score=90.0),
            weak_candidate("WEAK_2", score=89.0),
            weak_candidate("WEAK_3", score=88.0),
            strong_candidate("STRONG_1", score=70.0),
            strong_candidate("STRONG_2", score=69.0),
            strong_candidate("STRONG_3", score=68.0),
        ]
    }

    first = run_investigation(result, "test disease", search_id="s1", publish=False)
    assert first["prior_experience"]["recalled"] is False
    assert first["round_1"]["candidates_investigated"] == ["WEAK_1", "WEAK_2", "WEAK_3"]

    second = run_investigation(result, "test disease", search_id="s2", publish=False)
    # It remembered, and did NOT waste round 1 on the known dead ends.
    assert second["prior_experience"]["recalled"] is True
    assert second["prior_experience"]["prior_rounds_recalled"] > 0
    assert second["round_1"]["candidates_investigated"] != first["round_1"]["candidates_investigated"]
    assert "WEAK_1" not in second["round_1"]["candidates_investigated"]
    # Starting smarter shows up as a better opening round.
    assert second["round_1"]["mean_confidence"] > first["round_1"]["mean_confidence"]


def test_first_investigation_of_an_unseen_disease_uses_the_default():
    result = {"ranked_candidates": [strong_candidate(n) for n in ("A", "B", "C")]}
    out = run_investigation(result, "never seen before", search_id="s1", publish=False)
    assert out["prior_experience"]["recalled"] is False
    assert out["round_1"]["strategy"]["candidate_selection"] == "top_ranked"


# --------------------------------------------------------------------------
# 7. N rounds
# --------------------------------------------------------------------------
def test_rounds_parameter_is_actually_honoured():
    result = {"ranked_candidates": [weak_candidate(f"W{i}") for i in range(12)]}
    out = run_investigation(result, "test disease", search_id="s1", rounds=4, publish=False)

    assert out["rounds_run"] == 4
    assert len(out["rounds"]) == 4
    assert [r["round_number"] for r in out["rounds"]] == [1, 2, 3, 4]
    # Each round abandons more dead ends than the last.
    exclusions = [len(r["strategy"]["excluded_drugs"]) for r in out["rounds"]]
    assert exclusions == sorted(exclusions) and exclusions[-1] > exclusions[0]


def test_round_aliases_point_at_first_and_last_round():
    result = {"ranked_candidates": [weak_candidate(f"W{i}") for i in range(12)]}
    out = run_investigation(result, "test disease", search_id="s1", rounds=3, publish=False)
    assert out["round_1"] is out["rounds"][0]
    assert out["round_2"] is out["rounds"][-1]
    assert out["improvement"]["mean_confidence_round_2"] == out["rounds"][-1]["mean_confidence"]


def test_rounds_below_two_are_clamped():
    result = {"ranked_candidates": [strong_candidate(n) for n in ("A", "B", "C")]}
    out = run_investigation(result, "test disease", rounds=1, publish=False)
    assert out["rounds_run"] == 2  # a loop needs at least one adaptation


# --------------------------------------------------------------------------
# 8. The LLM must never overwrite the deterministic decision
# --------------------------------------------------------------------------
def test_crew_narration_cannot_replace_the_deterministic_learning(monkeypatch):
    import agent.rounds as rounds_mod

    monkeypatch.setattr(
        rounds_mod, "narrate_round",
        lambda *a, **k: {
            "orchestrated_by": "crewai",
            "agents": ["a", "b", "c"],
            "narrative_learned": "TOTALLY DIFFERENT CLAIM",
            "narrative_changing": "A CHANGE THAT NEVER HAPPENED",
        },
    )
    result = {"ranked_candidates": [weak_candidate(f"W{i}") for i in range(6)]}
    out = run_investigation(result, "test disease", publish=False)

    assert out["learning"]["what_i_learned"] != "TOTALLY DIFFERENT CLAIM"
    assert out["learning"]["what_i_am_changing"] != "A CHANGE THAT NEVER HAPPENED"
    assert out["learning"]["crew"]["narrative_learned"] == "TOTALLY DIFFERENT CLAIM"


def test_publishing_can_be_disabled_without_touching_the_network():
    result = {"ranked_candidates": [strong_candidate(n) for n in ("A", "B", "C")]}
    out = run_investigation(result, "test disease", publish=False)
    assert out["published"]["published"] is False
