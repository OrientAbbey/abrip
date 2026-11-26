"""Politique de rétention des couches curées et analytiques.

La couche brute est purgée séparément (`abrip ingest purge`, 30 jours par
défaut). Les Parquet curés et analytiques vivent plus longtemps
(`etl.retention_days`, 90 jours par défaut) : ils sont la mémoire exploitable de
la plateforme. Leur purge est **explicite** et simulée par défaut.

Seuls les sous-répertoires `date=AAAA-MM-JJ` sont candidats. Leur nom est
validé avant suppression et les liens symboliques sont ignorés : aucun chemin
configuré ni aucune partition récente ne peut être effacé par une faute de
frappe ou un répertoire parasite.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from abrip.config import Settings
from abrip.storage.catalog import Catalog

DATE_DIR = re.compile(r"date=\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class PurgeTarget:
    layer: str
    table: str
    path: Path
    day: date
    files: int
    bytes: int


def plan(
    settings: Settings, *, days: int | None = None, today: date | None = None
) -> tuple[list[PurgeTarget], date]:
    """Liste les partitions plus anciennes que la fenêtre de rétention."""
    retention = settings.etl.retention_days if days is None else days
    if retention < 1:
        raise ValueError("La rétention doit être d'au moins un jour.")
    reference = today or datetime.now(UTC).date()
    cutoff = reference - timedelta(days=retention)
    targets: list[PurgeTarget] = []

    for layer, root in (
        ("curated", settings.curated_dir),
        ("analytics", settings.analytics_dir),
    ):
        if not root.is_dir():
            continue
        for table_dir in sorted(root.iterdir()):
            if not table_dir.is_dir() or table_dir.is_symlink():
                continue
            for candidate in sorted(table_dir.iterdir()):
                if not candidate.is_dir() or candidate.is_symlink():
                    continue
                if not DATE_DIR.fullmatch(candidate.name):
                    continue
                day = date.fromisoformat(candidate.name.removeprefix("date="))
                if day >= cutoff:
                    continue
                files = [path for path in candidate.rglob("*") if path.is_file()]
                targets.append(
                    PurgeTarget(
                        layer=layer,
                        table=table_dir.name,
                        path=candidate,
                        day=day,
                        files=len(files),
                        bytes=sum(path.stat().st_size for path in files),
                    )
                )
    return targets, cutoff


def _prune_catalog(catalog: Catalog, paths: list[Path], *, apply: bool) -> int:
    """Retire du catalogue les partitions qui n'existent plus sur le disque."""
    if not paths:
        return 0
    with catalog.connect() as con:
        rows = con.execute("SELECT partition_key, path FROM curated_partitions").fetchall()
        keys = [
            key
            for key, stored in rows
            if any(stored == str(path) or stored.startswith(f"{path}{os.sep}") for path in paths)
        ]
        if keys and apply:
            for start in range(0, len(keys), 100):
                chunk = keys[start : start + 100]
                con.execute(
                    f"DELETE FROM curated_partitions WHERE partition_key IN ({','.join('?' * len(chunk))})",
                    chunk,
                )
    return len(keys)


def execute(
    targets: Iterable[PurgeTarget], catalog: Catalog | None, *, dry_run: bool = True
) -> dict[str, int]:
    """Applique (ou simule) la purge et retourne un bilan comptable."""
    selected = list(targets)
    catalog_rows = (
        _prune_catalog(catalog, [target.path for target in selected], apply=not dry_run)
        if catalog is not None
        else 0
    )
    if dry_run:
        return {
            "directories": len(selected),
            "files": sum(target.files for target in selected),
            "bytes": sum(target.bytes for target in selected),
            "catalog_rows": catalog_rows,
        }
    for target in selected:
        shutil.rmtree(target.path)
    return {
        "directories": len(selected),
        "files": sum(target.files for target in selected),
        "bytes": sum(target.bytes for target in selected),
        "catalog_rows": catalog_rows,
    }
