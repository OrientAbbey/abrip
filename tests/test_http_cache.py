"""ETag, Cache-Control et compression des réponses JSON."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abrip.api.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


class TestCacheJson:
    def test_etag_et_cache_control(self, client):
        response = client.get("/api/meta/collectors")
        assert response.status_code == 200
        assert response.headers["etag"].startswith('W/"')
        assert response.headers["cache-control"] == "private, no-cache"
        assert "accept-encoding" in response.headers["vary"].lower()

    def test_requete_conditionnelle_renvoie_304(self, client):
        first = client.get("/api/meta/collectors")
        etag = first.headers["etag"]
        second = client.get("/api/meta/collectors", headers={"if-none-match": etag})
        assert second.status_code == 304
        assert second.content == b""
        assert second.headers["etag"] == etag
        assert second.headers["cache-control"] == first.headers["cache-control"]

    def test_if_none_match_etoile(self, client):
        response = client.get("/api/meta/collectors", headers={"if-none-match": "*"})
        assert response.status_code == 304

    def test_sante_jamais_cachee(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "etag" not in response.headers

    def test_etag_suit_les_parametres(self, client):
        first = client.get("/api/asns", params={"limit": 1})
        second = client.get("/api/asns", params={"limit": 2})
        assert first.status_code == second.status_code == 200
        assert first.headers["etag"] != second.headers["etag"]

    def test_erreurs_non_cachees(self, client):
        response = client.get("/api/inconnue")
        assert response.status_code == 404
        assert "etag" not in response.headers
        assert "cache-control" not in response.headers


class TestCompression:
    def test_grosse_reponse_compressee(self, client):
        response = client.get("/api/openapi.json", headers={"accept-encoding": "gzip"})
        assert response.status_code == 200
        assert response.headers["content-encoding"] == "gzip"

    def test_petite_reponse_non_compressee(self, client):
        response = client.get(
            "/api/search", params={"q": "zzz-aucun-resultat"}, headers={"accept-encoding": "gzip"}
        )
        assert response.status_code == 200
        assert "content-encoding" not in response.headers

    def test_sans_negociation_pas_de_compression(self, client):
        response = client.get("/api/openapi.json", headers={"accept-encoding": "identity"})
        assert response.status_code == 200
        assert "content-encoding" not in response.headers
