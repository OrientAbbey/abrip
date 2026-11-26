"""Durcissement HTTP : en-têtes de réponse et clé API comparée en temps constant."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abrip.api import deps
from abrip.api.deps import api_key_matches
from abrip.api.main import create_app
from abrip.config import get_settings


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_api_key_matches_sans_cle_configuree():
    assert api_key_matches(None, None)
    assert api_key_matches(None, "nimportequoi")


def test_api_key_matches_avec_cle():
    assert api_key_matches("secret", "secret")
    assert not api_key_matches("secret", None)
    assert not api_key_matches("secret", "secret!")
    assert not api_key_matches("secret", "autre")


class TestEnTetesDeSecurite:
    # `/` n'est pas testé ici : il ne répond que si `frontend/dist` est compilé,
    # ce qui n'est pas le cas du job Python en CI. Le middleware est global,
    # donc une réponse d'API et une réponse d'erreur suffisent à le couvrir.
    @pytest.mark.parametrize(("path", "status"), [("/api/health", 200), ("/api/inconnue", 404)])
    def test_en_tetes_present_sur_api_et_erreurs(self, client, path, status):
        response = client.get(path)
        assert response.status_code == status
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "camera=()" in response.headers["Permissions-Policy"]


class TestCSP:
    @pytest.fixture
    def client_avec_spa(self, tmp_path):
        (tmp_path / "index.html").write_text("<!doctype html><html><body></body></html>", "utf-8")
        settings = get_settings().model_copy(deep=True)
        settings.api.static_dir = str(tmp_path)
        return TestClient(create_app(settings))

    def test_csp_sur_le_html_de_la_spa(self, client_avec_spa):
        response = client_avec_spa.get("/")
        assert response.status_code == 200
        csp = response.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "img-src 'self' data: blob:" in csp
        assert "object-src 'none'" in csp

    def test_pas_de_csp_sur_l_api(self, client_avec_spa):
        response = client_avec_spa.get("/api/health")
        assert response.status_code == 200
        assert "content-security-policy" not in response.headers


class TestCleApi:
    @pytest.fixture
    def protege(self, monkeypatch):
        settings = get_settings().model_copy(deep=True)
        settings.api.api_key = "cle-de-test"
        monkeypatch.setattr(deps, "get_settings", lambda: settings)
        return TestClient(create_app(settings))

    def test_sans_cle_est_refuse(self, protege):
        assert protege.get("/api/health").status_code == 401

    def test_mauvaise_cle_est_refusee(self, protege):
        response = protege.get("/api/health", headers={"x-api-key": "mauvaise"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

    def test_bonne_cle_est_acceptee(self, protege):
        assert protege.get("/api/health", headers={"x-api-key": "cle-de-test"}).status_code == 200

    def test_documentation_est_aussi_protegee(self, protege):
        assert protege.get("/api/openapi.json").status_code == 401
        assert (
            protege.get("/api/openapi.json", headers={"x-api-key": "cle-de-test"}).status_code
            == 200
        )
