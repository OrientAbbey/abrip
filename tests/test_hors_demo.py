"""Mode hors démonstration : comportement quand les sources réelles sont injoignables.

On ne peut pas, dans la suite de tests, joindre RouteViews, RIPE ou IODA : on
vérifie donc ce qui doit rester vrai quand elles échouent — un journal qui dit
quelle URL a échoué et pourquoi, et un code de sortie qui ne prétend pas que
tout va bien.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from typer.testing import CliRunner

from abrip.cli import app
from abrip.config import reload_settings
from abrip.reference import sync


@pytest.fixture
def environnement(monkeypatch, tmp_path):
    """Données isolées ; handlers de journalisation restitués à la fin."""
    monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    racine = logging.getLogger()
    handlers, niveau = list(racine.handlers), racine.level
    yield settings
    for handler in racine.handlers:
        if handler not in handlers:
            handler.close()
    racine.handlers[:] = handlers
    racine.setLevel(niveau)
    monkeypatch.undo()
    reload_settings()


def _connexion_refusee(url, *args, **kwargs):
    raise httpx.ConnectError(
        "[Errno -2] Name or service not known", request=httpx.Request("GET", url)
    )


def _lignes(settings) -> list[dict]:
    texte = settings.log_path.read_text(encoding="utf-8")
    return [json.loads(ligne) for ligne in texte.splitlines() if ligne]


class TestSourcesInjoignables:
    def test_telechargement_echoue_journalise_url_et_type(self, environnement, monkeypatch):
        monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: _connexion_refusee(url))
        resultat = CliRunner().invoke(app, ["reference", "sync"])
        assert resultat.exit_code == 1

        echecs = [
            ligne
            for ligne in _lignes(environnement)
            if ligne["level"] == "WARNING" and "url" in ligne
        ]
        assert echecs, "les échecs de téléchargement doivent porter l'URL demandée"
        assert {ligne["error_type"] for ligne in echecs} == {"ConnectError"}
        assert all(ligne["url"].startswith("http") and ligne["method"] == "GET" for ligne in echecs)
        sources = {ligne["message"] for ligne in echecs}
        assert {"source RIR indisponible", "export RPKI indisponible"} <= sources

    def test_sortie_en_erreur_quand_rien_n_est_synchronise(self, environnement, monkeypatch):
        monkeypatch.setattr(sync, "_download", lambda url, *a, **k: _connexion_refusee(url))
        resultat = CliRunner().invoke(app, ["reference", "sync"])
        assert resultat.exit_code == 1
        assert "Aucun référentiel synchronisé" in resultat.output

    def test_sortie_normale_si_au_moins_une_source_repond(self, environnement, monkeypatch):
        monkeypatch.setattr(sync, "sync_rir", lambda settings, snapshot: 12)
        monkeypatch.setattr(sync, "sync_rpki", lambda settings, snapshot: 0)
        monkeypatch.setattr(sync, "sync_caida", lambda settings, snapshot, filename=None: 0)
        resultat = CliRunner().invoke(app, ["reference", "sync"])
        assert resultat.exit_code == 0


class TestIngestionInjoignable:
    def test_broker_sans_aucun_telechargement_sort_en_erreur(self, environnement, monkeypatch):
        from abrip.ingestion.downloader import Downloader

        monkeypatch.setattr(
            "tenacity.nap.time.sleep", lambda _s: None
        )  # pas d'attente entre essais
        monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: _connexion_refusee(url))
        monkeypatch.setattr(Downloader, "_fetch_one", lambda self, mrt: _connexion_refusee(mrt.url))
        resultat = CliRunner().invoke(
            app,
            [
                "ingest",
                "broker",
                "--from",
                "2026-10-28",
                "--to",
                "2026-10-28",
                "--collectors",
                "rrc19",
            ],
        )
        assert resultat.exit_code == 1
        assert "Aucun fichier téléchargé" in resultat.output

        lignes = _lignes(environnement)
        echecs = [x for x in lignes if x["message"] == "téléchargement échoué"]
        assert echecs and all(x["error_type"] == "ConnectError" for x in echecs)
        assert all(x["url"].startswith("https://data.ris.ripe.net/rrc19/") for x in echecs)
        broker = [x for x in lignes if x["message"].startswith("broker indisponible")]
        assert (
            broker
            and broker[0]["collector"] == "rrc19"
            and broker[0]["error_type"] == "ConnectError"
        )

    def test_dry_run_ne_telecharge_rien_et_sort_normalement(self, environnement, monkeypatch):
        monkeypatch.setattr("tenacity.nap.time.sleep", lambda _s: None)
        monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: _connexion_refusee(url))
        resultat = CliRunner().invoke(
            app,
            [
                "ingest",
                "broker",
                "--from",
                "2026-10-28",
                "--to",
                "2026-10-28",
                "--collectors",
                "rrc19",
                "--dry-run",
            ],
        )
        assert resultat.exit_code == 0
