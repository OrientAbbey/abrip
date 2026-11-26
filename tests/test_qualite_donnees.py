"""Tableau de qualité : contrat d'API et comportement sur installation vierge."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from abrip.api.deps import get_data_access
from abrip.api.main import create_app
from abrip.config import reload_settings
from abrip.storage.catalog import Catalog


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_qualite_avec_donnees_demo(client):
    body = client.get("/api/quality").json()
    assert set(body) == {"generated_at", "sources", "countries", "roa", "silent_collectors"}
    assert body["generated_at"].endswith("Z")
    assert isinstance(body["sources"], list)
    for source in body["sources"]:
        assert set(source) == {"collector", "file_type", "files", "oldest", "newest", "age_days"}
        assert source["files"] >= 0
    assert body["countries"]
    for country in body["countries"]:
        assert set(country) == {"country_iso2", "asns", "african"}
    assert set(body["roa"]) == {"roas", "prefixes"}
    assert body["roa"]["roas"] > 0
    assert isinstance(body["silent_collectors"], list)
    for collector in body["silent_collectors"]:
        assert set(collector) == {"name", "enabled", "last_file_ts", "age_days"}


def test_sources_depuis_le_journal(monkeypatch, tmp_path):
    monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / "journal"))
    settings = reload_settings()
    get_data_access.cache_clear()
    catalog = Catalog(settings.catalog_path)
    catalog.record_ingestion(
        file_url="https://example.test/updates.gz",
        collector="rrc19",
        file_type="updates",
        file_ts=datetime.now(UTC).replace(tzinfo=None),
        status="ok",
    )
    try:
        body = TestClient(create_app()).get("/api/quality").json()
        assert len(body["sources"]) == 1
        source = body["sources"][0]
        assert source["collector"] == "rrc19"
        assert source["file_type"] == "updates"
        assert source["age_days"] == 0
        assert source["newest"].endswith("Z")
    finally:
        monkeypatch.undo()
        reload_settings()
        get_data_access.cache_clear()


def test_qualite_sans_donnees(monkeypatch, tmp_path):
    monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / "vide"))
    reload_settings()
    get_data_access.cache_clear()
    try:
        response = TestClient(create_app()).get("/api/quality")
        assert response.status_code == 200
        body = response.json()
        assert body["sources"] == []
        assert body["countries"] == []
        assert body["roa"] == {"roas": 0, "prefixes": 0}
        assert body["silent_collectors"]
    finally:
        monkeypatch.undo()
        reload_settings()
        get_data_access.cache_clear()
