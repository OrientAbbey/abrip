"""Précalcul de la table des préfixes par AS.

La fiche d'un AS demande aujourd'hui un parcours de `bgp_elements` regroupé par
préfixe (1,1 s à 50 M de lignes). Une seule passe produit une table
`(asn, prefix)` réutilisable par toutes les fiches ; l'API retombe sur le calcul
direct si la table est absente ou périmée.
"""

from __future__ import annotations

import shutil

from abrip.config import Settings
from abrip.logging_conf import get_logger
from abrip.storage.catalog import Catalog, RunContext

log = get_logger(__name__)

ASN_PREFIX_STATS = "asn_prefix_stats"

_SQL = """
COPY (
    SELECT origin_asn AS asn, prefix,
           count(*) AS updates,
           min(ts) AS first_seen,
           max(ts) AS last_seen,
           count(DISTINCT peer_asn) AS peers
    FROM read_parquet([{source}], union_by_name = true)
    WHERE elem_type = 'A' AND origin_asn IS NOT NULL
    GROUP BY 1, 2
) TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)
"""


def _newest_source(settings: Settings) -> float:
    root = settings.curated_dir / "bgp_elements"
    return max(
        (path.stat().st_mtime for path in root.glob("date=*/*/*.parquet") if path.is_file()),
        default=0.0,
    )


def stats_is_current(settings: Settings) -> bool:
    """Vrai si le précalcul couvre toutes les partitions curées présentes."""
    target = settings.analytics_dir / ASN_PREFIX_STATS / "part-00000.parquet"
    return target.exists() and target.stat().st_mtime >= _newest_source(settings)


def build_asn_prefix_stats(settings: Settings, catalog: Catalog) -> dict[str, int]:
    """Écrit la table en une passe, atomiquement ; idempotent."""
    import duckdb

    source_root = settings.curated_dir / "bgp_elements"
    sources = sorted(source_root.rglob("*.parquet"))
    if not sources:
        return {"rows": 0}
    directory = settings.analytics_dir / ASN_PREFIX_STATS
    directory.mkdir(parents=True, exist_ok=True)
    spill = directory / ".tmp-spill"
    spill.mkdir(exist_ok=True)
    tmp = directory / ".part-00000.tmp.parquet"

    with RunContext(catalog, "analytics.asn_prefix_stats"):
        con = duckdb.connect()
        try:
            con.execute("SET memory_limit = ?", [settings.etl.sort_memory_limit])
            con.execute("SET temp_directory = ?", [str(spill)])
            con.execute("SET threads = 1")
            source = ", ".join(f"'{path.as_posix()}'" for path in sources)
            con.execute(_SQL.format(source=source, target=tmp.as_posix()))
            row = con.execute(f"SELECT count(*) FROM read_parquet('{tmp.as_posix()}')").fetchone()
            rows = int(row[0]) if row else 0
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        finally:
            con.close()
            shutil.rmtree(spill, ignore_errors=True)
        tmp.replace(directory / "part-00000.parquet")
    log.info("précalcul des préfixes par AS terminé", extra={"rows": rows})
    return {"rows": rows}
