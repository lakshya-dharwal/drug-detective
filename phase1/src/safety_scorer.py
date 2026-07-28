"""Deterministic safety scoring from OpenFDA labels.

Produces a 0-1 severity that the ranking engine scales into the -5% safety
penalty budget. Purely factual/rule-based — no LLM interpretation. Absence of
FDA data is neutral (severity 0), NOT a penalty.

Severity rules (configurable):
  * boxed warning present      -> BOXED_WARNING_SEVERITY (largest)
  * contraindications present  -> CONTRAINDICATION_SEVERITY (smaller)
  * neither / no data          -> 0.0
Severity is the max applicable rule (not additive), capped at 1.0.
"""

from __future__ import annotations

import logging

from src.models import SafetyFlag, SafetyInfo
from src.openfda_client import get_drug_label, label_url

logger = logging.getLogger(__name__)

BOXED_WARNING_SEVERITY = 1.0        # full -5% penalty at scale
CONTRAINDICATION_SEVERITY = 0.4     # ~-2% penalty at scale


def score_safety(drug_name: str) -> SafetyInfo:
    """Return deterministic safety evidence for a drug (never raises)."""
    label = get_drug_label(drug_name)
    if label is None:
        # No FDA record -> neutral. Not penalized.
        return SafetyInfo(safety_penalty=0.0, has_boxed_warning=False, flags=[], data_available=False)

    flags: list[SafetyFlag] = []
    severity = 0.0
    url = label_url(label)

    boxed = label.get("boxed_warning")
    if boxed:
        severity = max(severity, BOXED_WARNING_SEVERITY)
        flags.append(SafetyFlag(kind="boxed_warning", label="FDA boxed warning", source_url=url))

    contra = label.get("contraindications")
    if contra:
        severity = max(severity, CONTRAINDICATION_SEVERITY)
        flags.append(SafetyFlag(kind="contraindication", label="Has contraindications", source_url=url))

    return SafetyInfo(
        safety_penalty=min(severity, 1.0),
        has_boxed_warning=bool(boxed),
        flags=flags,
        data_available=True,
    )
