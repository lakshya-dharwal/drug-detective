"""CrewAI orchestration of the investigation round — three agents, no more.

Division of labour, and the hard line this respects:

  Research Agent  — decides what to retrieve and reads the You.com results.
  Evidence Agent  — summarises what the evidence and sandbox screen actually show.
  Critic Agent    — narrates the learning in scientific, hedged language.

The Critic does NOT choose the next strategy. `agent/strategy.py` does, as a pure
deterministic function, and the Critic narrates that decision. Likewise no agent
touches the Phase 1 ranking score. Keeping the LLM out of both the score and the
adaptation decision is what keeps this reproducible.

Disabled by default (ENABLE_CREWAI=1 to turn on) and degrades to the
deterministic text from strategy.py if anything fails.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    return os.getenv("ENABLE_CREWAI", "0") == "1" and bool(os.getenv("OPENAI_API_KEY"))


def narrate_round(
    disease: str, round_1: dict[str, Any], round_2: dict[str, Any],
    learning: dict[str, str], strategy_diff: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Run the 3-agent crew to produce a scientist-readable account of the round.

    Returns None if disabled or unavailable, in which case callers keep the
    deterministic narrative. Never raises into the request path.
    """
    if not is_enabled():
        return None

    try:
        from crewai import Agent, Crew, Process, Task
    except ImportError:
        logger.warning("CrewAI not installed; falling back to deterministic narrative")
        return None

    model = os.getenv("CREWAI_MODEL", "gpt-4o-mini")

    def summarise(r: dict[str, Any]) -> str:
        return "; ".join(
            f"{f['drug_name']} (confidence {f['investigation_confidence']}, {f['outcome']}"
            + (f", live-evidence screen {f['screening']['screening_score']}"
               if f.get("screening", {}).get("screening_score") is not None else "")
            + ")"
            for f in r.get("findings", [])
        )

    context = (
        f"Disease under investigation: {disease}\n"
        f"Round 1 strategy: {round_1.get('strategy')}\n"
        f"Round 1 findings: {summarise(round_1)}\n"
        f"Deterministic strategy change: lever '{strategy_diff.get('changed_lever')}' — "
        f"{strategy_diff.get('rationale')}\n"
        f"Round 2 findings: {summarise(round_2)}\n"
        f"Deterministic learning statement: {learning.get('what_i_learned')}\n"
        f"Deterministic change statement: {learning.get('what_i_am_changing')}\n"
    )

    guardrail = (
        "These are drug repurposing HYPOTHESES for further investigation, never "
        "treatment recommendations. Use hedged scientific language: 'candidate', "
        "'signal', 'evidence suggests'. Never claim a drug treats or is effective "
        "for the disease. Do not invent evidence beyond what is given."
    )

    try:
        researcher = Agent(
            role="Biomedical Research Agent",
            goal="Characterise what the retrieved live evidence shows about each candidate.",
            backstory="You assess literature and trial evidence for drug repurposing signals.",
            llm=model, verbose=False, allow_delegation=False,
        )
        evidence = Agent(
            role="Evidence Assessment Agent",
            goal="State plainly which candidates are supported and which are not, and why.",
            backstory="You weigh corroboration, source quality and contradiction.",
            llm=model, verbose=False, allow_delegation=False,
        )
        critic = Agent(
            role="Strategy Critic",
            goal="Explain what the agent learned and why its next investigation changed.",
            backstory=("You explain an ALREADY-MADE deterministic strategy decision to a "
                       "scientist. You never invent or override the decision."),
            llm=model, verbose=False, allow_delegation=False,
        )

        t1 = Task(
            description=f"{context}\nSummarise the evidence picture per candidate in 2-3 sentences.\n{guardrail}",
            expected_output="2-3 sentences on the evidence per candidate.", agent=researcher,
        )
        t2 = Task(
            description=f"Assess which candidates hold up and which do not, and why. {guardrail}",
            expected_output="A short assessment naming supported vs unsupported candidates.",
            agent=evidence, context=[t1],
        )
        t3 = Task(
            description=(
                "Write exactly two labelled lines explaining the strategy change that was "
                "ALREADY made deterministically (do not propose a different one):\n"
                "LEARNED: <one sentence>\nCHANGED: <one sentence>\n" + guardrail
            ),
            expected_output="Two lines, prefixed LEARNED: and CHANGED:.",
            agent=critic, context=[t1, t2],
        )

        crew = Crew(agents=[researcher, evidence, critic], tasks=[t1, t2, t3],
                    process=Process.sequential, verbose=False)
        result = str(crew.kickoff())

        learned = changed = None
        for line in result.splitlines():
            s = line.strip()
            if s.upper().startswith("LEARNED:"):
                learned = s.split(":", 1)[1].strip()
            elif s.upper().startswith("CHANGED:"):
                changed = s.split(":", 1)[1].strip()

        return {
            "orchestrated_by": "crewai",
            "agents": ["Biomedical Research Agent", "Evidence Assessment Agent", "Strategy Critic"],
            "evidence_assessment": str(t2.output) if t2.output else None,
            "what_i_learned": learned or learning.get("what_i_learned"),
            "what_i_am_changing": changed or learning.get("what_i_am_changing"),
            "note": "Narrative only — the strategy change itself was computed deterministically.",
        }
    except Exception as exc:  # noqa: BLE001 - never break the round
        logger.warning("CrewAI narration failed: %s", exc)
        return None
