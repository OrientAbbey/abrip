"""Explorateurs d'un AS : préfixes, voisins BGP, et relations agrégées d'un pays.

Inspirés de l'interface de radar.qrator.net : un graphe temporel, des onglets
qui le filtrent, et un tableau dessous qui suit la même plage de dates. Toutes
les routes acceptent ``from``/``to`` (défaut : toute la plage disponible), ce
qui permet à l'interface de restreindre graphe **et** tableau à la même
sélection.

Deux conventions valent d'être dites :

- le calcul de voisinage lit les chemins d'AS *dédupliqués du prepending* et
  retient les deux AS immédiatement adjacents dans chaque chemin où l'AS
  apparaît — un voisin BGP observé, pas un voisin déclaré ;
- le type d'un voisin (fournisseur, client, pair) vient des relations CAIDA
  (``ref_as_rel``) ; un voisin sans relation connue est « non spécifié », pas
  déduit par une heuristique de plus.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import polars as pl
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from abrip.analytics.daily import ADJACENCY, PREFIX_ORIGIN, adjacency_sql, summary_is_current
from abrip.api.deps import DataAccess, clamp_limit, get_data_access
from abrip.api.schemas import Page, Series, TimePoint
from abrip.reference.history import annotate_history, classify_presence, snapshot_dates
from abrip.reference.irr import IrrValidator
from abrip.reference.rpki import RpkiValidator

router = APIRouter(tags=["explorateur"])

NEIGHBOUR_TYPES = ("provider", "customer", "peer", "unspecified")


# --- utilitaires -----------------------------------------------------------
def _bounds(
    data: DataAccess, start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    """Plage effective : celle demandée, complétée par les bornes des données."""
    if start is not None and end is not None:
        return start, end
    if data.exists(PREFIX_ORIGIN) and summary_is_current(data.settings, PREFIX_ORIGIN):
        # Les bornes ne servent qu'à choisir des jours : la table journalière les donne
        # sans parcourir bgp_elements (0,9 s à 50 M de lignes, pour deux dates).
        row = data.query(f"SELECT min(day) AS lo, max(day) AS hi FROM {data.table(PREFIX_ORIGIN)}")[
            0
        ]
    else:
        row = data.query(f"SELECT min(ts) AS lo, max(ts) AS hi FROM {data.table('bgp_elements')}")[
            0
        ]
    lo = start or row["lo"] or datetime(1970, 1, 1)
    hi = end or row["hi"] or datetime(1970, 1, 1)
    return lo, hi


def _ip_version_clause(ip_version: str, column: str = "prefix_ip_version") -> str:
    return "" if ip_version == "all" else f"AND {column} = {int(ip_version)}"


def _day_range(lo: datetime, hi: datetime) -> tuple[datetime, datetime]:
    """Jours UTC entiers couvrant [lo, hi].

    Ces endpoints raisonnent en jours (présence d'un préfixe ou d'un voisin un
    jour donné) : une plage qui commence ou finit en milieu de journée inclut
    la journée entière. C'est aussi ce qui permet de répondre depuis les tables
    journalières, qui n'ont pas d'heure."""
    return (
        lo.replace(hour=0, minute=0, second=0, microsecond=0),
        hi.replace(hour=0, minute=0, second=0, microsecond=0),
    )


def _origin_scope(data: DataAccess, kind: str, value: int | str) -> tuple[str, int | str] | None:
    """Condition sur l'origine et valeur de `$1` pour un périmètre : un AS, ou tous
    les AS d'un pays (d'après ref_asn). None : pays sans référentiel, donc sans membres."""
    if kind == "asn":
        return "origin_asn = $1", value
    if not data.exists("ref_asn"):
        return None
    members = f"SELECT asn FROM {data.table('ref_asn')} WHERE country_iso2 = $1"
    return f"origin_asn IN ({members})", str(value).upper()


def _use_summary(data: DataAccess, name: str, d0: datetime, d1: datetime) -> bool:
    """Répondre depuis la table journalière ? Seulement si elle couvre tous les jours
    curés de la plage et n'est pas plus ancienne qu'eux ; sinon calcul direct, exact
    mais plus lent (voir analytics/daily.py)."""
    if not data.exists(name):
        return False
    days = [(d0 + timedelta(days=i)).date().isoformat() for i in range((d1 - d0).days + 1)]
    return summary_is_current(data.settings, name, days)


def _load_frame(data: DataAccess, table: str) -> pl.DataFrame:
    if not data.exists(table):
        return pl.DataFrame()
    return pl.read_parquet(sorted((data.settings.reference_dir / table).glob("**/*.parquet")))


# --- 6.1 : préfixes d'un AS -------------------------------------------------
@router.get(
    "/asns/{asn}/prefixes/timeseries",
    response_model=Series,
    summary="Nombre total de préfixes originés par un AS, jour par jour",
)
def prefix_count_series(
    asn: int,
    ip_version: str = Query("all", pattern="^(all|4|6)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> Series:
    return _prefix_series(data, "asn", asn, f"AS{asn}", ip_version, date_from, date_to)


def _prefix_series(
    data: DataAccess,
    kind: str,
    value: int | str,
    subject: str,
    ip_version: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Series:
    scope = _origin_scope(data, kind, value)
    d0, d1 = _day_range(*_bounds(data, date_from, date_to))
    if scope is None:
        return Series(metric="prefix_count", granularity="day", subject=subject, points=[])
    cond, param = scope
    if _use_summary(data, PREFIX_ORIGIN, d0, d1):
        rows = data.query(
            f"""SELECT day, count(DISTINCT prefix) AS total
                FROM {data.table(PREFIX_ORIGIN)}
                WHERE {cond} AND announcements > 0 AND day BETWEEN $2 AND $3
                      {_ip_version_clause(ip_version, "ip_version")}
                GROUP BY 1 ORDER BY 1""",
            [param, d0, d1],
        )
    else:
        rows = data.query(
            f"""SELECT date_trunc('day', ts) AS day, count(DISTINCT prefix) AS total
                FROM {data.table("bgp_elements")}
                WHERE {cond} AND elem_type = 'A'
                      AND ts >= $2 AND ts < $3 + INTERVAL 1 DAY
                      {_ip_version_clause(ip_version)}
                GROUP BY 1 ORDER BY 1""",
            [param, d0, d1],
        )
    points = [TimePoint(ts=r["day"], values={"prefixes": r["total"]}) for r in rows]
    return Series(metric="prefix_count", granularity="day", subject=subject, points=points)


@router.get(
    "/countries/{iso2}/prefixes/timeseries",
    response_model=Series,
    summary="Nombre de préfixes originés par les AS d'un pays, jour par jour",
)
def country_prefix_series(
    iso2: str,
    ip_version: str = Query("all", pattern="^(all|4|6)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> Series:
    return _prefix_series(data, "country", iso2, iso2.upper(), ip_version, date_from, date_to)


@router.get("/asns/{asn}/prefixes", summary="Préfixes d'un AS sur une plage de dates")
def prefix_table(
    asn: int,
    ip_version: str = Query("all", pattern="^(all|4|6)$"),
    status: str = Query("all", pattern="^(all|new|left|unstable)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    data: DataAccess = Depends(get_data_access),
) -> Page[dict[str, Any]]:
    """Classement New / Left / Unstable d'un préfixe sur la plage choisie.

    Règle, volontairement simple et lisible plutôt qu'exhaustive :
    - *new* : absent le premier jour de la plage, présent le dernier ;
    - *left* : présent le premier jour, absent le dernier ;
    - *unstable* : présent aux deux bouts mais avec au moins un jour d'absence
      entre les deux, ou apparu et disparu entièrement à l'intérieur de la
      plage — dans les deux cas, plusieurs apparitions/disparitions ;
    - sinon, actif sans interruption (visible seulement sous l'onglet « All »).
    """
    return _prefix_page(data, "asn", asn, ip_version, status, date_from, date_to, limit, offset)


@router.get(
    "/countries/{iso2}/prefixes",
    summary="Préfixes originés par les AS d'un pays, par plage de dates",
)
def country_prefix_table(
    iso2: str,
    ip_version: str = Query("all", pattern="^(all|4|6)$"),
    status: str = Query("all", pattern="^(all|new|left|unstable)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    data: DataAccess = Depends(get_data_access),
) -> Page[dict[str, Any]]:
    """Même classement que pour un AS, par couple (AS membre, préfixe) : chaque ligne
    porte `origin_asn`, l'AS du pays qui annonce le préfixe."""
    return _prefix_page(
        data, "country", iso2, ip_version, status, date_from, date_to, limit, offset
    )


def _prefix_rows(
    data: DataAccess,
    kind: str,
    value: int | str,
    ip_version: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[dict[str, Any]]:
    """Lignes (préfixe, origine, statut) sur la plage, avant filtre de statut."""
    scope = _origin_scope(data, kind, value)
    d0, d1 = _day_range(*_bounds(data, date_from, date_to))
    if scope is None:
        return []
    cond, param = scope
    if _use_summary(data, PREFIX_ORIGIN, d0, d1):
        source = f"""days AS (
                SELECT DISTINCT origin_asn, prefix, ip_version AS prefix_ip_version, day
                FROM {data.table(PREFIX_ORIGIN)}
                WHERE {cond} AND announcements > 0 AND day BETWEEN $2 AND $3
                      {_ip_version_clause(ip_version, "ip_version")}
            ),
            span AS (
                SELECT min(day) AS d0, max(day) AS d1
                FROM {data.table(PREFIX_ORIGIN)} WHERE day BETWEEN $2 AND $3
            ),"""
    else:
        source = f"""days AS (
                SELECT DISTINCT origin_asn, prefix, prefix_ip_version, date_trunc('day', ts) AS day
                FROM {data.table("bgp_elements")}
                WHERE {cond} AND elem_type = 'A'
                      AND ts >= $2 AND ts < $3 + INTERVAL 1 DAY
                      {_ip_version_clause(ip_version)}
            ),
            span AS (
                SELECT min(date_trunc('day', ts)) AS d0, max(date_trunc('day', ts)) AS d1
                FROM {data.table("bgp_elements")}
                WHERE ts >= $2 AND ts < $3 + INTERVAL 1 DAY
            ),"""
    rows = data.query(
        f"""WITH {source}
            per_prefix AS (
                SELECT origin_asn, prefix, any_value(prefix_ip_version) AS ip_version,
                       min(day) AS first_seen, max(day) AS last_seen,
                       count(DISTINCT day) AS days_active,
                       list(day ORDER BY day) AS seen_days,
                       bool_or(day = (SELECT d0 FROM span)) AS at_start,
                       bool_or(day = (SELECT d1 FROM span)) AS at_end
                FROM days GROUP BY origin_asn, prefix
            )
            SELECT p.*, date_diff('day', s.d0, s.d1) + 1 AS days_total
            FROM per_prefix p, span s
            ORDER BY p.prefix, p.origin_asn""",
        [param, d0, d1],
    )
    if rows:
        days = _data_days(data, d0, d1)
        for row in rows:
            row["status"] = classify_presence(row["seen_days"], days)
    return rows


class PrefixFacets(BaseModel):
    """Comptes exacts par famille d'adresses et par statut, sur la plage choisie."""

    ip_version: dict[str, int]
    status: dict[str, int]


def _prefix_facets(
    data: DataAccess,
    kind: str,
    value: int | str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> PrefixFacets:
    rows = _prefix_rows(data, kind, value, "all", date_from, date_to)
    return PrefixFacets(
        ip_version={key: sum(1 for r in rows if str(r["ip_version"]) == key) for key in ("4", "6")},
        status={
            key: sum(1 for r in rows if r["status"] == key)
            for key in ("stable", "new", "left", "unstable")
        },
    )


def _prefix_page(
    data: DataAccess,
    kind: str,
    value: int | str,
    ip_version: str,
    status: str,
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int,
    offset: int,
) -> Page[dict[str, Any]]:
    limit = clamp_limit(limit)
    rows = _prefix_rows(data, kind, value, ip_version, date_from, date_to)
    if status != "all":
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    page_rows = rows[offset : offset + limit]

    roa_frame = _load_frame(data, "ref_roa")
    irr_frame = _load_frame(data, "ref_irr_route")
    rpki = RpkiValidator.from_frame(roa_frame) if not roa_frame.is_empty() else None
    irr = IrrValidator.from_frame(irr_frame) if not irr_frame.is_empty() else None

    items: list[dict[str, Any]] = []
    for r in page_rows:
        prefix = r["prefix"]
        items.append(
            {
                "prefix": prefix,
                "origin_asn": int(r["origin_asn"]),
                "ip_version": int(r["ip_version"]),
                "active": bool(r["at_end"]),
                "status": r["status"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
                "days_active": int(r["days_active"]),
                "days_total": int(r["days_total"]),
                "rpki_status": rpki.validate(prefix, int(r["origin_asn"])).value
                if rpki
                else "not-found",
                "irr_status": irr.validate(prefix, int(r["origin_asn"])).value
                if irr
                else "irr_absent",
            }
        )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/asns/{asn}/prefixes/facets",
    response_model=PrefixFacets,
    summary="Comptes des préfixes d'un AS par famille et par statut",
)
def asn_prefix_facets(
    asn: int,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> PrefixFacets:
    return _prefix_facets(data, "asn", asn, date_from, date_to)


@router.get(
    "/countries/{iso2}/prefixes/facets",
    response_model=PrefixFacets,
    summary="Comptes des préfixes d'un pays par famille et par statut",
)
def country_prefix_facets(
    iso2: str,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> PrefixFacets:
    return _prefix_facets(data, "country", iso2.upper(), date_from, date_to)


def _history(
    data: DataAccess, table: str, columns: list[tuple[str, str]], prefix: str, asn: int
) -> list[dict[str, Any]]:
    """Regroupe les instantanés datés d'un référentiel en lignes « première /
    dernière apparition », avec le changement classé (new/left/unstable/stable).
    ``columns`` est une liste ``(expression, alias)``.

    Sans historique daté (aucune synchronisation encore faite), rend la table
    courante, en indiquant que la date n'est pas connue plutôt que d'inventer
    une première apparition.

    Correspondance sur le préfixe *exact* : un ROA d'un supernet qui couvre le
    préfixe sans le nommer n'apparaît pas ici — c'est l'historique des
    objets publiés pour ce préfixe, pas une validation d'origine.
    """
    select = ", ".join(f"{expr} AS {alias}" for expr, alias in columns)
    group = ", ".join(expr for expr, _ in columns)
    dates = snapshot_dates(data.settings.reference_dir, table)
    history_dir = data.settings.reference_dir / "history" / table
    files = sorted(history_dir.glob("date=*/*.parquet")) if history_dir.exists() else []
    if files:
        source = ", ".join(f"'{f}'" for f in files)
        rows = data.query(
            f"""SELECT {select},
                       min(snapshot_date) AS first_seen, max(snapshot_date) AS last_seen,
                       list(snapshot_date ORDER BY snapshot_date) AS seen_on
                FROM read_parquet([{source}], union_by_name=true)
                WHERE prefix = $1
                GROUP BY {group}
                ORDER BY first_seen""",
            [prefix],
        )
        annotate_history(rows, dates)
    else:
        current = data.settings.reference_dir / table
        files = sorted(current.glob("*.parquet")) if current.exists() else []
        if not files:
            return []
        source = ", ".join(f"'{f}'" for f in files)
        rows = data.query(
            f"""SELECT {select}, NULL AS first_seen, NULL AS last_seen
                FROM read_parquet([{source}], union_by_name=true)
                WHERE prefix = $1""",
            [prefix],
        )
        for row in rows:
            row["change"] = "unknown"
            row["active"] = False
    for row in rows:
        row["match"] = int(row["origin"]) == asn
    return rows


@router.get(
    "/asns/{asn}/prefixes/{prefix:path}/roa-history",
    summary="Historique des ROA RPKI d'un préfixe",
)
def roa_history(
    asn: int, prefix: str, data: DataAccess = Depends(get_data_access)
) -> dict[str, Any]:
    rows = _history(
        data,
        "ref_roa",
        [
            ("prefix", "prefix"),
            ("asn", "origin"),
            ("ta", "trust_anchor"),
            ("max_len", "max_length"),
        ],
        prefix,
        asn,
    )
    return {"prefix": prefix, "specified_asn": asn, "rows": rows}


@router.get(
    "/asns/{asn}/prefixes/{prefix:path}/route-history",
    summary="Historique des objets route IRR d'un préfixe",
)
def route_object_history(
    asn: int, prefix: str, data: DataAccess = Depends(get_data_access)
) -> dict[str, Any]:
    rows = _history(
        data,
        "ref_irr_route",
        [("prefix", "prefix"), ("asn", "origin"), ("source", "source")],
        prefix,
        asn,
    )
    return {"prefix": prefix, "specified_asn": asn, "rows": rows}


# --- 6.2 : voisins BGP ------------------------------------------------------
_NEIGHBOUR_PAIRS_RAW = """
    occ AS (
        SELECT ts, prefix_ip_version, as_path_dedup,
               list_position(as_path_dedup, $1) AS pos, len(as_path_dedup) AS plen
        FROM {elements}
        WHERE elem_type = 'A' AND ts >= $2 AND ts < $3 + INTERVAL 1 DAY
              AND list_contains(as_path_dedup, $1)
    ),
    pairs AS (
        SELECT date_trunc('day', ts) AS day, prefix_ip_version, as_path_dedup[pos - 1] AS neighbour
        FROM occ WHERE pos > 1
        UNION ALL
        SELECT date_trunc('day', ts) AS day, prefix_ip_version, as_path_dedup[pos + 1] AS neighbour
        FROM occ WHERE pos < plen
    ),"""

# Même résultat depuis la table journalière (analytics/daily.py) : une ligne par jour,
# version IP et voisin, au lieu de relire tous les chemins.
_NEIGHBOUR_PAIRS_SUMMARY = """
    pairs AS (
        SELECT day, ip_version AS prefix_ip_version, neighbour
        FROM {adjacency} WHERE asn = $1 AND day BETWEEN $2 AND $3
    ),"""

_NEIGHBOUR_TYPES_SQL = """
    rel AS (
        -- Vu depuis l'AS $1 : le voisin est son fournisseur si (voisin p2c AS),
        -- son client si (AS p2c voisin), un pair si p2p dans un sens ou l'autre.
        SELECT as_a AS neighbour, 'provider' AS kind FROM {ref_rel}
            WHERE as_b = $1 AND relationship = 'p2c'
        UNION ALL
        SELECT as_b AS neighbour, 'customer' AS kind FROM {ref_rel}
            WHERE as_a = $1 AND relationship = 'p2c'
        UNION ALL
        SELECT as_b AS neighbour, 'peer' AS kind FROM {ref_rel}
            WHERE as_a = $1 AND relationship = 'p2p'
        UNION ALL
        SELECT as_a AS neighbour, 'peer' AS kind FROM {ref_rel}
            WHERE as_b = $1 AND relationship = 'p2p'
    ),
    typed AS (
        SELECT p.day, p.prefix_ip_version, p.neighbour,
               coalesce(any_value(r.kind), 'unspecified') AS kind
        FROM pairs p LEFT JOIN rel r ON p.neighbour = r.neighbour
        WHERE p.neighbour IS NOT NULL
        GROUP BY p.day, p.prefix_ip_version, p.neighbour
    )
"""


def _neighbour_sql(data: DataAccess, summary: bool) -> str:
    ref_rel = data.optional_table("ref_as_rel")
    if ref_rel is None:
        # Sans relations connues, tout voisin reste « non spécifié » : une
        # table vide au bon schéma évite de dupliquer la requête.
        ref_rel = "(SELECT 0::UBIGINT AS as_a, 0::UBIGINT AS as_b, '' AS relationship WHERE false)"
    pairs = (
        _NEIGHBOUR_PAIRS_SUMMARY.format(adjacency=data.table(ADJACENCY))
        if summary
        else _NEIGHBOUR_PAIRS_RAW.format(elements=data.table("bgp_elements"))
    )
    return "WITH" + pairs + _NEIGHBOUR_TYPES_SQL.format(ref_rel=ref_rel)


@router.get("/asns/{asn}/neighbours", summary="Voisins BGP observés d'un AS")
def neighbour_table(
    asn: int,
    kind: str = Query("all", alias="type", pattern="^(all|provider|customer|peer|unspecified)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    d0, d1 = _day_range(*_bounds(data, date_from, date_to))
    type_clause = "" if kind == "all" else "WHERE kind = $4"
    params: list[Any] = [asn, d0, d1] + ([] if kind == "all" else [kind])
    rows = data.query(
        _neighbour_sql(data, _use_summary(data, ADJACENCY, d0, d1))
        + f"""
        SELECT neighbour AS asn, kind AS type,
               bool_or(prefix_ip_version = 4) AS ipv4,
               bool_or(prefix_ip_version = 6) AS ipv6,
               min(day) AS first_seen, max(day) AS last_seen,
               list(DISTINCT day ORDER BY day) AS history,
               max(day) = (SELECT max(day) FROM typed) AS active_now
        FROM typed {type_clause}
        GROUP BY neighbour, kind
        ORDER BY active_now DESC, count(DISTINCT day) DESC, neighbour""",
        params,
    )

    countries = {}
    if data.exists("ref_asn"):
        for r in data.query(f"SELECT asn, country_iso2 FROM {data.table('ref_asn')}"):
            countries[int(r["asn"])] = r["country_iso2"]

    all_days = sorted({d for r in rows for d in r["history"]})
    status_counts = _add_statuses(rows, _data_days(data, d0, d1))
    for r in rows:
        r["country_iso2"] = countries.get(int(r["asn"]))
        r["history"] = [
            d.date().isoformat() if hasattr(d, "date") else str(d) for d in r["history"]
        ]
    return {
        "asn": asn,
        "days": [d.date().isoformat() if hasattr(d, "date") else str(d) for d in all_days],
        "counts": {k: sum(1 for r in rows if r["type"] == k) for k in NEIGHBOUR_TYPES},
        "status_counts": status_counts,
        "items": rows,
    }


@router.get(
    "/asns/{asn}/neighbours/timeseries",
    response_model=Series,
    summary="Nombre de voisins BGP par type, jour par jour",
)
def neighbour_series(
    asn: int,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> Series:
    d0, d1 = _day_range(*_bounds(data, date_from, date_to))
    rows = data.query(
        _neighbour_sql(data, _use_summary(data, ADJACENCY, d0, d1))
        + """
        SELECT day, kind, count(DISTINCT neighbour) AS n
        FROM typed GROUP BY day, kind ORDER BY day""",
        [asn, d0, d1],
    )
    by_day: dict[Any, dict[str, float | None]] = {}
    for r in rows:
        by_day.setdefault(r["day"], {k: 0 for k in NEIGHBOUR_TYPES})[r["kind"]] = r["n"]
    points = [TimePoint(ts=day, values=values) for day, values in sorted(by_day.items())]
    return Series(metric="neighbour_count", granularity="day", subject=f"AS{asn}", points=points)


# --- 6.3 : un pays, vu par ses AS et leurs relations ------------------------
def _country_typed_sql(data: DataAccess, summary: bool) -> str:
    """CTE `typed` pour tous les AS d'un pays : (jour, version IP, AS membre, voisin, type).

    Même logique que `_neighbour_sql`, avec la colonne `member` : le type est celui
    de la relation vue depuis le membre. `$1` = code pays, `$2`/`$3` = jours."""
    ref_rel = data.optional_table("ref_as_rel")
    rel = (
        f"""
        SELECT as_b AS member, as_a AS neighbour, 'provider' AS kind FROM {ref_rel}
            WHERE relationship = 'p2c'
        UNION ALL
        SELECT as_a AS member, as_b AS neighbour, 'customer' AS kind FROM {ref_rel}
            WHERE relationship = 'p2c'
        UNION ALL
        SELECT as_a AS member, as_b AS neighbour, 'peer' AS kind FROM {ref_rel}
            WHERE relationship = 'p2p'
        UNION ALL
        SELECT as_b AS member, as_a AS neighbour, 'peer' AS kind FROM {ref_rel}
            WHERE relationship = 'p2p'"""
        if ref_rel
        else "SELECT NULL::UINTEGER AS member, NULL::UINTEGER AS neighbour, '' AS kind WHERE false"
    )
    if summary:
        adjacency = f"SELECT day, ip_version, asn, neighbour FROM {data.table(ADJACENCY)}"
        window = "day BETWEEN $2 AND $3"
    else:
        adjacency = adjacency_sql(
            data.table("bgp_elements"), "AND ts >= $2 AND ts < $3 + INTERVAL 1 DAY"
        )
        window = "TRUE"
    return f"""
    WITH members AS (SELECT asn FROM {data.table("ref_asn")} WHERE country_iso2 = $1),
    adj AS ({adjacency}),
    pairs AS (
        SELECT day, ip_version AS prefix_ip_version, asn AS member, neighbour
        FROM adj WHERE asn IN (SELECT asn FROM members) AND {window}
    ),
    rel AS ({rel}),
    typed AS (
        SELECT p.day, p.prefix_ip_version, p.member, p.neighbour,
               coalesce(any_value(r.kind), 'unspecified') AS kind
        FROM pairs p LEFT JOIN rel r ON r.member = p.member AND r.neighbour = p.neighbour
        WHERE p.neighbour IS NOT NULL
        GROUP BY p.day, p.prefix_ip_version, p.member, p.neighbour
    )"""


@router.get(
    "/countries/{iso2}/neighbours",
    summary="Voisins BGP des AS d'un pays, par AS membre et par type de relation",
)
def country_neighbour_table(
    iso2: str,
    kind: str = Query("all", alias="type", pattern="^(all|provider|customer|peer|unspecified)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    """Une ligne par couple (AS du pays, voisin) : `member_asn` est l'AS du pays."""
    d0, d1 = _day_range(*_bounds(data, date_from, date_to))
    code = iso2.upper()
    empty: dict[str, Any] = {
        "country_iso2": code,
        "days": [],
        "counts": {k: 0 for k in NEIGHBOUR_TYPES},
        "status_counts": {"stable": 0, "new": 0, "left": 0, "unstable": 0},
        "items": [],
    }
    if not data.exists("ref_asn") or not data.exists("bgp_elements"):
        return empty
    type_clause = "" if kind == "all" else "WHERE kind = $4"
    params: list[Any] = [code, d0, d1] + ([] if kind == "all" else [kind])
    rows = data.query(
        _country_typed_sql(data, _use_summary(data, ADJACENCY, d0, d1))
        + f"""
        SELECT member AS member_asn, neighbour AS asn, kind AS type,
               bool_or(prefix_ip_version = 4) AS ipv4,
               bool_or(prefix_ip_version = 6) AS ipv6,
               min(day) AS first_seen, max(day) AS last_seen,
               list(DISTINCT day ORDER BY day) AS history,
               max(day) = (SELECT max(day) FROM typed) AS active_now
        FROM typed {type_clause}
        GROUP BY member, neighbour, kind
        ORDER BY active_now DESC, count(DISTINCT day) DESC, member, neighbour""",
        params,
    )
    countries = {
        int(r["asn"]): r["country_iso2"]
        for r in data.query(f"SELECT asn, country_iso2 FROM {data.table('ref_asn')}")
    }

    def iso(day: Any) -> str:
        return day.date().isoformat() if hasattr(day, "date") else str(day)

    all_days = sorted({day for r in rows for day in r["history"]})
    status_counts = _add_statuses(rows, _data_days(data, d0, d1))
    for r in rows:
        r["country_iso2"] = countries.get(int(r["asn"]))
        r["history"] = [iso(day) for day in r["history"]]
    return {
        "country_iso2": code,
        "days": [iso(day) for day in all_days],
        "counts": {k: sum(1 for r in rows if r["type"] == k) for k in NEIGHBOUR_TYPES},
        "status_counts": status_counts,
        "items": rows,
    }


@router.get(
    "/countries/{iso2}/neighbours/timeseries",
    response_model=Series,
    summary="Nombre de couples (AS du pays, voisin) par type, jour par jour",
)
def country_neighbour_series(
    iso2: str,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> Series:
    d0, d1 = _day_range(*_bounds(data, date_from, date_to))
    code = iso2.upper()
    if not data.exists("ref_asn") or not data.exists("bgp_elements"):
        return Series(metric="neighbour_count", granularity="day", subject=code, points=[])
    rows = data.query(
        _country_typed_sql(data, _use_summary(data, ADJACENCY, d0, d1))
        + """
        SELECT day, kind, count(DISTINCT (member, neighbour)) AS n
        FROM typed GROUP BY day, kind ORDER BY day""",
        [code, d0, d1],
    )
    by_day: dict[Any, dict[str, float | None]] = {}
    for r in rows:
        by_day.setdefault(r["day"], {k: 0 for k in NEIGHBOUR_TYPES})[r["kind"]] = r["n"]
    points = [TimePoint(ts=day, values=values) for day, values in sorted(by_day.items())]
    return Series(metric="neighbour_count", granularity="day", subject=code, points=points)


def _data_days(data: DataAccess, d0: datetime, d1: datetime) -> list[date]:
    """Jours de collecte de [d0, d1], tous AS confondus.

    Une période d'annonce se calcule sur ces jours-là, pas sur le calendrier : un
    jour sans aucune donnée (collecte interrompue) n'est pas une absence du
    préfixe, et ne doit pas couper une période en deux."""
    if _use_summary(data, PREFIX_ORIGIN, d0, d1):
        rows = data.query(
            f"SELECT DISTINCT day FROM {data.table(PREFIX_ORIGIN)} WHERE day BETWEEN $1 AND $2",
            [d0, d1],
        )
    else:
        rows = data.query(
            f"""SELECT DISTINCT date_trunc('day', ts) AS day FROM {data.table("bgp_elements")}
                WHERE ts >= $1 AND ts < $2 + INTERVAL 1 DAY""",
            [d0, d1],
        )
    return sorted(r["day"].date() for r in rows)


def _presence_status(present: set[date], days: list[date]) -> str:
    """Délègue à la règle unique, sans duplication SQL/Python."""
    return classify_presence(present, days)


def _add_statuses(
    rows: list[dict[str, Any]], days: list[date], history_key: str = "history"
) -> dict[str, int]:
    """Ajoute `status` à chaque ligne (d'après ses jours de présence) ; renvoie les décomptes."""
    counts = {"stable": 0, "new": 0, "left": 0, "unstable": 0}
    for r in rows:
        present = {d.date() if hasattr(d, "date") else d for d in r[history_key]}
        r["status"] = _presence_status(present, days)
        counts[r["status"]] += 1
    return counts


def _runs(present: dict[date, int], days: list[date]) -> list[dict[str, Any]]:
    """Périodes de présence continue sur les jours de collecte.

    `present` : jour -> nombre d'observations. Une période est une suite de jours de
    collecte consécutifs où l'élément est présent ; elle est « en cours » si elle
    atteint le dernier jour de la plage."""
    runs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for day in days:
        if day in present:
            if current is None:
                current = {"first_seen": day.isoformat(), "days": 0, "observations": 0}
            current["last_seen"] = day.isoformat()
            current["days"] += 1
            current["observations"] += present[day]
        elif current is not None:
            runs.append(current)
            current = None
    if current is not None:
        runs.append(current)
    last = days[-1].isoformat() if days else None
    return [{**r, "active": r["last_seen"] == last} for r in runs]


def _without_counts(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Une relation est présente ou non un jour donné : pas de nombre d'observations."""
    return [{k: v for k, v in run.items() if k != "observations"} for run in runs]


@router.get(
    "/asns/{asn}/prefixes/{prefix:path}/history",
    summary="Périodes d'annonce d'un préfixe par cet AS",
)
def prefix_announcement_history(
    asn: int,
    prefix: str,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    """Quand cet AS a annoncé ce préfixe : chaque période continue, avec ses trous.

    Le tableau des préfixes ne donne que le premier et le dernier jour vus, ce qui
    cache les interruptions ; un préfixe « instable » se lit ici."""
    empty: dict[str, Any] = {
        "asn": asn,
        "prefix": prefix,
        "start": None,
        "end": None,
        "items": [],
        "daily": [],
    }
    if not data.exists("bgp_elements"):
        return empty
    d0, d1 = _day_range(*_bounds(data, date_from, date_to))
    days = _data_days(data, d0, d1)
    if not days:
        return empty
    if _use_summary(data, PREFIX_ORIGIN, d0, d1):
        rows = data.query(
            f"""SELECT day, sum(announcements) AS n FROM {data.table(PREFIX_ORIGIN)}
                WHERE origin_asn = $1 AND prefix = $4 AND announcements > 0
                      AND day BETWEEN $2 AND $3 GROUP BY 1""",
            [asn, d0, d1, prefix],
        )
    else:
        rows = data.query(
            f"""SELECT date_trunc('day', ts) AS day, count(*) AS n
                FROM {data.table("bgp_elements")}
                WHERE origin_asn = $1 AND prefix = $4 AND elem_type = 'A'
                      AND ts >= $2 AND ts < $3 + INTERVAL 1 DAY GROUP BY 1""",
            [asn, d0, d1, prefix],
        )
    present = {r["day"].date(): int(r["n"]) for r in rows}
    return {
        **empty,
        "start": days[0].isoformat(),
        "end": days[-1].isoformat(),
        "items": _runs(present, days),
        "daily": [{"day": d.isoformat(), "observations": present.get(d, 0)} for d in days],
    }


@router.get(
    "/asns/{asn}/neighbours/{neighbour}/history",
    summary="Historique de la relation entre deux AS (IPv4 / IPv6)",
)
def neighbour_history(
    asn: int,
    neighbour: int,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    """Quand ces deux AS ont été vus côte à côte sur un chemin, par famille
    d'adresses, avec le type de la relation (fournisseur, client, pair)."""
    empty: dict[str, Any] = {
        "asn": asn,
        "neighbour": neighbour,
        "type": "unspecified",
        "start": None,
        "end": None,
        "ipv4": [],
        "ipv6": [],
        "daily": [],
    }
    if not data.exists("bgp_elements"):
        return empty
    d0, d1 = _day_range(*_bounds(data, date_from, date_to))
    days = _data_days(data, d0, d1)
    if not days:
        return empty
    rows = data.query(
        _neighbour_sql(data, _use_summary(data, ADJACENCY, d0, d1))
        + """
        SELECT day, prefix_ip_version AS ip_version, kind FROM typed
        WHERE neighbour = $4 ORDER BY day""",
        [asn, d0, d1, neighbour],
    )
    by_family: dict[int, dict[date, int]] = {4: {}, 6: {}}
    for r in rows:
        by_family[int(r["ip_version"])][r["day"].date()] = 1
    result = {
        **empty,
        "type": rows[-1]["kind"] if rows else "unspecified",
        "start": days[0].isoformat(),
        "end": days[-1].isoformat(),
        "ipv4": _without_counts(_runs(by_family[4], days)),
        "ipv6": _without_counts(_runs(by_family[6], days)),
        "daily": [
            {"day": d.isoformat(), "ipv4": d in by_family[4], "ipv6": d in by_family[6]}
            for d in days
        ],
    }
    return result


@router.get("/countries/{iso2}/relationships", summary="AS d'un pays et relations agrégées")
def country_relationships(iso2: str, data: DataAccess = Depends(get_data_access)) -> dict[str, Any]:
    """Vue de tout un pays : ses AS, et pour chaque relation CAIDA reliant un AS
    du pays à un AS extérieur, le voisin classé fournisseur / client / pair
    *du point de vue du pays*, avec le nombre d'AS du pays qu'il relie.
    """
    code = iso2.upper()
    if not data.exists("ref_asn"):
        return {"country_iso2": code, "asns": [], "providers": [], "customers": [], "peers": []}

    asn_rows = data.query(
        f"SELECT asn FROM {data.table('ref_asn')} WHERE country_iso2 = $1 ORDER BY asn", [code]
    )
    local = [int(r["asn"]) for r in asn_rows]
    result: dict[str, Any] = {
        "country_iso2": code,
        "asns": local,
        "providers": [],
        "customers": [],
        "peers": [],
    }
    if not local or not data.exists("ref_as_rel"):
        return result

    countries = {
        int(r["asn"]): r["country_iso2"]
        for r in data.query(f"SELECT asn, country_iso2 FROM {data.table('ref_asn')}")
    }
    rel = data.query(f"SELECT as_a, as_b, relationship FROM {data.table('ref_as_rel')}")
    local_set = set(local)

    buckets: dict[str, dict[int, set[int]]] = {"providers": {}, "customers": {}, "peers": {}}
    for r in rel:
        a, b, kind = int(r["as_a"]), int(r["as_b"]), r["relationship"]
        for mine, other, mine_is_a in ((a, b, True), (b, a, False)):
            if mine not in local_set or other in local_set:
                continue  # le lien doit relier le pays à l'extérieur
            if kind == "p2p":
                bucket = "peers"
            elif kind == "p2c":
                # as_a est fournisseur de as_b : si mon AS est as_a, l'autre est mon client.
                bucket = "customers" if mine_is_a else "providers"
            else:
                continue
            buckets[bucket].setdefault(other, set()).add(mine)

    for bucket, mapping in buckets.items():
        result[bucket] = sorted(
            (
                {"asn": other, "country_iso2": countries.get(other), "local_asns": sorted(mine)}
                for other, mine in mapping.items()
            ),
            key=lambda item: (-len(item["local_asns"]), item["asn"]),
        )
    return result
