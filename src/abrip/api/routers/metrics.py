"""Séries temporelles dérivées des tables `metric_*`.

Toutes les routes de ce module renvoient le même schéma `Series` : un sujet
(préfixe, ASN, pays ou agrégat global), une granularité, et une liste de points
horodatés portant un dictionnaire de valeurs. Le frontend n'a donc qu'un seul
composant de graphique à écrire, et l'ajout d'une métrique ne casse pas le
contrat.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from abrip.api.deps import DataAccess, get_data_access
from abrip.api.schemas import Series, TimePoint

router = APIRouter(tags=["métriques"])

MAX_POINTS = 2000


def _window_filter(
    column: str,
    date_from: datetime | None,
    date_to: datetime | None,
    conditions: list[str],
    params: list[object],
) -> None:
    if date_from:
        conditions.append(f"{column} >= ?")
        params.append(date_from)
    if date_to:
        conditions.append(f"{column} <= ?")
        params.append(date_to)


def _to_series(
    metric: str,
    subject: str,
    granularity: str,
    rows: list[dict[str, object]],
    ts_key: str,
) -> Series:
    points = [
        TimePoint(
            ts=row[ts_key],  # type: ignore[arg-type]
            values={k: _num(v) for k, v in row.items() if k != ts_key},
        )
        for row in rows
    ]
    return Series(metric=metric, granularity=granularity, subject=subject, points=points)


def _num(value: object) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@router.get("/metrics/churn", response_model=Series, summary="Churn d'annonces dans le temps")
def churn_series(
    prefix: str | None = Query(None, description="Préfixe CIDR exact"),
    asn: int | None = Query(None, ge=0, description="ASN d'origine"),
    collector: str | None = Query(None),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> Series:
    if prefix and asn is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_parameters",
                "message": "Fournir 'prefix' ou 'asn', pas les deux.",
            },
        )

    conditions: list[str] = []
    params: list[object] = []
    if asn is not None:
        source = data.table("metric_churn_asn")
        subject = f"AS{asn}"
        extra = "sum(distinct_prefixes) AS distinct_prefixes"
        conditions.append("origin_asn = ?")
        params.append(asn)
    else:
        source = data.table("metric_churn_prefix")
        subject = prefix or "tous préfixes"
        extra = "max(distinct_peers) AS distinct_peers, max(distinct_origins) AS distinct_origins"
        if prefix:
            conditions.append("prefix = ?")
            params.append(prefix)
    if collector:
        conditions.append("collector = ?")
        params.append(collector)
    _window_filter("window_start", date_from, date_to, conditions, params)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = data.query(
        f"""
        SELECT window_start AS ts,
               sum(announcements) AS announcements,
               sum(withdrawals) AS withdrawals,
               sum(updates_total) AS updates_total,
               {extra}
        FROM {source}
        {where}
        GROUP BY 1 ORDER BY 1
        LIMIT {MAX_POINTS}
        """,
        params,
    )
    return _to_series("churn", subject, "hour", rows, "ts")


@router.get(
    "/metrics/visibility", response_model=Series, summary="Visibilité d'un préfixe ou globale"
)
def visibility_series(
    prefix: str | None = Query(None),
    asn: int | None = Query(None, ge=0),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> Series:
    source = data.table("metric_visibility")
    conditions: list[str] = []
    params: list[object] = []
    subject = "tous préfixes"
    if prefix:
        conditions.append("prefix = ?")
        params.append(prefix)
        subject = prefix
    if asn is not None:
        conditions.append("origin_asn = ?")
        params.append(asn)
        subject = f"AS{asn}"
    _window_filter("snapshot_ts", date_from, date_to, conditions, params)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    aggregate = "avg(visibility_ratio)" if not prefix else "any_value(visibility_ratio)"
    rows = data.query(
        f"""
        SELECT snapshot_ts AS ts,
               {aggregate} AS visibility_ratio,
               avg(visibility_local) AS visibility_local,
               avg(visibility_external) AS visibility_external,
               avg(median_path_len) AS median_path_len,
               count(DISTINCT prefix) AS prefixes
        FROM {source}
        {where}
        GROUP BY 1 ORDER BY 1
        LIMIT {MAX_POINTS}
        """,
        params,
    )
    return _to_series("visibility", subject, "snapshot", rows, "ts")


@router.get(
    "/metrics/countries",
    response_model=Series,
    summary="Dépendance au transit et visibilité par pays",
)
def country_series(
    country: str = Query(..., min_length=2, max_length=2),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> Series:
    source = data.table("metric_country")
    conditions = ["country_iso2 = ?"]
    params: list[object] = [country.upper()]
    _window_filter("window_start", date_from, date_to, conditions, params)
    rows = data.query(
        f"""
        SELECT window_start AS ts,
               any_value(asns_observed) AS asns_observed,
               avg(avg_hhi_transit) AS hhi_transit,
               avg(avg_upstream_count) AS upstream_count,
               avg(transit_dependency_ratio) AS transit_dependency_ratio,
               avg(avg_visibility) AS visibility,
               any_value(prefixes_visible) AS prefixes_visible
        FROM {source}
        WHERE {" AND ".join(conditions)}
        GROUP BY 1 ORDER BY 1
        LIMIT {MAX_POINTS}
        """,
        params,
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "not_found",
                "message": f"Aucune métrique pour le pays {country.upper()}.",
            },
        )
    return _to_series("country", country.upper(), "day", rows, "ts")


@router.get(
    "/metrics/upstreams",
    response_model=Series,
    summary="Concentration du transit d'un AS (HHI)",
)
def upstream_series(
    asn: int = Query(..., ge=0),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> Series:
    source = data.table("metric_upstream")
    conditions = ["origin_asn = ?"]
    params: list[object] = [asn]
    _window_filter("window_start", date_from, date_to, conditions, params)
    rows = data.query(
        f"""
        SELECT window_start AS ts,
               any_value(upstream_count) AS upstream_count,
               any_value(primary_upstream) AS primary_upstream,
               avg(hhi_transit) AS hhi_transit,
               sum(observations) AS observations
        FROM {source}
        WHERE {" AND ".join(conditions)}
        GROUP BY 1 ORDER BY 1
        LIMIT {MAX_POINTS}
        """,
        params,
    )
    return _to_series("upstream", f"AS{asn}", "day", rows, "ts")
