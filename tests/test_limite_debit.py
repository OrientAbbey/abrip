"""Limitation de débit : fenêtre glissante et réponses HTTP 429."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abrip.api.main import create_app
from abrip.api.rate_limit import RateLimiter
from abrip.config import get_settings


class Horloge:
    def __init__(self) -> None:
        self.maintenant = 0.0

    def __call__(self) -> float:
        return self.maintenant


def test_fenetre_glissante():
    horloge = Horloge()
    limiteur = RateLimiter(2, window=60.0, clock=horloge)
    assert limiteur.allow("192.0.2.1") == (True, 0)
    assert limiteur.allow("192.0.2.1") == (True, 0)
    autorise, attente = limiteur.allow("192.0.2.1")
    assert not autorise and attente == 60
    horloge.maintenant = 61.0
    assert limiteur.allow("192.0.2.1") == (True, 0)


def test_limite_separee_par_client():
    limiteur = RateLimiter(1, window=60.0)
    assert limiteur.allow("a") == (True, 0)
    assert limiteur.allow("a")[0] is False
    assert limiteur.allow("b") == (True, 0)


@pytest.fixture
def client_limite() -> TestClient:
    settings = get_settings().model_copy(deep=True)
    settings.api.rate_limit_per_minute = 2
    return TestClient(create_app(settings))


def test_troisieme_requete_est_refusee(client_limite):
    for _ in range(2):
        assert client_limite.get("/api/meta/collectors").status_code == 200
    refus = client_limite.get("/api/meta/collectors")
    assert refus.status_code == 429
    assert refus.json()["error"]["code"] == "rate_limited"
    assert int(refus.headers["Retry-After"]) >= 1


def test_supervision_exempte(client_limite):
    for _ in range(6):
        assert client_limite.get("/api/health").status_code == 200
        assert client_limite.get("/api/metrics").status_code == 200


def test_429_compte_dans_les_metriques(client_limite):
    for _ in range(3):
        client_limite.get("/api/meta/collectors")
    body = client_limite.get("/api/metrics").text
    assert 'status="429"' in body


def test_limite_desactivee_par_defaut():
    client = TestClient(create_app())
    for _ in range(4):
        assert client.get("/api/meta/collectors").status_code == 200
