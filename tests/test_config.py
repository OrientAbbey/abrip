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
