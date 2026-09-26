"""Exploration : AS, préfixes, pays, recherche unifiée."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from abrip.api.deps import DataAccess, clamp_limit, get_data_access, org_names
from abrip.api.schemas import AsnSummary, Page, PrefixSummary, SearchHit

router = APIRouter(tags=["exploration"])


@router.get("/asns", response_model=Page[AsnSummary], summary="Systèmes autonomes suivis")
def list_asns(
    country: str | None = Query(None, min_length=2, max_length=2),
    q: str | None = Query(None, description="Recherche par numéro d'AS"),
    african_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    data: DataAccess = Depends(get_data_access),
) -> Page[AsnSummary]:
    limit = clamp_limit(limit)
    elements = data.table("bgp_elements")
    ref = data.optional_table("ref_asn")
    upstream = data.optional_table("metric_upstream")
    events = data.optional_table("events")

    conditions: list[str] = ["e.origin_asn IS NOT NULL"]
    params: list[object] = []
    if country:
        conditions.append("r.country_iso2 = ?")
        params.append(country.upper())
    if african_only and ref:
        conditions.append("r.is_african")
    if q:
        conditions.append("CAST(e.origin_asn AS VARCHAR) LIKE ?")
        params.append(f"%{q}%")

    ref_join = f"LEFT JOIN {ref} r ON r.asn = e.origin_asn" if ref else ""
    ref_cols = (
        "r.country_iso2, r.is_african" if ref else "NULL AS country_iso2, false AS is_african"
    )

    base = f"""
        SELECT e.origin_asn AS asn, {ref_cols},
               count(DISTINCT e.prefix) AS prefixes,
               count(*) AS updates
        FROM {elements} e
        {ref_join}
        WHERE {" AND ".join(conditions)}
        GROUP BY 1, 2, 3
    """
    total = int(data.scalar(f"SELECT count(*) FROM ({base})", params) or 0)
    rows = data.query(f"{base} ORDER BY updates DESC LIMIT ? OFFSET ?", [*params, limit, offset])

    up_by_asn = {}
    if upstream and rows:
        asns = [int(r["asn"]) for r in rows]
        placeholders = ",".join("?" * len(asns))
        up_by_asn = {
            int(r["origin_asn"]): r
            for r in data.query(
                f"""SELECT origin_asn, any_value(upstream_count) AS upstream_count,
                           any_value(primary_upstream) AS primary_upstream,
                           avg(hhi_transit) AS hhi_transit
                    FROM {upstream} WHERE origin_asn IN ({placeholders}) GROUP BY 1""",
                asns,
            )
        }

    open_events: dict[int, int] = {}
    if events and rows:
        open_events = {
            int(r["asn"]): int(r["n"])
            for r in data.query(
                # DuckDB refuse UNNEST dans un SELECT agrégé : on déplie
                # d'abord dans une sous-requête, on agrège ensuite.
                f"""SELECT asn, count(*) AS n FROM (
                        SELECT unnest(asns_involved) AS asn FROM {events}
                    ) GROUP BY 1"""
            )
        }

    names = org_names(
        data,
        [int(r["asn"]) for r in rows]
        + [_int_or_none(v.get("primary_upstream")) for v in up_by_asn.values()],
    )

    items = []
    for r in rows:
        asn = int(r["asn"])
        primary_upstream = _int_or_none(up_by_asn.get(asn, {}).get("primary_upstream"))
        items.append(
            AsnSummary(
                asn=asn,
                as_name=names.get(asn),
                country_iso2=r.get("country_iso2"),
                is_african=bool(r.get("is_african")),
                prefixes=int(r["prefixes"]),
                updates=int(r["updates"]),
                upstream_count=_int_or_none(up_by_asn.get(asn, {}).get("upstream_count")),
                primary_upstream=primary_upstream,
                primary_upstream_name=names.get(primary_upstream) if primary_upstream else None,
                hhi_transit=_float_or_none(up_by_asn.get(asn, {}).get("hhi_transit")),
                open_events=open_events.get(asn, 0),
            )
        )
    return Page[AsnSummary](items=items, total=total, limit=limit, offset=offset)


@router.get("/asns/{asn}", summary="Fiche d'un système autonome")
def asn_detail(asn: int, data: DataAccess = Depends(get_data_access)) -> dict:
    elements = data.table("bgp_elements")
    prefixes = data.query(
        f"""SELECT prefix, count(*) AS updates, min(ts) AS first_seen, max(ts) AS last_seen,
                   count(DISTINCT peer_asn) AS peers
            FROM {elements} WHERE origin_asn = ? AND elem_type = 'A'
            GROUP BY 1 ORDER BY updates DESC LIMIT 200""",
        [asn],
    )
    if not prefixes:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "asn_not_found",
                "message": f"AS{asn} n'apparaît pas dans les données disponibles.",
            },
        )

    identity = {}
    if data.exists("ref_asn"):
        rows = data.query(f"SELECT * FROM {data.table('ref_asn')} WHERE asn = ?", [asn])
        identity = rows[0] if rows else {}

    upstreams = []
    if data.exists("metric_upstream"):
        upstreams = data.query(
            f"""SELECT primary_upstream, avg(hhi_transit) AS hhi_transit,
                       max(upstream_count) AS upstream_count, count(*) AS windows
                FROM {data.table("metric_upstream")} WHERE origin_asn = ?
                GROUP BY 1 ORDER BY windows DESC""",
            [asn],
        )

    events = []
    if data.exists("events"):
        events = data.query(
            f"""SELECT event_id, detector, severity, score, prefix, first_seen, explanation
                FROM {data.table("events")}
                WHERE list_contains(asns_involved, ?) ORDER BY first_seen DESC LIMIT 50""",
            [asn],
        )

    names = org_names(data, [asn, *(_int_or_none(u["primary_upstream"]) for u in upstreams)])
    identity["as_name"] = names.get(asn)
    for row in upstreams:
        up = _int_or_none(row["primary_upstream"])
        row["primary_upstream_name"] = names.get(up) if up else None

    return {
        "asn": asn,
        "identity": identity,
        "prefixes": prefixes,
        "upstreams": upstreams,
        "events": events,
    }


@router.get("/prefixes", response_model=Page[PrefixSummary], summary="Préfixes observés")
def list_prefixes(
    q: str | None = Query(None),
    origin_asn: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    data: DataAccess = Depends(get_data_access),
) -> Page[PrefixSummary]:
    limit = clamp_limit(limit)
    elements = data.table("bgp_elements")
    conditions = ["elem_type <> 'R'"]
    params: list[object] = []
    if q:
        conditions.append("prefix LIKE ?")
        params.append(f"{q}%")
    if origin_asn is not None:
        conditions.append("origin_asn = ?")
        params.append(origin_asn)

    base = f"""
        SELECT prefix, mode(origin_asn) AS origin_asn, count(*) AS updates,
               count(DISTINCT origin_asn) AS distinct_origins
        FROM {elements} WHERE {" AND ".join(conditions)} GROUP BY 1
    """
    total = int(data.scalar(f"SELECT count(*) FROM ({base})", params) or 0)
    rows = data.query(f"{base} ORDER BY updates DESC LIMIT ? OFFSET ?", [*params, limit, offset])

    visibility: dict[str, float] = {}
    if data.exists("metric_visibility") and rows:
        placeholders = ",".join("?" * len(rows))
        visibility = {
            r["prefix"]: float(r["v"])
            for r in data.query(
                f"""SELECT prefix, avg(visibility_ratio) AS v
                    FROM {data.table("metric_visibility")}
                    WHERE prefix IN ({placeholders}) GROUP BY 1""",
                [r["prefix"] for r in rows],
            )
        }

    names = org_names(data, [_int_or_none(r["origin_asn"]) for r in rows])

    items = [
        PrefixSummary(
            prefix=r["prefix"],
            origin_asn=(origin_asn := _int_or_none(r["origin_asn"])),
            origin_as_name=names.get(origin_asn) if origin_asn else None,
            visibility_ratio=visibility.get(r["prefix"]),
            distinct_origins=int(r["distinct_origins"]),
            updates=int(r["updates"]),
        )
        for r in rows
    ]
    return Page[PrefixSummary](items=items, total=total, limit=limit, offset=offset)


@router.get("/prefixes/{prefix:path}", summary="Fiche d'un préfixe")
def prefix_detail(prefix: str, data: DataAccess = Depends(get_data_access)) -> dict:
    elements = data.table("bgp_elements")
    origins = data.query(
        f"""SELECT origin_asn, count(*) AS announcements, min(ts) AS first_seen,
                   max(ts) AS last_seen, count(DISTINCT peer_asn) AS peers
            FROM {elements} WHERE prefix = ? AND elem_type = 'A' AND origin_asn IS NOT NULL
            GROUP BY 1 ORDER BY announcements DESC""",
        [prefix],
    )
    if not origins:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "prefix_not_found",
                "message": f"Le préfixe {prefix} n'apparaît pas dans les données disponibles.",
            },
        )

    paths = data.query(
        f"""SELECT list_aggregate(as_path_dedup, 'string_agg', ' ') AS as_path,
                   count(*) AS observations, count(DISTINCT peer_asn) AS peers
            FROM {elements} WHERE prefix = ? AND elem_type = 'A'
            GROUP BY 1 ORDER BY observations DESC LIMIT 15""",
        [prefix],
    )

    visibility = []
    if data.exists("metric_visibility"):
        visibility = data.query(
            f"""SELECT snapshot_ts, visibility_ratio, peers_seeing, peers_total, collectors_seeing
                FROM {data.table("metric_visibility")} WHERE prefix = ?
                ORDER BY snapshot_ts""",
            [prefix],
        )

    roa = []
    if data.exists("ref_roa"):
        roa = data.query(
            f"SELECT prefix, asn, max_len, ta FROM {data.table('ref_roa')} WHERE prefix = ?",
            [prefix],
        )

    names = org_names(data, [_int_or_none(o["origin_asn"]) for o in origins])
    for row in origins:
        origin = _int_or_none(row["origin_asn"])
        row["as_name"] = names.get(origin) if origin is not None else None

    events = []
    if data.exists("events"):
        events = data.query(
            f"""SELECT event_id, detector, severity, score, confidence, first_seen, explanation
                FROM {data.table("events")} WHERE prefix = ? ORDER BY first_seen DESC LIMIT 50""",
            [prefix],
        )

    return {
        "prefix": prefix,
        "origins": origins,
        "top_paths": paths,
        "visibility": visibility,
        "roa": roa,
        "events": events,
    }


@router.get("/countries", summary="Indicateurs agrégés par pays")
def countries(data: DataAccess = Depends(get_data_access)) -> list[dict]:
    if not data.exists("metric_country"):
        return []
    rpki_join = ""
    rpki_select = "NULL AS rpki_coverage_ratio"
    if data.exists("metric_rpki_coverage"):
        rpki_select = "avg(r.rpki_coverage_ratio) AS rpki_coverage_ratio"
        rpki_join = (
            f"LEFT JOIN {data.table('metric_rpki_coverage')} r ON r.country_iso2 = c.country_iso2"
        )
    return data.query(
        f"""SELECT c.country_iso2 AS country_iso2,
                   avg(c.transit_dependency_ratio) AS transit_dependency_ratio,
                   avg(c.avg_hhi_transit) AS hhi_transit,
                   avg(c.avg_upstream_count) AS avg_upstream_count,
                   max(c.asns_observed) AS asns_observed,
                   avg(c.avg_visibility) AS avg_visibility,
                   max(c.prefixes_visible) AS prefixes_visible,
                   avg(c.coverage_ratio) AS coverage_ratio,
                   {rpki_select}
            FROM {data.table("metric_country")} c
            {rpki_join}
            GROUP BY 1
            ORDER BY transit_dependency_ratio DESC"""
    )


@router.get("/search", response_model=list[SearchHit], summary="Recherche unifiée")
def search(
    q: str = Query(..., min_length=1), data: DataAccess = Depends(get_data_access)
) -> list[SearchHit]:
    hits: list[SearchHit] = []
    term = q.strip()

    if term.upper().startswith("AS") and term[2:].isdigit():
        term = term[2:]

    if term.isdigit() and data.exists("ref_asn"):
        for row in data.query(
            f"""SELECT asn, country_iso2, is_african FROM {data.table("ref_asn")}
                WHERE CAST(asn AS VARCHAR) LIKE ? LIMIT 10""",
            [f"{term}%"],
        ):
            hits.append(
                SearchHit(
                    kind="asn",
                    value=str(row["asn"]),
                    label=f"AS{row['asn']}",
                    detail={"country": row["country_iso2"], "african": row["is_african"]},
                )
            )

    if any(char in term for char in "./:") or term[:1].isdigit():
        for row in data.query(
            f"""SELECT DISTINCT prefix FROM {data.table("bgp_elements")}
                WHERE prefix LIKE ? LIMIT 10""",
            [f"{term}%"],
        ):
            hits.append(SearchHit(kind="prefix", value=row["prefix"], label=row["prefix"]))

    if len(term) == 2 and term.isalpha() and data.exists("ref_asn"):
        count = data.scalar(
            f"SELECT count(*) FROM {data.table('ref_asn')} WHERE country_iso2 = ?", [term.upper()]
        )
        if count:
            hits.append(
                SearchHit(
                    kind="country",
                    value=term.upper(),
                    label=term.upper(),
                    detail={"asns": int(count)},
                )
            )
    return hits[:20]


def _int_or_none(value: Any) -> int | None:
    return int(value) if value is not None else None


def _float_or_none(value: Any) -> float | None:
    return round(float(value), 4) if value is not None else None
