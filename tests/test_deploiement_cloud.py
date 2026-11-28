"""Fichiers de déploiement cloud : manifeste, fenêtres et YAML valide."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "scripts" / "deploy" / "run_pipeline.py"


@pytest.fixture(scope="module")
def module():
    if str(RACINE) not in sys.path:
        sys.path.insert(0, str(RACINE))
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


def test_workflow_installe_le_parseur_et_ingere_les_rib():
    workflow = (RACINE / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    assert "uv sync --locked --extra bgpkit" in workflow
    assert '"rib"' in script
    assert "rib_snapshots" in script


def test_pipeline_par_jour_et_job_parseurs():
    pipeline = (RACINE / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    parsers = (RACINE / ".github" / "workflows" / "parsers.yml").read_text(encoding="utf-8")
    assert "matrix:" in pipeline
    assert "--no-manifest" in pipeline
    assert "finalize_dataset.py" in pipeline
    assert "ABRIP_ETL__SORT_PARTITIONS" in pipeline
    assert "--all-extras" in parsers
    assert "ABRIP_TEST_MRT_PATH" in parsers


def test_manifest_final_depuis_fichiers_distants():
    if str(RACINE) not in sys.path:
        sys.path.insert(0, str(RACINE))
    spec = importlib.util.spec_from_file_location(
        "finalize_dataset", RACINE / "scripts" / "deploy" / "finalize_dataset.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fichiers = [
        "curated/bgp_elements/date=2026-11-20/part-00000.parquet",
        "analytics/events/date=2026-11-20/part-00000.parquet",
        "README.md",
        "manifest.json",
    ]
    assert module.build_manifest(fichiers) == {
        "bgp_elements": ["curated/bgp_elements/date=2026-11-20/part-00000.parquet"],
        "events": ["analytics/events/date=2026-11-20/part-00000.parquet"],
    }


def test_fenetre_par_defaut_et_cle_api_generee():
    workflow = (RACINE / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    blueprint = yaml.safe_load((RACINE / "render.yaml").read_text(encoding="utf-8"))
    variables = {item["key"]: item for item in blueprint["services"][0]["envVars"] if "key" in item}
    assert variables["ABRIP_API__API_KEY"]["generateValue"] is True
    assert "PIPELINE_DAYS" in workflow
    assert "1 day ago" in workflow  # le jour courant est exclu


def test_auto_ne_retombe_pas_sur_le_synthetique(monkeypatch):
    from abrip.etl import mrt_parser

    for name in ("bgpkit", "mrtparse"):
        monkeypatch.setattr(mrt_parser._IMPLEMENTATIONS[name], "available", lambda self: False)
    with pytest.raises(RuntimeError, match="bgpkit"):
        mrt_parser.get_parser("auto")
    assert isinstance(mrt_parser.get_parser("synthetic"), mrt_parser.SyntheticParser)
