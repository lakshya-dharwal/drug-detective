import json
from unittest.mock import patch

import pytest

from src import entity_resolver


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "entity_cache.json"
    monkeypatch.setattr(entity_resolver, "ENTITY_CACHE_PATH", cache_path)
    yield cache_path


def test_resolve_gene_known_symbol_returns_ensembl_id():
    hits = [
        {"id": "ENSG00000146648", "name": "EGFR", "entity": "target"},
        {"id": "ENSG00000224057", "name": "EGFR-AS1", "entity": "target"},
    ]
    with patch.object(entity_resolver, "search_entities", return_value=hits) as mock_search, patch.object(
        entity_resolver, "get_target_detail", return_value={"id": "ENSG00000146648", "synonyms": [{"label": "HER1"}]}
    ):
        resolved = entity_resolver.resolve_gene("EGFR")

    assert resolved is not None
    assert resolved.ensembl_id == "ENSG00000146648"
    assert resolved.hgnc_symbol == "EGFR"
    assert "HER1" in resolved.synonyms
    mock_search.assert_called_once_with("EGFR", "target")


def test_resolve_gene_by_synonym_matches_same_gene():
    hits = [{"id": "ENSG00000146648", "name": "EGFR", "entity": "target"}]
    with patch.object(entity_resolver, "search_entities", return_value=hits), patch.object(
        entity_resolver, "get_target_detail", return_value=None
    ):
        resolved = entity_resolver.resolve_gene("HER1")  # known EGFR synonym

    assert resolved is not None
    assert resolved.ensembl_id == "ENSG00000146648"


def test_resolve_gene_caches_result_and_avoids_second_api_call():
    hits = [{"id": "ENSG00000146648", "name": "EGFR", "entity": "target"}]
    with patch.object(entity_resolver, "search_entities", return_value=hits) as mock_search, patch.object(
        entity_resolver, "get_target_detail", return_value=None
    ):
        entity_resolver.resolve_gene("EGFR")
        entity_resolver.resolve_gene("egfr")  # different casing, should hit cache

    assert mock_search.call_count == 1


def test_resolve_gene_no_match_returns_none():
    with patch.object(entity_resolver, "search_entities", return_value=[]):
        assert entity_resolver.resolve_gene("not-a-real-gene-xyz") is None


def test_resolve_drug_known_synonym_returns_chembl_id():
    hits = [{"id": "CHEMBL1431", "name": "METFORMIN", "entity": "drug"}]
    detail = {
        "id": "CHEMBL1431",
        "name": "METFORMIN",
        "synonyms": [{"label": "Glucophage", "source": "ChEMBL"}],
        "crossReferences": [{"source": "drugbank", "ids": ["DB00331"]}],
    }
    with patch.object(entity_resolver, "search_entities", return_value=hits), patch.object(
        entity_resolver, "get_drug_detail", return_value=detail
    ):
        resolved = entity_resolver.resolve_drug("Glucophage")

    assert resolved is not None
    assert resolved.chembl_id == "CHEMBL1431"
    assert resolved.drugbank_id == "DB00331"
    assert "Glucophage" in resolved.synonyms


def test_entity_cache_persists_to_disk(isolated_cache):
    hits = [{"id": "CHEMBL1431", "name": "METFORMIN", "entity": "drug"}]
    with patch.object(entity_resolver, "search_entities", return_value=hits), patch.object(
        entity_resolver, "get_drug_detail", return_value=None
    ):
        entity_resolver.resolve_drug("metformin")

    assert isolated_cache.exists()
    with isolated_cache.open() as f:
        cache = json.load(f)
    assert "metformin" in cache["drugs"]
    assert cache["drugs"]["metformin"]["chembl_id"] == "CHEMBL1431"
