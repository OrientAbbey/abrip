"""Le jeu de démonstration sait dire s'il est seul dans son répertoire de données.

Cas réel : `data/` avait reçu une synchronisation de référentiels, puis la démo. Un objet
route RADB *réel* était alors renvoyé pour 197.155.64.0/22, que la démo ne couvre pas, et
`test_prefixe_sans_objet` échouait sans qu'on voie pourquoi. Le bootstrap écrit désormais
un marqueur et la liste de ses fichiers ; il refuse d'écraser autre chose, et
`abrip demo check` nomme les fichiers étrangers.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from typer.testing import CliRunner

from abrip.cli import app
from abrip.config import reload_settings
from abrip.demo.bootstrap import (
    MARKER,
    DatasetNotDemoError,
    bootstrap,
    dataset_state,
    verify,
)
from abrip.storage.parquet import write_frame


@pytest.fixture
def reglages(monkeypatch, tmp_path):
    def _faire(nom: str):
        monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / nom))
        return reload_settings()

    yield _faire
    monkeypatch.undo()
    reload_settings()


def _objet_route_reel(settings, date: str = "2026-11-02"):
    """Ce que laisserait une vraie synchronisation : un objet RADB pour un préfixe de la démo."""
    frame = pl.DataFrame(
        [{"prefix": "197.155.64.0/22", "asn": 37100, "source": "RADB", "snapshot_date": date}]
    )
    write_frame(frame, settings.reference_dir / "history" / "ref_irr_route" / f"date={date}")


class TestEtatDuRepertoire:
    def test_vide(self, reglages):
        assert dataset_state(reglages("vide"))["state"] == "empty"

    def test_donnees_sans_marqueur(self, reglages):
        settings = reglages("ancien")
        _objet_route_reel(settings)
        etat = dataset_state(settings)
        assert etat["state"] == "unmarked"
        assert any("ref_irr_route" in f for f in etat["foreign"])

    def test_marqueur_corrompu_ne_plante_pas(self, reglages):
        settings = reglages("abime")
        settings.ensure_dirs()
        (settings.data_dir / MARKER).write_text("pas du json", encoding="utf-8")
        _objet_route_reel(settings)
        assert dataset_state(settings)["state"] == "modified"


class TestBootstrapEtProprete:
    def test_cycle_complet(self, reglages):
        settings = reglages("demo")
        bootstrap(settings)

        # 1. Marqueur et liste des fichiers écrits : la démo est reconnue comme telle.
        marqueur = json.loads((settings.data_dir / MARKER).read_text(encoding="utf-8"))
        assert marqueur["base_date"] == "2026-08-24"
        assert any(f.startswith("curated/bgp_elements/") for f in marqueur["files"])
        assert dataset_state(settings) == {"state": "demo", "foreign": [], "missing": []}

        # 2. Relancer sur la démo seule est permis (idempotent).
        bootstrap(settings, days=7)
        assert dataset_state(settings)["state"] == "demo"

        # 3. Un fichier étranger est détecté, nommé, et le bootstrap refuse de passer dessus.
        _objet_route_reel(settings)
        etat = dataset_state(settings)
        assert etat["state"] == "modified"
        assert etat["foreign"] == [
            "reference/history/ref_irr_route/date=2026-11-02/part-00000.parquet"
        ]
        with pytest.raises(DatasetNotDemoError, match="ref_irr_route/date=2026-11-02"):
            bootstrap(settings)

        # 4. --force écrase : la démo redevient seule, et l'objet RADB réel a disparu.
        bootstrap(settings, force=True)
        assert dataset_state(settings)["state"] == "demo"
        historique = settings.reference_dir / "history" / "ref_irr_route"
        prefixes = {
            p
            for f in historique.glob("date=*/*.parquet")
            for p in pl.read_parquet(f)["prefix"].to_list()
        }
        assert "197.155.64.0/22" not in prefixes
        assert verify(settings)["recall"] == 1.0

    def test_donnees_sans_marqueur_refusees_sans_force(self, reglages):
        settings = reglages("legacy")
        _objet_route_reel(settings)
        with pytest.raises(DatasetNotDemoError, match="autre chose"):
            bootstrap(settings, days=2)
        assert dataset_state(settings)["state"] == "unmarked"  # rien n'a été touché
        assert (
            settings.reference_dir
            / "history"
            / "ref_irr_route"
            / "date=2026-11-02"
            / "part-00000.parquet"
        ).exists()

        bootstrap(settings, days=2, force=True)
        assert dataset_state(settings)["state"] == "demo"


class TestCommandes:
    def test_check_sur_repertoire_vide(self, reglages):
        reglages("cli-vide")
        resultat = CliRunner().invoke(app, ["demo", "check"])
        assert resultat.exit_code == 1
        assert '"state": "empty"' in resultat.output

    def test_check_nomme_les_fichiers_etrangers(self, reglages):
        settings = reglages("cli-etranger")
        _objet_route_reel(settings)
        resultat = CliRunner().invoke(app, ["demo", "check"])
        assert resultat.exit_code == 1
        assert "unmarked" in resultat.output and "ref_irr_route/date=2026-11-02" in resultat.output

    def test_bootstrap_refuse_avec_message_et_code_2(self, reglages):
        settings = reglages("cli-refus")
        _objet_route_reel(settings)
        resultat = CliRunner().invoke(app, ["demo", "bootstrap", "--days", "2"])
        assert resultat.exit_code == 2
        assert "--force" in resultat.output and "ABRIP_DATA_DIR" in resultat.output
