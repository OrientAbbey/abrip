"""Rétention des couches curées et analytiques : plan, simulation et purge."""

from __future__ import annotations

import json
from datetime import date

import pytest
from typer.testing import CliRunner

from abrip.cli import app
from abrip.config import reload_settings
from abrip.storage.catalog import Catalog
from abrip.storage.retention import execute, plan

AUJOURDHUI = date(2026, 11, 26)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / "data"))
    configured = reload_settings()
    yield configured
    monkeypatch.undo()
    reload_settings()


def partition(root, table: str, day: str, *, size: int = 8):
    path = root / table / f"date={day}"
    path.mkdir(parents=True, exist_ok=True)
    (path / "part-00000.parquet").write_bytes(b"x" * size)
    return path


def test_plan_ne_garde_que_la_fenetre(settings):
    old = partition(settings.curated_dir, "bgp_elements", "2026-08-24")
    limite = partition(settings.curated_dir, "bgp_elements", "2026-08-28")
    analytics = partition(settings.analytics_dir, "events", "2026-08-20")

    targets, cutoff = plan(settings, days=90, today=AUJOURDHUI)

    assert cutoff == date(2026, 8, 28)
    assert {target.path for target in targets} == {old, analytics}
    assert limite not in {target.path for target in targets}


def test_plan_ignore_les_noms_de_dates_invalides(settings):
    base = settings.curated_dir / "bgp_elements"
    (base / "date=hier").mkdir(parents=True)
    (base / "date=2026-8-2").mkdir(parents=True)
    (base / "date=2026-08-2x").mkdir(parents=True)
    assert plan(settings, days=90, today=AUJOURDHUI)[0] == []


def test_plan_refuse_une_rentention_nulle(settings):
    with pytest.raises(ValueError, match="au moins un jour"):
        plan(settings, days=0, today=AUJOURDHUI)


def test_simulation_puis_purge_effective(settings):
    old = partition(settings.curated_dir, "bgp_elements", "2026-08-24", size=16)
    catalog = Catalog(settings.catalog_path)
    catalog.register_partition("bgp_elements", str(old), 10, 16, "run-test")

    targets, _ = plan(settings, days=90, today=AUJOURDHUI)
    assert execute(targets, catalog, dry_run=True) == {
        "directories": 1,
        "files": 1,
        "bytes": 16,
        "catalog_rows": 1,
    }
    assert old.exists()

    assert execute(targets, catalog, dry_run=False) == {
        "directories": 1,
        "files": 1,
        "bytes": 16,
        "catalog_rows": 1,
    }
    assert not old.exists()
    with catalog.connect() as con:
        assert con.execute("SELECT count(*) FROM curated_partitions").fetchone()[0] == 0


def test_commande_purge_simulee_par_defaut(settings):
    old = partition(settings.curated_dir, "bgp_elements", "2026-08-24")
    resultat = CliRunner().invoke(app, ["etl", "purge", "--days", "1"])
    assert resultat.exit_code == 0, resultat.output
    bilan = json.loads(resultat.output)
    assert bilan["applied"] is False
    assert bilan["directories"] == 1
    assert old.exists()


def test_commande_purge_avec_apply(settings):
    old = partition(settings.curated_dir, "bgp_elements", "2026-08-24")
    resultat = CliRunner().invoke(app, ["etl", "purge", "--days", "1", "--apply"])
    assert resultat.exit_code == 0, resultat.output
    assert json.loads(resultat.output)["applied"] is True
    assert not old.exists()


def test_commande_purge_refuse_un_jour_invalide(settings):
    resultat = CliRunner().invoke(app, ["etl", "purge", "--days", "0"])
    assert resultat.exit_code != 0
