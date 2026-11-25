from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import polars as pl

from abrip.etl.curate import _curate_rib


class _Catalog:
    def __init__(self) -> None:
        self.partitions: list[tuple[str, str, int]] = []

    def register_partition(
        self, table_name: str, path: str, rows: int, size_bytes: int, run_id: str
    ) -> None:
        self.partitions.append((table_name, path, rows))


def _settings(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        curated_dir=tmp_path / "curated",
        etl=SimpleNamespace(batch_rows=50, compression="zstd"),
    )


def test_curate_rib_ecrit_par_lots_et_remplace_la_partition(tmp_path):
    settings = _settings(tmp_path)
    catalog = _Catalog()

    rows = _curate_rib(settings, catalog, date(2026, 8, 24), "rrc00", "run-1", synthetic=True)
    target = settings.curated_dir / "rib_snapshots" / "date=2026-08-24" / "collector=rrc00"

    assert rows > 50
    fragments = sorted(target.glob("*.parquet"))
    assert len(fragments) > 1  # plusieurs lots, pas un DataFrame complet
    assert pl.read_parquet(fragments).height == rows
    assert catalog.partitions[-1][0] == "rib_snapshots"

    again = _curate_rib(settings, catalog, date(2026, 8, 24), "rrc00", "run-2", synthetic=True)
    assert again == rows
    assert sorted(target.glob("*.parquet")) == fragments  # remplacement, pas ajout
    assert pl.read_parquet(fragments).height == rows
