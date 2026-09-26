"""Diff d'un référentiel historisé entre deux dates.

``reference/sync.py`` écrit un instantané daté et immuable de chaque
référentiel sous ``reference/history/<table>/date=YYYY-MM-DD/`` (voir sa
docstring). Ce module compare une plage de ces instantanés pour qualifier
chaque entité (relation d'AS, ROA, objet IRR...) comme :

- ``new`` — absente au premier jour de la plage, présente au dernier ;
- ``left`` — présente au premier jour, absente au dernier ;
- ``unstable`` — au moins une réapparition après une absence intermédiaire
  (un aller-retour présent → absent → présent suffit) ;
- ``stable`` — présente à chaque instantané de la plage.

Une entité présente seulement au milieu de la plage (absente aux deux
bornes, sans réapparition) n'entre dans aucune des trois premières classes
au sens strict ; elle est rangée dans ``unstable``, le classement le plus
proche du réel (ni stable, ni simplement en train d'apparaître ou de
disparaître).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import polars as pl

from abrip.storage.parquet import iter_partition_dates, read_partitions


def snapshot_dates(reference_dir: Path, table: str, start: str, end: str) -> list[str]:
    """Dates d'instantané disponibles pour ``table`` dans ``[start, end]``."""
    return sorted(
        d for d in iter_partition_dates(reference_dir / "history", table) if start <= d <= end
    )


def diff_entities(
    reference_dir: Path,
    table: str,
    key_columns: Sequence[str],
    start: str,
    end: str,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Une ligne par entité distincte vue sur ``[start, end]``.

    Chaque ligne porte les colonnes de ``key_columns``, plus ``change``
    (``new``/``left``/``unstable``/``stable``), ``first_seen`` et
    ``last_seen`` (dates d'instantané, pas d'horodatages). ``filters``
    restreint aux lignes égales à la valeur donnée pour chaque colonne
    (ex. ``{"prefix": "197.155.64.0/22"}``), appliqué avant le diff plutôt
    qu'après pour ne jamais charger plus que nécessaire.
    """
    dates = snapshot_dates(reference_dir, table, start, end)
    if not dates:
        return []

    scan = read_partitions(reference_dir / "history", table, date_from=dates[0], date_to=dates[-1])
    for column, value in (filters or {}).items():
        scan = scan.filter(pl.col(column) == value)
    frame = scan.select([*key_columns, "snapshot_date"]).unique().collect()
    if frame.is_empty():
        return []

    grouped = frame.group_by(list(key_columns)).agg(pl.col("snapshot_date").sort().alias("seen_on"))

    first_day, last_day = dates[0], dates[-1]
    out: list[dict[str, Any]] = []
    for row in grouped.iter_rows(named=True):
        seen: list[str] = row["seen_on"]
        change = classify_presence(seen, dates, first_day, last_day)
        key = {k: row[k] for k in key_columns}
        out.append({**key, "change": change, "first_seen": seen[0], "last_seen": seen[-1]})
    return out


def classify_presence(seen: list[str], all_dates: list[str], first_day: str, last_day: str) -> str:
    """``new``/``left``/``unstable``/``stable`` à partir des jours de présence.

    Générique : ``all_dates`` n'a pas besoin de venir d'un instantané de
    référentiel — la Phase 1 du point 6 (25/09/2026) l'applique aussi aux
    préfixes observés dans les données BGP curées.
    """
    if len(seen) == len(all_dates):
        return "stable"
    if count_reappearances(seen, all_dates) >= 1:
        return "unstable"
    present_start, present_end = first_day in seen, last_day in seen
    if not present_start and present_end:
        return "new"
    if present_start and not present_end:
        return "left"
    return "unstable"  # apparue puis disparue entièrement dans la fenêtre


def count_reappearances(seen: list[str], all_dates: list[str]) -> int:
    """Nombre de fois où l'entité redevient présente après une absence qui
    suivait une présence — 0 si elle n'a jamais disparu puis réapparu."""
    seen_set = set(seen)
    count = 0
    was_present = False
    gap_since_present = False
    for day in all_dates:
        present = day in seen_set
        if was_present and not present:
            gap_since_present = True
        elif gap_since_present and present:
            count += 1
            gap_since_present = False
        was_present = present
    return count
