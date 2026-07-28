"""Display-layer AI chat over a single search's results (Phase 5 / Tier 4).

STRICT GROUNDING: the model may only answer from the ranked results + evidence
the frontend passes in. It never invents drugs, scores, or citations, and it is
explicitly told to say when the answer isn't in the provided data. This is a
research aid, not medical advice, and it never changes any score.

Disabled gracefully when OPENAI_API_KEY is absent.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or None
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
CHAT_TEMPERATURE = float(os.getenv("OPENAI_CHAT_TEMPERATURE", "0.2"))
MAX_DRUGS_IN_CONTEXT = int(os.getenv("MAX_DRUGS_IN_CONTEXT", "15"))

_SYSTEM_PROMPT = (
    "You are a research assistant for a drug-repurposing tool. You will be given "
    "a disease and a JSON list of ranked candidate drugs with their evidence "
    "(scores, mechanism, publication counts, FDA safety flags, clinical trials). "
    "Answer the user's question using ONLY this provided data.\n"
    "Rules:\n"
    "- Use ONLY the provided results. Do NOT use outside knowledge or invent drugs, "
    "numbers, PMIDs, or trials.\n"
    "- If the answer is not in the provided data, say so plainly.\n"
    "- Refer to drugs by name and cite concrete evidence from the data (e.g. paper "
    "counts, trial counts, safety flags) when relevant.\n"
    "- Be concise (a few sentences). This is research information, NOT medical advice; "
    "do not recommend treatment for any individual."
)


def is_enabled() -> bool:
    return OPENAI_API_KEY is not None


def answer_question(disease: str, question: str, drugs: list[dict[str, Any]]) -> dict[str, Any]:
    """Return {answer, tokens} grounded in the provided drug context.

    `drugs` is a compact list built by the frontend from the search result.
    """
    if not is_enabled():
        return {
            "answer": "AI chat is not configured on this deployment (no OpenAI API key). "
            "The ranked results and their evidence above remain fully available.",
            "disabled": True,
        }

    context = drugs[:MAX_DRUGS_IN_CONTEXT]
    import json as _json

    user_content = (
        f"Disease: {disease}\n\n"
        f"Ranked candidate drugs (JSON):\n{_json.dumps(context, ensure_ascii=False)}\n\n"
        f"Question: {question}"
    )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=OPENAI_CHAT_MODEL,
            temperature=CHAT_TEMPERATURE,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        usage = resp.usage
        logger.info(
            "Chat answered for '%s': %d prompt + %d completion tokens",
            disease,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )
        return {"answer": text, "disabled": False}
    except Exception as exc:  # noqa: BLE001 - never crash the API on a chat failure
        logger.error("Chat failed for '%s': %s", disease, exc)
        return {"answer": "Sorry — the chat request failed. Please try again.", "error": str(exc)}
