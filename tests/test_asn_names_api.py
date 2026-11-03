"""GET /api/asns/names : table ASN -> nom, chargée une fois côté client."""

from __future__ import annotations

import pytest
from _demo import requires_demo
from fastapi.testclient import TestClient

from abrip.api.main import create_app

pytestmark = requires_demo


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


class TestNomsDAs:
    def test_table_asn_vers_nom(self, client):
        response = client.get("/api/asns/names")
        assert response.status_code == 200
        names = response.json()
        assert names, "le jeu de démonstration fournit des noms d'AS"
        # Clés en chaîne (JSON), valeurs en chaîne non vide.
        assert all(isinstance(k, str) and k.isdigit() for k in names)
        assert all(isinstance(v, str) and v for v in names.values())

    def test_nom_court_prefere_au_nom_d_organisation(self, client):
        names = client.get("/api/asns/names").json()
        # `asn_name` (CAIDA aut_name) l'emporte sur `org_name` quand il existe.
        assert names["174"] == "COGENT-174"
        assert names["37100"] == "LITTORAL-TELECOM"
