"""Canonical entity resolution layer.

Every gene is resolved to an Ensembl gene ID; every drug is resolved to a
ChEMBL ID. Resolution goes through Open Targets' `search` endpoint (which
fuzzy-matches names/symbols/synonyms) and results are cached indefinitely in
a local JSON lookup table (entity_cache.json) so repeated lookups for the
same name never hit the network again.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from src.models import ResolvedDisease, ResolvedDrug, ResolvedGene
from src.open_targets_client import (
    OpenTargetsAPIError,
    get_drug_detail,
    get_target_detail,
    search_entities,
)

logger = logging.getLogger(__name__)

ENTITY_CACHE_PATH = Path(os.getenv("ENTITY_CACHE_PATH", "data/entity_cache.json"))
_cache_lock = threading.Lock()

_EMPTY_CACHE = {"genes": {}, "drugs": {}, "diseases": {}}


def _load_entity_cache() -> dict:
    if not ENTITY_CACHE_PATH.exists():
        return {"genes": {}, "drugs": {}, "diseases": {}}
    try:
        with ENTITY_CACHE_PATH.open("r", encoding="utf-8") as f:
            cache = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read entity cache, starting fresh: %s", exc)
        return {"genes": {}, "drugs": {}, "diseases": {}}
    for section in ("genes", "drugs", "diseases"):
        cache.setdefault(section, {})
    return cache


def _save_entity_cache(cache: dict) -> None:
    ENTITY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ENTITY_CACHE_PATH.open("w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError as exc:
        logger.warning("Failed to write entity cache: %s", exc)


def _normalize_key(name: str) -> str:
    return name.strip().lower()


def resolve_gene(name_or_symbol: str) -> Optional[ResolvedGene]:
    """Resolve a gene name/symbol to its canonical Ensembl ID via Open Targets search.

    Returns None if no match is found or the lookup fails after retries.
    """
    key = _normalize_key(name_or_symbol)

    with _cache_lock:
        cache = _load_entity_cache()
        if key in cache["genes"]:
            return ResolvedGene(**cache["genes"][key])

    try:
        hits = search_entities(name_or_symbol, "target")
    except OpenTargetsAPIError as exc:
        logger.error("Gene resolution failed for '%s': %s", name_or_symbol, exc)
        return None

    if not hits:
        logger.warning("No gene match found for '%s'", name_or_symbol)
        return None

    top = hits[0]
    synonyms = [h["name"] for h in hits[1:] if h["name"] != top["name"]]

    try:
        detail = get_target_detail(top["id"])
        if detail and detail.get("synonyms"):
            synonyms = list(dict.fromkeys(synonyms + [s["label"] for s in detail["synonyms"]]))
    except OpenTargetsAPIError as exc:
        logger.warning("Could not fetch synonym detail for target %s: %s", top["id"], exc)

    resolved = ResolvedGene(ensembl_id=top["id"], hgnc_symbol=top["name"], synonyms=synonyms)

    with _cache_lock:
        cache = _load_entity_cache()
        cache["genes"][key] = resolved.model_dump()
        _save_entity_cache(cache)

    return resolved


def resolve_drug(name_or_synonym: str) -> Optional[ResolvedDrug]:
    """Resolve a drug name/synonym to its canonical ChEMBL ID via Open Targets search."""
    key = _normalize_key(name_or_synonym)

    with _cache_lock:
        cache = _load_entity_cache()
        if key in cache["drugs"]:
            return ResolvedDrug(**cache["drugs"][key])

    try:
        hits = search_entities(name_or_synonym, "drug")
    except OpenTargetsAPIError as exc:
        logger.error("Drug resolution failed for '%s': %s", name_or_synonym, exc)
        return None

    if not hits:
        logger.warning("No drug match found for '%s'", name_or_synonym)
        return None

    top = hits[0]
    synonyms = [h["name"] for h in hits[1:] if h["name"] != top["name"]]
    drugbank_id = None

    try:
        detail = get_drug_detail(top["id"])
        if detail:
            if detail.get("synonyms"):
                synonyms = list(dict.fromkeys(synonyms + [s["label"] for s in detail["synonyms"]]))
            for xref in detail.get("crossReferences") or []:
                if xref.get("source", "").lower() == "drugbank" and xref.get("ids"):
                    drugbank_id = xref["ids"][0]
                    break
    except OpenTargetsAPIError as exc:
        logger.warning("Could not fetch synonym detail for drug %s: %s", top["id"], exc)

    resolved = ResolvedDrug(
        chembl_id=top["id"],
        drugbank_id=drugbank_id,
        canonical_name=top["name"],
        synonyms=synonyms,
    )

    with _cache_lock:
        cache = _load_entity_cache()
        cache["drugs"][key] = resolved.model_dump()
        _save_entity_cache(cache)

    return resolved


def resolve_disease(name: str) -> Optional[ResolvedDisease]:
    """Resolve a disease name to its canonical EFO/MONDO ID via Open Targets search.

    Not required by the spec's resolver interface, but lives here since it's the
    same search-and-cache pattern and the pipeline needs it as its entry point.
    """
    key = _normalize_key(name)

    with _cache_lock:
        cache = _load_entity_cache()
        if key in cache["diseases"]:
            return ResolvedDisease(**cache["diseases"][key])

    try:
        hits = search_entities(name, "disease")
    except OpenTargetsAPIError as exc:
        logger.error("Disease resolution failed for '%s': %s", name, exc)
        return None

    if not hits:
        return None

    top = hits[0]
    resolved = ResolvedDisease(efo_id=top["id"], name=top["name"])

    with _cache_lock:
        cache = _load_entity_cache()
        cache["diseases"][key] = resolved.model_dump()
        _save_entity_cache(cache)

    return resolved
