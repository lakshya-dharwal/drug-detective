"""Display-only LLM summarization of retrieved PubMed abstracts.

STRICT GUARDRAILS — this module NEVER influences scores or ranking. It only
produces a short, human-readable narration of abstracts we already retrieved,
and it always shows its source PMIDs.

  * Input to the model is ONLY the retrieved abstracts. The prompt forbids
    outside knowledge and speculation.
  * If no abstracts are available, the LLM is NOT called — we return a fixed
    "no direct literature" string.
  * If OPENAI_API_KEY is not set (or the SDK is missing), summarization is
    disabled and returns None; callers show the papers list without a summary.
  * Temperature is low. Token usage is logged for cost visibility.
  * Summaries are cached per (drug, disease) so we don't pay twice.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from src.cache_manager import get_cached, set_cached
from src.pubmed_client import get_abstracts

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or None
OPENAI_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")
SUMMARY_TEMPERATURE = float(os.getenv("OPENAI_SUMMARY_TEMPERATURE", "0.2"))
MAX_ABSTRACTS_IN_PROMPT = int(os.getenv("MAX_ABSTRACTS_IN_PROMPT", "6"))

NO_EVIDENCE_TEXT = "No direct literature found for this drug-disease pair."

_SYSTEM_PROMPT = (
    "You are a biomedical research assistant. You will be given the titles and "
    "abstracts of PubMed articles about a specific drug and disease. Summarize "
    "ONLY what these abstracts say, in 2-3 sentences, in plain language.\n"
    "Rules:\n"
    "- Use ONLY the provided abstracts. Do NOT use any outside knowledge.\n"
    "- Cite the PMIDs you draw from, in brackets like [PMID: 12345678].\n"
    "- If the abstracts do not clearly support a drug-disease link, say so; "
    "write 'Limited published evidence' rather than speculating.\n"
    "- Never state efficacy or safety conclusions that the abstracts do not.\n"
    "- Do not recommend treatment. This is a research summary, not advice."
)


@dataclass
class SummaryResult:
    summary: str
    pmids: list[str]
    prompt_tokens: int = 0
    completion_tokens: int = 0


def is_enabled() -> bool:
    return OPENAI_API_KEY is not None


def summarize_evidence(drug_name: str, disease_name: str, pmids: list[str]) -> Optional[SummaryResult]:
    """Return a display-only summary for a drug-disease pair, or None if disabled.

    Returns a fixed no-evidence SummaryResult (no LLM call) when there are no
    PMIDs. Returns None only when summarization is unavailable (no API key), so
    callers can distinguish "nothing to say" from "feature off".
    """
    if not pmids:
        return SummaryResult(summary=NO_EVIDENCE_TEXT, pmids=[])

    cache_key = f"llm_summary::{OPENAI_MODEL}::{drug_name.lower()}::{disease_name.lower()}::{','.join(sorted(pmids))}"
    cached = get_cached(cache_key)
    if cached is not None:
        return SummaryResult(**cached)

    if not is_enabled():
        logger.info("LLM summarization disabled (no OPENAI_API_KEY); skipping for %s / %s", drug_name, disease_name)
        return None

    abstracts = get_abstracts(pmids[:MAX_ABSTRACTS_IN_PROMPT])
    abstracts = [a for a in abstracts if a.get("abstract")]
    if not abstracts:
        # We have PMIDs but no usable abstract text — do not invent a summary.
        return SummaryResult(summary=NO_EVIDENCE_TEXT, pmids=[])

    user_content = _build_user_prompt(drug_name, disease_name, abstracts)

    try:
        result = _call_openai(user_content)
    except Exception as exc:  # noqa: BLE001 - never break the pipeline on LLM failure
        logger.error("LLM summarization failed for %s / %s: %s", drug_name, disease_name, exc)
        return None

    used_pmids = [a["pmid"] for a in abstracts if a.get("pmid")]
    result.pmids = used_pmids
    logger.info(
        "LLM summary for %s / %s: %d prompt + %d completion tokens (model %s)",
        drug_name,
        disease_name,
        result.prompt_tokens,
        result.completion_tokens,
        OPENAI_MODEL,
    )
    set_cached(cache_key, result.__dict__)
    return result


def _build_user_prompt(drug_name: str, disease_name: str, abstracts: list[dict[str, Any]]) -> str:
    lines = [f"Drug: {drug_name}", f"Disease: {disease_name}", "", "Abstracts:"]
    for a in abstracts:
        lines.append(f"[PMID: {a['pmid']}] {a['title']}\n{a['abstract']}\n")
    return "\n".join(lines)


def _call_openai(user_content: str) -> SummaryResult:
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=SUMMARY_TEMPERATURE,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    usage = resp.usage
    return SummaryResult(
        summary=text,
        pmids=[],
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )
