"""Installation vierge : l'API doit répondre sans jeu de données.

`/api/health` est la route qu'on interroge quand rien ne marche ; elle répond
« degraded » (et non « ok ») tant que les couches bgp_elements et events sont
absentes. `/api/asns/names` répond un dictionnaire vide plutôt qu'une erreur.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abrip.api.deps import get_data_access
from abrip.api.main import create_app
from abrip.config import reload_settings


@pytest.fixture
def client_vierge(monkeypatch, tmp_path):
    monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / "vide"))
    reload_settings()
    get_data_access.cache_clear()  # DataAccess est mémorisé : il pointerait sur d'autres données
    yield TestClient(create_app())
    monkeypatch.undo()
    reload_settings()
    get_data_access.cache_clear()


class TestInstallationVierge:
    def test_health_degraded_sans_donnees(self, client_vierge):
        response = client_vierge.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        absentes = {layer["name"] for layer in body["layers"] if not layer["present"]}
        assert {"bgp_elements", "events"} <= absentes

    def test_noms_d_as_vides_sans_referentiel(self, client_vierge):
        response = client_vierge.get("/api/asns/names")
        assert response.status_code == 200
        assert response.json() == {}

    def test_propagation_vide_sans_donnees(self, client_vierge):
        body = client_vierge.get("/api/prefixes/197.155.64.0%2F22/propagation").json()
        assert body["nodes"] == [] and body["edges"] == []
        rejeu = client_vierge.get("/api/prefixes/197.155.64.0%2F22/propagation/replay").json()
        assert rejeu["frames"] == [] and rejeu["nodes"] == []

    def test_fournisseurs_amont_vides_sans_donnees(self, client_vierge):
        body = client_vierge.get("/api/prefixes/197.155.64.0%2F22/upstreams").json()
        assert body["upstreams"] == [] and body["points"] == []
