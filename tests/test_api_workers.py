"""Options de démarrage multi-processus du service API."""

from __future__ import annotations

import pytest
import uvicorn
from typer.testing import CliRunner

from abrip.cli import app
from abrip.config import reload_settings


@pytest.fixture
def capture(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))
    return captured


def test_un_worker_par_defaut(capture):
    resultat = CliRunner().invoke(app, ["api", "serve"])
    assert resultat.exit_code == 0, resultat.output
    assert capture["workers"] == 1


def test_option_workers(capture):
    resultat = CliRunner().invoke(app, ["api", "serve", "--workers", "4"])
    assert resultat.exit_code == 0, resultat.output
    assert capture["workers"] == 4


def test_workers_depuis_la_configuration(monkeypatch, capture):
    monkeypatch.setenv("ABRIP_API__WORKERS", "3")
    configure = reload_settings()
    try:
        resultat = CliRunner().invoke(app, ["api", "serve"])
        assert resultat.exit_code == 0, resultat.output
        assert capture["workers"] == 3
        assert configure.api.workers == 3
    finally:
        monkeypatch.undo()
        reload_settings()


def test_reload_et_workers_sont_incompatibles(capture):
    resultat = CliRunner().invoke(app, ["api", "serve", "--reload", "--workers", "2"])
    assert resultat.exit_code != 0
    assert "incompatibles" in resultat.output
    assert "workers" not in capture


def test_workers_nuls_sont_refuses(capture):
    resultat = CliRunner().invoke(app, ["api", "serve", "--workers", "0"])
    assert resultat.exit_code != 0
    assert "workers" not in capture
