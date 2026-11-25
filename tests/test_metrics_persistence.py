from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import polars as pl

from abrip.analytics.metrics import _persist
from abrip.api.deps import TABLES


class _Catalog:
    def __init__(self) -> None:
        self.partitions: list[tuple[str, str, int, int, str]] = []

    def register_partition(
        self, table_name: str, path: str, rows: int, size_bytes: int, run_id: str
    ) -> None:
        self.partitions.append((table_name, path, rows, size_bytes, run_id))


def _settings(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(analytics_dir=tmp_path / "analytics")


def _metric(day: int, value: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "window_start": [datetime(2026, 8, day)],
            "origin_asn": [37100],
            "observations": [value],
        }
    )


def test_persist_conserve_les_autres_jours_lors_d_un_recalcul(tmp_path):
    settings = _settings(tmp_path)
    catalog = _Catalog()

    assert (
        _persist(
            settings,
            catalog,
            "metric_upstream",
            pl.concat([_metric(24, 4), _metric(25, 8)]),
            "run-1",
        )
        == 2
    )
    assert _persist(settings, catalog, "metric_upstream", _metric(24, 7), "run-2") == 1

    files = sorted((settings.analytics_dir / "metric_upstream").glob("date=*/*.parquet"))
    saved = pl.read_parquet(files).sort("window_start")
    assert saved.get_column("observations").to_list() == [7, 8]
    assert [partition[1].split("date=")[-1] for partition in catalog.partitions[-1:]] == [
        "2026-08-24"
    ]


def test_persist_migre_les_anciennes_metriques_a_plat(tmp_path):
    settings = _settings(tmp_path)
    catalog = _Catalog()
    legacy = settings.analytics_dir / "metric_upstream"
    legacy.mkdir(parents=True)
    pl.concat([_metric(24, 4), _metric(25, 8)]).write_parquet(legacy / "part-00000.parquet")

    _persist(settings, catalog, "metric_upstream", _metric(26, 12), "run-3")

    assert not list(legacy.glob("*.parquet"))
    saved = pl.read_parquet(sorted(legacy.glob("date=*/*.parquet"))).sort("window_start")
    assert saved.get_column("observations").to_list() == [4, 8, 12]


def test_api_lit_les_metriques_dans_les_partitions_journalieres():
    assert TABLES["metric_upstream"] == ("analytics", "metric_upstream/**/*.parquet")
