"""Tables journalières précalculées : de quoi répondre sans relire bgp_elements.

Les endpoints « par AS » (préfixes d'un AS, voisins d'un AS) et la liste des
préfixes n'ont pas de clé de tri qui les aide : sur 50 millions de lignes ils
relisent tout (3 à 6 secondes, voir docs/performances.md). Ce qu'ils calculent
tient pourtant dans de petites tables, une par jour :

``daily_prefix_origin``
    (day, prefix, ip_version, origin_asn, announcements, withdrawals, ribs) —
    une ligne par préfixe et par origine et par jour.
``daily_adjacency``
    (day, ip_version, asn, neighbour) — les AS vus côte à côte sur un chemin
    annoncé ce jour-là, dans les deux sens, comme le calcul direct (la première
    occurrence de chaque AS sur le chemin, comme ``list_position``).

Une partition par jour (``date=AAAA-MM-JJ``) : relancer le calcul sur une plage
remplace les jours de cette plage et laisse les autres.

Le calcul passe par DuckDB (mémoire bornée, débordement sur disque), comme le tri
des partitions. Les API ne s'en servent que si la table couvre tous les jours
demandés et n'est pas plus ancienne que les partitions curées
(:func:`summary_is_current`) ; sinon elles retombent sur le calcul direct, plus
lent mais toujours exact.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

from abrip.config import Settings
from abrip.logging_conf import get_logger
from abrip.storage.catalog import Catalog

log = get_logger(__name__)

PREFIX_ORIGIN = "daily_prefix_origin"
ADJACENCY = "daily_adjacency"
TABLES = (PREFIX_ORIGIN, ADJACENCY)


def _curated_days(settings: Settings) -> dict[str, Path]:
    root = settings.curated_dir / "bgp_elements"
    return {p.name.removeprefix("date="): p for p in sorted(root.glob("date=*")) if p.is_dir()}


def _newest(directory: Path) -> float:
    return max((f.stat().st_mtime for f in directory.rglob("*.parquet")), default=0.0)


def summary_is_current(settings: Settings, name: str, days: Iterable[str] | None = None) -> bool:
    """Vrai si la table couvre les jours demandés (par défaut tous les jours curés)
    et si aucune partition curée n'a été réécrite depuis son calcul."""
    curated = _curated_days(settings)
    wanted = sorted(set(days) & set(curated) if days is not None else curated)
    if not wanted:
        return False
    for day in wanted:
        target = settings.analytics_dir / name / f"date={day}"
        if not target.is_dir() or _newest(target) < _newest(curated[day]):
            return False
    return True


_PREFIX_ORIGIN_SQL = """
    SELECT date_trunc('day', ts) AS day, prefix, any_value(prefix_ip_version) AS ip_version,
           origin_asn,
           count(*) FILTER (WHERE elem_type = 'A') AS announcements,
           count(*) FILTER (WHERE elem_type = 'W') AS withdrawals,
           count(*) FILTER (WHERE elem_type = 'R') AS ribs
    FROM read_parquet([{files}], union_by_name = true)
    GROUP BY date_trunc('day', ts), prefix, origin_asn
    ORDER BY prefix, origin_asn
"""


def adjacency_sql(source: str, where: str = "") -> str:
    """Requête des adjacences AS-AS par jour, sur n'importe quelle source de lignes.

    Chemins distincts d'abord (très peu par rapport aux lignes), puis dépliés.
    `source` : une expression de table (``read_parquet(…)`` ou une table nommée) ;
    `where` : conditions supplémentaires, commençant par « AND »."""
    return f"""
    WITH paths AS (
        SELECT DISTINCT date_trunc('day', ts) AS day, prefix_ip_version AS ip_version,
               as_path_dedup AS p
        FROM {source}
        WHERE elem_type = 'A' AND len(as_path_dedup) >= 2 {where}
    ),
    firsts AS (
        SELECT day, ip_version, p, i
        FROM (SELECT day, ip_version, p, unnest(range(1, len(p) + 1)) AS i FROM paths)
        WHERE list_position(p, p[i]) = i
    )
    SELECT DISTINCT day, ip_version, p[i] AS asn, p[i - 1] AS neighbour FROM firsts WHERE i > 1
    UNION
    SELECT DISTINCT day, ip_version, p[i] AS asn, p[i + 1] AS neighbour
    FROM firsts WHERE i < len(p)
    ORDER BY asn, neighbour
"""


def _write_day(settings: Settings, name: str, sql: str, day: str, files: list[Path]) -> int:
    import duckdb

    target = settings.analytics_dir / name / f"date={day}"
    spill = settings.analytics_dir / name / f".tmp-{day}"
    tmp = settings.analytics_dir / name / f".{day}.parquet.tmp"
    target.parent.mkdir(parents=True, exist_ok=True)
    spill.mkdir(exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit = ?", [settings.etl.sort_memory_limit])
        con.execute("SET temp_directory = ?", [str(spill)])
        con.execute("SET threads = 1")
        listing = ", ".join(f"'{f.as_posix()}'" for f in files)
        con.execute(
            f"COPY ({sql.format(files=listing)}) TO '{tmp.as_posix()}' "
            f"(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        counted = con.execute(f"SELECT count(*) FROM read_parquet('{tmp.as_posix()}')").fetchone()
        rows = int(counted[0]) if counted else 0
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        con.close()
        shutil.rmtree(spill, ignore_errors=True)
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    tmp.replace(target / "part-00000.parquet")
    return rows


def compute_daily_summaries(
    settings: Settings,
    catalog: Catalog | None,
    start: date,
    end: date,
    run_id: str | None = None,
) -> dict[str, int]:
    """(Re)calcule les deux tables pour chaque jour curé de [start, end]."""
    curated = _curated_days(settings)
    totals = {name: 0 for name in TABLES}
    day = start
    while day <= end:
        key = day.isoformat()
        files = sorted(curated[key].glob("collector=*/*.parquet")) if key in curated else []
        if files:
            for name, sql in (
                (PREFIX_ORIGIN, _PREFIX_ORIGIN_SQL),
                (ADJACENCY, adjacency_sql("read_parquet([{files}], union_by_name = true)")),
            ):
                rows = _write_day(settings, name, sql, key, files)
                totals[name] += rows
                if catalog is not None and run_id:
                    target = settings.analytics_dir / name / f"date={key}"
                    size = sum(f.stat().st_size for f in target.glob("*.parquet"))
                    catalog.register_partition(name, str(target), rows, size, run_id)
        day += timedelta(days=1)
    log.info("tables journalières calculées", extra=totals)
    return totals
