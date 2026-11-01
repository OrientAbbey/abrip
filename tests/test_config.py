"""Configuration : cascade défauts → YAML → environnement.

Cette précédence est documentée dans le README et le guide de déploiement.
Un hébergeur ne configure la plateforme que par variables d'environnement : si
le YAML les écrasait, le déploiement serait silencieusement ingouvernable.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from abrip.config import _detect_project_root, get_settings, reload_settings


@pytest.fixture(autouse=True)
def cache_propre():
    """Le cache de configuration est par processus : il faut le vider entre les
    tests, sinon le premier réglage lu gagnerait pour tous les suivants."""
    reload_settings()
    yield
    for name in list(os.environ):
        if name.startswith("ABRIP_"):
            del os.environ[name]
    reload_settings()


class TestPrecedence:
    def test_valeurs_du_yaml_par_defaut(self):
        settings = get_settings()
        assert settings.api.port == 8000
        assert settings.collectors, "les collecteurs viennent de collectors.yaml"

    def test_environnement_prime_sur_yaml(self, monkeypatch):
        monkeypatch.setenv("ABRIP_DATA_DIR", "/tmp/abrip-test")
        settings = reload_settings()
        assert settings.data_dir == Path("/tmp/abrip-test")

    def test_champ_imbrique(self, monkeypatch):
        monkeypatch.setenv("ABRIP_API__PORT", "7860")
        settings = reload_settings()
        assert settings.api.port == 7860
        # Les autres champs du même bloc gardent leur valeur configurée.
        assert settings.api.host == "127.0.0.1"

    def test_absence_de_variable_ne_change_rien(self):
        assert get_settings().api.port == 8000


class TestRacineProjet:
    def test_variable_explicite_respectee(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ABRIP_PROJECT_ROOT", str(tmp_path))
        assert _detect_project_root() == tmp_path.resolve()

    def test_detection_depuis_le_depot(self):
        # Sans variable, la racine doit contenir les fichiers de configuration.
        racine = _detect_project_root()
        assert (racine / "configs").is_dir()


class TestCheminsDerives:
    def test_sous_repertoires_sous_data_dir(self):
        settings = get_settings()
        for chemin in (settings.raw_dir, settings.curated_dir, settings.analytics_dir):
            assert chemin.is_relative_to(settings.data_dir)

    def test_collecteurs_ont_un_role_valide(self):
        roles = {c.role for c in get_settings().collectors}
        assert roles <= {"local", "external"}
        assert "local" in roles, "au moins un collecteur africain doit être défini"


class TestConfigurationCentralisee:
    """Les constantes qui vivaient dans le code sont des réglages (correction 3)."""

    def test_valeurs_par_defaut(self):
        settings = get_settings()
        assert set(settings.ingestion.archive_root) >= {"routeviews", "riperis", "pch"}
        assert settings.ingestion.cadence["routeviews"]["updates"] == 15
        assert settings.ingestion.ris_live_url.startswith("wss://ris-live.ripe.net")
        assert settings.reference.anycast_v4_url.startswith("https://")
        assert settings.reference.anycast_v6_url.startswith("https://")
        assert settings.enrichment.ioda_outage_threshold == 0.5
        assert settings.enrichment.atlas_connected_floor == 0.6

    def test_seuil_moas_anycast_vient_de_detection_yaml(self):
        assert get_settings().detection["detectors"]["moas"]["anycast_overlap_ceiling"] == 0.5

    def test_archive_root_surchargeable_par_variable(self, monkeypatch):
        monkeypatch.setenv(
            "ABRIP_INGESTION__ARCHIVE_ROOT",
            '{"routeviews": "https://miroir.example/rv", "riperis": "https://miroir.example/ris",'
            ' "pch": "https://miroir.example/pch"}',
        )
        settings = reload_settings()
        assert settings.ingestion.archive_root["routeviews"] == "https://miroir.example/rv"

    def test_urls_d_archive_suivent_la_racine_configuree(self, monkeypatch):
        from datetime import datetime

        from abrip.ingestion.broker import build_archive_urls

        monkeypatch.setenv(
            "ABRIP_INGESTION__ARCHIVE_ROOT",
            '{"routeviews": "https://miroir.example/rv", "riperis": "https://miroir.example/ris",'
            ' "pch": "https://miroir.example/pch"}',
        )
        settings = reload_settings()
        collecteur = next(c for c in settings.collectors if c.project == "routeviews")
        debut = datetime(2026, 8, 24, 0, 0)
        fichiers = build_archive_urls(collecteur, debut, debut, settings=settings)
        assert fichiers and all(f.url.startswith("https://miroir.example/rv") for f in fichiers)

    def test_cadence_surchargeable_change_le_nombre_de_fichiers(self, monkeypatch):
        from datetime import datetime, timedelta

        from abrip.ingestion.broker import build_archive_urls

        debut = datetime(2026, 8, 24, 0, 0)
        fin = debut + timedelta(minutes=10)

        defaut = reload_settings()
        collecteur = next(c for c in defaut.collectors if c.project == "routeviews")
        assert (
            len(build_archive_urls(collecteur, debut, fin, settings=defaut)) == 1
        )  # pas de 15 min

        monkeypatch.setenv(
            "ABRIP_INGESTION__CADENCE",
            '{"routeviews": {"rib": 60, "updates": 5}, "riperis": {"rib": 480, "updates": 5},'
            ' "pch": {"rib": 1440, "updates": 1440}}',
        )
        rapide = reload_settings()
        assert len(build_archive_urls(collecteur, debut, fin, settings=rapide)) == 3  # 00:00/05/10

    def test_seuils_d_enrichissement_surchargeables(self, monkeypatch):
        monkeypatch.setenv("ABRIP_ENRICHMENT__IODA_OUTAGE_THRESHOLD", "0.8")
        monkeypatch.setenv("ABRIP_ENRICHMENT__ATLAS_CONNECTED_FLOOR", "0.4")
        settings = reload_settings()
        assert settings.enrichment.ioda_outage_threshold == 0.8
        assert settings.enrichment.atlas_connected_floor == 0.4
        # Les autres réglages du bloc gardent leur valeur.
        assert settings.enrichment.request_timeout == 15.0

    def test_journal_fichier_configurable(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("ABRIP_LOG_MAX_BYTES", "12345")
        monkeypatch.setenv("ABRIP_LOG_BACKUP_COUNT", "2")
        settings = reload_settings()
        assert settings.log_path == tmp_path / "logs" / "abrip.log"
        assert settings.log_max_bytes == 12345 and settings.log_backup_count == 2
