"""Écriture et lecture Parquet à mémoire bornée.

Le principe structurant : on n'assemble jamais un DataFrame complet en mémoire.
``ParquetBatchWriter`` accumule des enregistrements et écrit un fragment dès que
le seuil de lignes est atteint, puis libère le tampon.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, cast

import polars as pl

from abrip.logging_conf import get_logger

log = get_logger(__name__)


class ParquetBatchWriter:
    """Écrit un flux d'enregistrements en fragments Parquet compressés.

    Exemple :
        with ParquetBatchWriter(path, schema, batch_rows=500_000) as writer:
            for record in stream:
                writer.add(record)
    """

    def __init__(
        self,
        directory: Path,
        schema: dict[str, Any],
        *,
        batch_rows: int = 500_000,
        compression: str = "zstd",
        prefix: str = "part",
    ) -> None:
        self.directory = directory
        self.schema = schema
        self.batch_rows = batch_rows
        self.compression = compression
        self.prefix = prefix
        self._buffer: list[dict[str, Any]] = []
        self._fragment = 0
        self.rows_written = 0

    def __enter__(self) -> ParquetBatchWriter:
        self.directory.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is None:
            self.flush()

    def add(self, record: dict[str, Any]) -> None:
        self._buffer.append(record)
        if len(self._buffer) >= self.batch_rows:
            self.flush()

    def extend(self, records: Iterable[dict[str, Any]]) -> None:
        for record in records:
            self.add(record)

    def flush(self) -> None:
        if not self._buffer:
            return
        frame = pl.DataFrame(self._buffer, schema=self.schema, strict=False)
        target = self.directory / f"{self.prefix}-{self._fragment:05d}.parquet"
        frame.write_parquet(target, compression=cast(Any, self.compression), statistics=True)
        self.rows_written += frame.height
        self._fragment += 1
        self._buffer.clear()
        del frame


def write_frame(
    frame: pl.DataFrame,
    directory: Path,
    *,
    filename: str = "part-00000.parquet",
    compression: str = "zstd",
    replace: bool = True,
) -> Path:
    """Écrit une partition de façon atomique : écriture temporaire puis renommage.

    Garantit l'idempotence : une partition retraitée remplace l'ancienne plutôt
    que de s'y ajouter.
    """
    directory.mkdir(parents=True, exist_ok=True)
    if replace:
        for stale in directory.glob("*.parquet"):
            stale.unlink()
    tmp = directory / f".{filename}.tmp"
    frame.write_parquet(tmp, compression=cast(Any, compression), statistics=True)
    final = directory / filename
    tmp.replace(final)
    return final


def partition_path(
    root: Path, table: str, *, date: str | None = None, collector: str | None = None, **extra: str
) -> Path:
    path = root / table
    if date:
        path = path / f"date={date}"
    if collector:
        path = path / f"collector={collector}"
    for key, value in extra.items():
        path = path / f"{key}={value}"
    return path


def read_partitions(
    root: Path,
    table: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    collectors: list[str] | None = None,
) -> pl.LazyFrame:
    """Retourne un LazyFrame sur les partitions correspondantes.

    Le filtre de date est appliqué sur les *chemins* avant lecture : c'est ce qui
    évite d'ouvrir des fichiers inutiles.
    """
    base = root / table
    if not base.exists():
        raise FileNotFoundError(
            f"Table absente : {base}. Lancer l'étape qui la produit avant d'interroger."
        )
    paths = _select_paths(base, date_from, date_to, collectors)
    if not paths:
        raise FileNotFoundError(f"Aucune partition dans {base} pour le filtre demandé.")
    return pl.scan_parquet([str(p) for p in paths])


def _select_paths(
    base: Path, date_from: str | None, date_to: str | None, collectors: list[str] | None
) -> list[Path]:
    selected: list[Path] = []
    for date_dir in sorted(base.glob("date=*")):
        day = date_dir.name.split("=", 1)[1]
        if date_from and day < date_from:
            continue
        if date_to and day > date_to:
            continue
        sub = list(date_dir.glob("collector=*"))
        if not sub:
            selected.extend(date_dir.rglob("*.parquet"))
            continue
        for coll_dir in sub:
            name = coll_dir.name.split("=", 1)[1]
            if collectors and name not in collectors:
                continue
            selected.extend(coll_dir.rglob("*.parquet"))
    if not selected and not list(base.glob("date=*")):
        selected = list(base.rglob("*.parquet"))
    return selected


def iter_partition_dates(root: Path, table: str) -> Iterator[str]:
    base = root / table
    if not base.exists():
        return
    for date_dir in sorted(base.glob("date=*")):
        yield date_dir.name.split("=", 1)[1]


def drop_partition(root: Path, table: str, date: str, collector: str | None = None) -> None:
    path = partition_path(root, table, date=date, collector=collector)
    if path.exists():
        shutil.rmtree(path)
