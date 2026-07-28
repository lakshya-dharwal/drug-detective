"""Thin client for the Open Targets Platform GraphQL API.

Handles: search-based entity resolution, disease -> gene associations, and
gene -> drug (known/candidate drug) associations. All network calls go through
`execute_query`, which applies retry-with-backoff and raises `OpenTargetsAPIError`
on unrecoverable failure so callers can decide how to degrade gracefully.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import requests

from src.cache_manager import get_cached, set_cached

logger = logging.getLogger(__name__)

API_URL = os.getenv("OPEN_TARGETS_API_URL", "https://api.platform.opentargets.org/api/v4/graphql")
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))

SOURCE_NAME = "Open Targets Platform"


class OpenTargetsAPIError(Exception):
    """Raised when the Open Targets API call fails after all retries."""


def execute_query(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """POST a GraphQL query, retrying transient failures with exponential backoff.

    Retries up to MAX_RETRIES times (so MAX_RETRIES=2 means 3 attempts total),
    with delays of 1s, 2s, 4s... Raises OpenTargetsAPIError if all attempts fail
    or the API returns GraphQL-level errors.
    """
    last_exc: Optional[Exception] = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                API_URL,
                json={"query": query, "variables": variables},
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()

            if "errors" in payload:
                raise OpenTargetsAPIError(f"GraphQL errors: {payload['errors']}")

            return payload["data"]

        except (requests.RequestException, ValueError, KeyError) as exc:
            last_exc = exc
            logger.warning(
                "Open Targets API call failed (attempt %d/%d): %s",
                attempt + 1,
                MAX_RETRIES + 1,
                exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(2**attempt)
        except OpenTargetsAPIError as exc:
            # GraphQL-level errors are not transient (bad query/args) - don't retry.
            raise exc

    raise OpenTargetsAPIError(f"Open Targets API call failed after {MAX_RETRIES + 1} attempts") from last_exc


# --------------------------------------------------------------------------
# Search (used by entity_resolver.py)
# --------------------------------------------------------------------------

SEARCH_QUERY = """
query Search($q: String!, $entityNames: [String!]!) {
  search(queryString: $q, entityNames: $entityNames, page: {index: 0, size: 5}) {
    total
    hits {
      id
      name
      entity
    }
  }
}
"""


def search_entities(query_string: str, entity_name: str) -> list[dict[str, Any]]:
    """entity_name is one of "target", "drug", "disease"."""
    data = execute_query(SEARCH_QUERY, {"q": query_string, "entityNames": [entity_name]})
    return data.get("search", {}).get("hits", [])


TARGET_DETAIL_QUERY = """
query TargetDetail($id: String!) {
  target(ensemblId: $id) {
    id
    approvedSymbol
    synonyms { label }
  }
}
"""


def get_target_detail(ensembl_id: str) -> Optional[dict[str, Any]]:
    data = execute_query(TARGET_DETAIL_QUERY, {"id": ensembl_id})
    return data.get("target")


DRUG_DETAIL_QUERY = """
query DrugDetail($id: String!) {
  drug(chemblId: $id) {
    id
    name
    synonyms { label source }
    crossReferences { source ids }
  }
}
"""


def get_drug_detail(chembl_id: str) -> Optional[dict[str, Any]]:
    data = execute_query(DRUG_DETAIL_QUERY, {"id": chembl_id})
    return data.get("drug")


# --------------------------------------------------------------------------
# Disease -> gene associations
# --------------------------------------------------------------------------

DISEASE_ASSOCIATIONS_QUERY = """
query DiseaseTargets($efoId: String!, $size: Int!) {
  disease(efoId: $efoId) {
    id
    name
    associatedTargets(page: {index: 0, size: $size}) {
      count
      rows {
        score
        target {
          id
          approvedSymbol
        }
      }
    }
  }
}
"""


def get_disease_gene_associations(
    efo_id: str, max_genes: int = 50, use_cache: bool = True
) -> Optional[dict[str, Any]]:
    """Returns the raw `disease` payload (id, name, associatedTargets.rows), or None.

    Applies the standard cache -> live call -> stale-cache-fallback flow.
    """
    cache_key = f"disease_targets::{efo_id}::{max_genes}"

    if use_cache:
        cached = get_cached(cache_key)
        if cached is not None:
            logger.info("Using cached disease-target associations for %s", efo_id)
            return cached

    try:
        data = execute_query(DISEASE_ASSOCIATIONS_QUERY, {"efoId": efo_id, "size": max_genes})
        disease = data.get("disease")
        if disease is not None:
            set_cached(cache_key, disease)
        return disease
    except OpenTargetsAPIError as exc:
        logger.error("Live call failed for disease %s: %s", efo_id, exc)
        stale = get_cached(cache_key, allow_expired=True)
        if stale is not None:
            logger.warning("Falling back to stale cache for disease %s", efo_id)
            return stale
        raise


# --------------------------------------------------------------------------
# Gene -> drug associations
# --------------------------------------------------------------------------

TARGET_DRUGS_QUERY = """
query TargetDrugs($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    id
    approvedSymbol
    drugAndClinicalCandidates {
      count
      rows {
        maxClinicalStage
        drug {
          id
          name
          drugType
          maximumClinicalStage
          parentMolecule { id name }
          crossReferences { source ids }
          mechanismsOfAction {
            rows {
              mechanismOfAction
              targets { id }
            }
          }
        }
      }
    }
  }
}
"""


def get_target_drugs(ensembl_id: str, max_drugs: int = 50, use_cache: bool = True) -> Optional[dict[str, Any]]:
    """Returns the raw `target` payload (id, approvedSymbol, drugAndClinicalCandidates.rows), or None.

    `drugAndClinicalCandidates` takes no pagination arguments on this API version, so
    it always returns the full list; `max_drugs` truncates the rows client-side.
    """
    cache_key = f"target_drugs::{ensembl_id}"

    if use_cache:
        cached = get_cached(cache_key)
        if cached is not None:
            logger.info("Using cached target-drug associations for %s", ensembl_id)
            target = cached
        else:
            target = None
    else:
        target = None

    if target is None:
        try:
            data = execute_query(TARGET_DRUGS_QUERY, {"ensemblId": ensembl_id})
            target = data.get("target")
            if target is not None:
                set_cached(cache_key, target)
        except OpenTargetsAPIError as exc:
            logger.error("Live call failed for target %s: %s", ensembl_id, exc)
            stale = get_cached(cache_key, allow_expired=True)
            if stale is not None:
                logger.warning("Falling back to stale cache for target %s", ensembl_id)
                target = stale
            else:
                raise

    if target and target.get("drugAndClinicalCandidates", {}).get("rows"):
        target = dict(target)
        candidates = dict(target["drugAndClinicalCandidates"])
        candidates["rows"] = candidates["rows"][:max_drugs]
        target["drugAndClinicalCandidates"] = candidates

    return target
