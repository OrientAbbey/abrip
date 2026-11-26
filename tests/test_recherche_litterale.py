"""Les jokers SQL saisis par l'utilisateur restent des caractères ordinaires."""

from __future__ import annotations

import pytest
from _demo import requires_demo
from fastapi.testclient import TestClient

from abrip.api.main import create_app
from abrip.api.search import escape_like


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_escape_like():
    assert escape_like("102.22.%") == r"102.22.\%"
    assert escape_like("as_") == r"as\_"
    assert escape_like(r"a\b") == r"a\\b"


@requires_demo
class TestRechercheLitteraleAvecDonnees:
    @pytest.mark.parametrize("joker", ["%", "_", "102.%", "102._8.0.0/22"])
    def test_recherche_unifiee_ne_renvoie_rien_sur_un_joker(self, client, joker):
        body = client.get("/api/search", params={"q": joker}).json()
        assert body == []

    @pytest.mark.parametrize("route", ["/api/prefixes", "/api/asns"])
    def test_listes_ne_renvoient_rien_sur_un_joker(self, client, route):
        body = client.get(route, params={"q": "%"}).json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_recherche_litterale_continue_a_fonctionner(self, client):
        hits = client.get("/api/search", params={"q": "102.22.8"}).json()
        assert any(hit["kind"] == "prefix" for hit in hits)
