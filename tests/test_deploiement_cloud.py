"""Fichiers de déploiement cloud : manifeste, fenêtres et YAML valide."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "scripts" / "deploy" / "run_pipeline.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("run_pipeline", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_jours_inclusifs(module):
    assert list(module.jours(date(2026, 11, 20), date(2026, 11, 22))) == [
        date(2026, 11, 20),
        date(2026, 11, 21),
        date(2026, 11, 22),
    ]


def test_manifest_cache_les_tables_sans_le_brut(module, tmp_path):
    for relative in (
        "curated/bgp_elements/date=2026-11-20/part-00000.parquet",
        "analytics/metric_churn_prefix/date=2026-11-20/part-00000.parquet",
        "reference/ref_asn/part-00000.parquet",
        "raw/updates/date=2026-11-20/mrt.gz",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    tables = module.ecrire_manifest(tmp_path)

    assert set(tables) == {"bgp_elements", "metric_churn_prefix", "ref_asn"}
    assert tables["bgp_elements"] == ["curated/bgp_elements/date=2026-11-20/part-00000.parquet"]
    manifeste = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert "raw/updates" not in manifeste


def test_carte_dataset_attribue_les_sources(module, tmp_path):
    module.ecrire_carte_dataset(tmp_path)
    carte = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert carte.startswith("---\nlicense: other")
    assert "RouteViews" in carte and "CC BY 4.0" in carte
    assert "RIPE NCC RIS" in carte and "CAIDA" in carte
    assert "Acceptable Use Agreement" in carte


@pytest.mark.parametrize(
    "fichier",
    [
        ".github/workflows/pipeline.yml",
        ".github/workflows/keep-awake.yml",
        "render.yaml",
        "configs/allowlist.yaml",
        "configs/detection.yaml",
    ],
)
def test_yaml_valide(fichier):
    contenu = yaml.safe_load((RACINE / fichier).read_text(encoding="utf-8"))
    assert isinstance(contenu, dict) and contenu


def test_start_script_execute_l_api():
    contenu = (RACINE / "scripts" / "deploy" / "start.sh").read_text(encoding="utf-8")
    assert contenu.startswith("#!/bin/sh")
    assert "abrip api serve --host 0.0.0.0" in contenu
