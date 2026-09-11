"""Daytona — the computational screening step, run in an isolated sandbox.

The agent hands a deterministic screening script plus this round's retrieved
evidence to a Daytona sandbox and gets structured numbers back. Running it
off-box is the point: the script is generated per round and executes untrusted
scraped text, so it should not run in the API process.

The arithmetic stays deterministic and auditable — the sandbox is where it runs,
not a black box that invents a score. Degrades to a skipped status without a key.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

TIMEOUT = int(os.getenv("DAYTONA_TIMEOUT_SECONDS", "90"))

# Runs INSIDE the sandbox. Pure stdlib, deterministic, no network.
SCREENING_SCRIPT = r'''
import json, sys, re
from datetime import datetime

payload = json.loads(sys.stdin.read())
items = payload.get("evidence", [])
drug = payload.get("drug", "")
disease = payload.get("disease", "")

CORROBORATING = ("trial", "efficacy", "improv", "benefit", "treat", "therap", "phase")
CONTRADICTING = ("failed", "no benefit", "terminated", "withdrawn", "ineffective",
                 "halted", "discontinued", "negative result")
HIGH_QUALITY = ("nih.gov", "nature.com", "nejm.org", "thelancet.com", "science.org",
                "cell.com", "bmj.com", "jamanetwork.com", "clinicaltrials.gov",
                "pubmed", "europepmc", "biorxiv", "medrxiv", ".edu", "who.int")

corroborating = contradicting = high_quality = recent = 0
years = []
for it in items:
    text = " ".join(str(it.get(k, "")) for k in ("title", "description", "snippet")).lower()
    url = str(it.get("url", "")).lower()
    if any(t in text for t in CORROBORATING): corroborating += 1
    if any(t in text for t in CONTRADICTING): contradicting += 1
    if any(d in url for d in HIGH_QUALITY):   high_quality += 1
    for y in re.findall(r"\b(20[0-2]\d)\b", text):
        years.append(int(y))
        if int(y) >= datetime.utcnow().year - 2: recent += 1

n = max(len(items), 1)
support   = corroborating / n
contra    = contradicting / n
quality   = high_quality / n
recency   = min(recent / n, 1.0)

# Deterministic weighted screen. Contradiction subtracts.
screen = max(0.0, min(1.0, 0.40*support + 0.25*quality + 0.25*recency - 0.30*contra))

print(json.dumps({
    "drug": drug, "disease": disease, "items_screened": len(items),
    "corroborating": corroborating, "contradicting": contradicting,
    "high_quality_sources": high_quality,
    "support_ratio": round(support, 3), "contradiction_ratio": round(contra, 3),
    "source_quality_ratio": round(quality, 3), "recency_ratio": round(recency, 3),
    "screening_score": round(screen, 3),
    "latest_year": max(years) if years else None,
    "flag": "contradicted" if contra > 0.3 else ("supported" if screen >= 0.5 else "weak"),
}))
'''


def is_configured() -> bool:
    return bool(os.getenv("DAYTONA_API_KEY"))


def run_screening(batch: list[dict[str, Any]]) -> dict[str, Any]:
    """Screen each candidate's retrieved evidence inside one Daytona sandbox.

    `batch` is [{drug, disease, evidence:[...]}, ...]. One sandbox is reused for
    the whole batch — creating one per candidate would dominate the round's time.
    """
    if not is_configured():
        return {"executed": False, "reason": "DAYTONA_API_KEY not set", "results": {}}
    if not batch:
        return {"executed": False, "reason": "no evidence to screen", "results": {}}

    try:
        from daytona import Daytona, DaytonaConfig
    except ImportError:
        return {"executed": False, "reason": "daytona SDK not installed", "results": {}}

    sandbox = None
    try:
        client = Daytona(DaytonaConfig(api_key=os.getenv("DAYTONA_API_KEY")))
        sandbox = client.create()
        results: dict[str, Any] = {}
        for entry in batch:
            code = (
                "import subprocess,sys\n"
                f"script = {SCREENING_SCRIPT!r}\n"
                f"data = {json.dumps(entry)!r}\n"
                "p = subprocess.run([sys.executable,'-c',script],input=data,"
                "capture_output=True,text=True,timeout=60)\n"
                "print(p.stdout.strip() or p.stderr.strip())\n"
            )
            resp = sandbox.process.code_run(code)
            raw = (resp.result or "").strip()
            try:
                results[entry["drug"]] = json.loads(raw.splitlines()[-1])
            except (ValueError, IndexError):
                logger.warning("Daytona screening unparseable for %s: %s", entry.get("drug"), raw[:200])
                results[entry["drug"]] = {"error": "unparseable", "raw": raw[:200]}
        return {
            "executed": True, "sandbox_id": getattr(sandbox, "id", None),
            "candidates_screened": len(results), "results": results,
        }
    except Exception as exc:  # noqa: BLE001 - sandbox must never break the round
        logger.warning("Daytona screening failed: %s", exc)
        return {"executed": False, "reason": str(exc)[:200], "results": {}}
    finally:
        if sandbox is not None:
            try:
                sandbox.delete()
            except Exception:  # noqa: BLE001
                pass
