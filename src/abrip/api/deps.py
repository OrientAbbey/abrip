"""Accès aux données depuis l'API.

Choix assumé : l'API interroge les Parquet en SQL via DuckDB plutôt que de
recharger des DataFrames. DuckDB ne lit que les colonnes et les fragments
nécessaires, ce qui tient la cible de p95 sans serveur de base de données.

L'API est **strictement en lecture**. Aucune route n'écrit, aucune route
n'exécute du SQL fourni par l'appelant.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

import duckdb
from fastapi import Header, HTTPException, status

from abrip.config import Settings, get_settings
from abrip.logging_conf import get_logger

log = get_logger(__name__)


def _as_utc(value: Any) -> Any:
    """Rend explicite le fuseau d'un ``datetime`` avant sérialisation JSON.

    DuckDB restitue des ``datetime`` naïfs (l'horloge interne de la plateforme
    est toujours UTC, voir ``storage/catalog.py::_utcnow``) : sans fuseau
    explicite, le JSON produit (ex. ``"2026-09-24T10:00:00"``) est ambigu, et
    ``new Date(...)`` côté navigateur le réinterprète en heure locale plutôt
    qu'en UTC — chaque horodatage affiché se décale du fuseau du visiteur
    (trouvaille FR1, revue du 24/09/2026). Fixé ici, au point unique par où
    transitent tous les résultats DuckDB de l'API, plutôt que dans chaque
    formatteur frontend.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# Tables exposées : nom logique -> (répertoire racine, sous-chemin)
TABLES: dict[str, tuple[str, str]] = {
    "bgp_elements": ("curated", "bgp_elements/**/*.parquet"),
    "rib_snapshots": ("curated", "rib_snapshots/**/*.parquet"),
    "events": ("analytics", "events/*.parquet"),
    "incidents": ("analytics", "incidents/*.parquet"),
    "metric_churn_prefix": ("analytics", "metric_churn_prefix/*.parquet"),
    "metric_churn_asn": ("analytics", "metric_churn_asn/*.parquet"),
    "metric_visibility": ("analytics", "metric_visibility/*.parquet"),
    "metric_aspath": ("analytics", "metric_aspath/*.parquet"),
    "metric_upstream": ("analytics", "metric_upstream/*.parquet"),
    "metric_country": ("analytics", "metric_country/*.parquet"),
    "metric_coverage": ("analytics", "metric_coverage/*.parquet"),
    "metric_rpki_coverage": ("analytics", "metric_rpki_coverage/*.parquet"),
    "ref_asn": ("reference", "ref_asn/*.parquet"),
    "ref_roa": ("reference", "ref_roa/*.parquet"),
    "ref_as_rel": ("reference", "ref_as_rel/*.parquet"),
    "ref_as_org": ("reference", "ref_as_org/*.parquet"),
    "ref_irr_route": ("reference", "ref_irr_route/*.parquet"),
    "ref_anycast": ("reference", "ref_anycast/*.parquet"),
    "ref_as_rel_evidence": ("reference", "ref_as_rel_evidence/*.parquet"),
}


class DataUnavailable(HTTPException):
    """503 explicite : la table n'existe pas encore, et on dit quoi lancer."""

    def __init__(self, table: str, command: str) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "data_unavailable",
                "message": f"La table '{table}' n'a pas encore été produite.",
                "details": {"run": command},
            },
        )


COMMAND_HINTS: dict[str, str] = {
    "bgp_elements": "abrip etl curate --from <date> --to <date>",
    "rib_snapshots": "abrip etl curate --from <date> --to <date>",
    "events": "abrip detect run --from <date> --to <date>",
    "incidents": "abrip detect run --from <date> --to <date>",
    "ref_asn": "abrip reference sync --sources afrinic",
    "ref_roa": "abrip reference sync --sources rpki",
    "ref_as_rel": "abrip reference sync --sources caida",
}


class DataAccess:
    """Façade SQL sur les Parquet. Une instance par application."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._roots = {
            "curated": settings.curated_dir,
            "analytics": settings.analytics_dir,
            "reference": settings.reference_dir,
            "raw": settings.raw_dir,
        }
        self._cache: dict[str, tuple[float, Any]] = {}

    # --- résolution des chemins -----------------------------------------
    def glob_for(self, table: str) -> str:
        if table not in TABLES:
            raise HTTPException(
                status_code=404,
                detail={"code": "unknown_table", "message": f"Table inconnue : {table}"},
            )
        root_name, pattern = TABLES[table]
        return str(self._roots[root_name] / pattern)

    def exists(self, table: str) -> bool:
        root_name, pattern = TABLES[table]
        base = self._roots[root_name] / pattern.split("/")[0]
        return base.exists() and any(base.rglob("*.parquet"))

    def require(self, table: str) -> str:
        if not self.exists(table):
            raise DataUnavailable(table, COMMAND_HINTS.get(table, "abrip demo bootstrap"))
        return self.glob_for(table)

    # --- exécution --------------------------------------------------------
    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        con = duckdb.connect(database=":memory:")
        try:
            cursor = con.execute(sql, params or [])
            columns = [d[0] for d in cursor.description]
            return [
                {col: _as_utc(value) for col, value in zip(columns, row, strict=True)}
                for row in cursor.fetchall()
            ]
        finally:
            con.close()

    def scalar(self, sql: str, params: list[Any] | None = None) -> Any:
        rows = self.query(sql, params)
        return next(iter(rows[0].values())) if rows else None

    def table(self, name: str) -> str:
        """Retourne une expression SQL lisible pour une table exposée."""
        return f"read_parquet('{self.require(name)}', union_by_name=true)"

    def optional_table(self, name: str) -> str | None:
        return self.table(name) if self.exists(name) else None

    # --- cache -------------------------------------------------------------
    def cached(self, key: str, producer: Callable[[], Any]) -> Any:
        ttl = self.settings.api.cache_ttl_seconds
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        value = producer()
        self._cache[key] = (now, value)
        return value

    def invalidate(self) -> None:
        self._cache.clear()


@functools.lru_cache(maxsize=1)
def get_data_access() -> DataAccess:
    return DataAccess(get_settings())


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Clé API optionnelle. Désactivée par défaut, pour ne pas gêner l'usage local."""
    expected = get_settings().api.api_key
    if expected and x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Clé API absente ou invalide."},
        )


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, get_settings().api.max_page_size))


def org_names(data: DataAccess, asns: Iterable[int | None]) -> dict[int, str]:
    """Numéro -> nom d'AS (CAIDA AS2Org), pour l'affichage « AS174 (Cogent…) ».

    Meilleur effort : beaucoup d'AS africains n'ont pas d'entrée dans CAIDA
    AS2Org — l'appelant retombe alors sur le numéro seul, sans mention (voir
    frontend/src/components/Badges.tsx::AsLink). Partagé entre les routeurs
    exploration et topologie plutôt que dupliqué.
    """
    ids = sorted({a for a in asns if a is not None})
    if not ids or not data.exists("ref_as_org"):
        return {}
    placeholders = ",".join("?" * len(ids))
    return {
        int(r["asn"]): r["org_name"]
        for r in data.query(
            f"""SELECT asn, any_value(org_name) AS org_name FROM {data.table("ref_as_org")}
                WHERE asn IN ({placeholders}) GROUP BY 1""",
            ids,
        )
        if r["org_name"]
    }
