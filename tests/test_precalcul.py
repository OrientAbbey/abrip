"""Précalcul des préfixes par AS et préchauffage du cache de la vue d'ensemble."""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from abrip.analytics.precompute import ASN_PREFIX_STATS, build_asn_prefix_stats, stats_is_current
from abrip.api.deps import DataAccess, get_data_access
from abrip.api.main import create_app
from abrip.api.routers import system
from abrip.api.schemas import Overview
from abrip.cli import app
from abrip.config import get_settings, reload_settings
from abrip.storage.catalog import Catalog

ASN = 37100


@pytest.fixture
def copie(tmp_path, monkeypatch):
    source = get_settings().data_dir
    for name in ("curated", "analytics"):
        shutil.copytree(source / name, tmp_path / name, dirs_exist_ok=True)
    monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path))
    configure = reload_settings()
    get_data_access.cache_clear()
    yield configure
    monkeypatch.undo()
    reload_settings()
    get_data_access.cache_clear()


def _prefixes(data: DataAccess, table: str) -> list[tuple[object, ...]]:
    if table == ASN_PREFIX_STATS:
        sql = f"SELECT prefix, updates, first_seen, last_seen, peers FROM {data.table(table)} WHERE asn = ? ORDER BY 1"
    else:
        sql = f"""SELECT prefix, count(*) AS updates, min(ts) AS first_seen, max(ts) AS last_seen,
                         count(DISTINCT peer_asn) AS peers
                  FROM {data.table(table)} WHERE origin_asn = ? AND elem_type = 'A'
                  GROUP BY 1 ORDER BY 1"""
    return [tuple(row.values()) for row in data.query(sql, [ASN])]


def test_precalcul_identique_au_calcul_direct(copie):
    data = DataAccess(copie)
    avant = _prefixes(data, "bgp_elements")
    assert avant
    assert not stats_is_current(copie)

    catalogue = Catalog(copie.catalog_path)
    assert build_asn_prefix_stats(copie, catalogue)["rows"] > 0
    assert stats_is_current(copie)
    assert _prefixes(data, ASN_PREFIX_STATS) == avant


def test_fiche_as_avant_et_apres_precalcul(copie):
    avant = TestClient(create_app(copie)).get(f"/api/asns/{ASN}").json()
    catalogue = Catalog(copie.catalog_path)
    build_asn_prefix_stats(copie, catalogue)
    apres = TestClient(create_app(copie)).get(f"/api/asns/{ASN}").json()
    assert avant["prefixes"] == apres["prefixes"]


def test_commande_analytics_precompute(copie):
    resultat = CliRunner().invoke(app, ["analytics", "precompute"])
    assert resultat.exit_code == 0, resultat.output
    assert '"rows"' in resultat.output
    assert stats_is_current(copie)


def test_prewarm_remplit_le_cache(copie, monkeypatch):
    appels: list[int] = []
    faux = Overview(
        window_from=None,
        window_to=None,
        prefixes_tracked=0,
        asns_tracked=0,
        countries_tracked=0,
        median_visibility=None,
        events_by_severity={},
        events_by_detector={},
        top_unstable_prefixes=[],
    )

    def _faux_overview(data: DataAccess, days: int) -> Overview:
        appels.append(days)
        return faux

    monkeypatch.setattr(system, "_build_overview", _faux_overview)
    copie.api.prewarm = True
    create_app(copie)
    assert appels == [7]
