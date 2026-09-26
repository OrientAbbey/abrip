"""Topologie : évolution des préfixes et voisins BGP d'un AS (point 6, lot 2).

Trois familles d'endpoints, tous en lecture seule comme le reste de l'API
(voir ``api/deps.py``) :

- ``/asns/{asn}/prefixes/timeseries`` et ``/changes`` — la courbe et le
  tableau New/Left/Unstable de l'onglet Préfixes d'une fiche ASN, calculés
  sur les données BGP curées (jour par jour, déjà disponibles en démo).
- ``/asns/{asn}/neighbors`` — les voisins directs observés sur les chemins
  AS-path passant par cet AS, classés fournisseur/client/peering/inconnu via
  ``reference.relationships.RelationshipIndex``.
- ``/prefixes/{prefix}/roa-history`` et ``/route-object-history`` — pour les
  modales RPKI ROA / Route Object de la même fiche, via
  ``reference.history.diff_entities`` sur les référentiels historisés.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from abrip.analytics.metrics import _load_reference
from abrip.api.deps import DataAccess, get_data_access, org_names
from abrip.reference.history import classify_presence, diff_entities, snapshot_dates
from abrip.reference.relationships import RelationshipIndex

router = APIRouter(tags=["topologie"])

_RELATION_BUCKET = {
    "p2c": "providers",  # le voisin est fournisseur de cet AS
    "c2p": "customers",  # le voisin est client de cet AS
    "p2p": "peerings",
    "s2s": "peerings",  # même organisation : pas de hiérarchie, comme un peering
    "unknown": "unspecified",
}


def _date_range(start: str, end: str) -> list[str]:
    """Chaque jour calendaire entre deux dates ISO, bornes incluses."""
    lo, hi = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
    days = []
    d = lo
    while d <= hi:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def _day_bounds(
    data: DataAccess, asn: int, date_from: datetime | None, date_to: datetime | None
) -> tuple[str, str] | None:
    """Bornes ``(start, end)`` en dates (pas d'horodatages).

    À défaut de bornes explicites, utilise la plage couverte par
    l'ensemble des données BGP curées — jamais celle de cet AS seul : un AS
    qui n'apparaît qu'en fin de fenêtre (ex. un nouveau préfixe) verrait
    sinon sa propre plage se réduire à ces seuls jours, rendant "new"
    indiscernable de "stable" (rien avant = rien à comparer).
    """
    elements = data.table("bgp_elements")
    if not data.exists("bgp_elements"):
        return None
    if date_from and date_to:
        start, end = date_from.date().isoformat(), date_to.date().isoformat()
    else:
        row = data.query(f"SELECT min(ts) AS lo, max(ts) AS hi FROM {elements}")
        if not row or row[0]["lo"] is None:
            return None
        lo, hi = row[0]["lo"], row[0]["hi"]
        start = date_from.date().isoformat() if date_from else lo.date().isoformat()
        end = date_to.date().isoformat() if date_to else hi.date().isoformat()
    exists = data.query(
        f"SELECT 1 FROM {elements} WHERE origin_asn = ? LIMIT 1",
        [asn],
    )
    return (start, end) if exists else None


@router.get("/asns/{asn}/prefixes/timeseries", summary="Nombre de préfixes annoncés par jour")
def asn_prefixes_timeseries(
    asn: int,
    family: str = Query("all", pattern="^(all|4|6)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    elements = data.table("bgp_elements")
    conditions = ["origin_asn = ?"]
    params: list[object] = [asn]
    if date_from:
        conditions.append("ts >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("ts <= ?")
        params.append(date_to)
    if family != "all":
        conditions.append("prefix_ip_version = ?")
        params.append(int(family))

    rows = data.query(
        f"""SELECT date_trunc('day', ts) AS day, count(DISTINCT prefix) AS n
            FROM {elements} WHERE {" AND ".join(conditions)}
            GROUP BY 1 ORDER BY 1""",
        params,
    )
    return {
        "asn": asn,
        "family": family,
        "points": [{"day": r["day"].date().isoformat(), "prefixes": int(r["n"])} for r in rows],
    }


@router.get("/asns/{asn}/prefixes/changes", summary="Préfixes apparus/disparus/instables")
def asn_prefixes_changes(
    asn: int,
    tab: str = Query("all", pattern="^(all|new|left|unstable)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    bounds = _day_bounds(data, asn, date_from, date_to)
    if bounds is None:
        return {"asn": asn, "start": None, "end": None, "items": []}
    start, end = bounds

    elements = data.table("bgp_elements")
    rows = data.query(
        f"""SELECT DISTINCT prefix, strftime(ts, '%Y-%m-%d') AS day
            FROM {elements}
            WHERE origin_asn = ? AND ts >= ? AND ts <= ?""",
        [asn, start, end + "T23:59:59"],
    )
    # Tous les jours de la fenêtre, pas seulement ceux où une annonce existe
    # pour cet AS : un préfixe absent en tout début ou toute fin de fenêtre
    # ne produit aucune ligne pour ces jours-là, et le comparer seulement aux
    # jours où *quelque chose* a été vu le ferait passer à tort pour stable.
    all_days = _date_range(start, end)
    by_prefix: dict[str, list[str]] = {}
    for r in rows:
        by_prefix.setdefault(r["prefix"], []).append(r["day"])

    has_roa = (
        {r["prefix"] for r in data.query(f"SELECT DISTINCT prefix FROM {data.table('ref_roa')}")}
        if data.exists("ref_roa")
        else set()
    )
    has_route_object = (
        {
            r["prefix"]
            for r in data.query(f"SELECT DISTINCT prefix FROM {data.table('ref_irr_route')}")
        }
        if data.exists("ref_irr_route")
        else set()
    )

    items: list[dict[str, Any]] = []
    for prefix, seen in by_prefix.items():
        seen.sort()
        change = classify_presence(seen, all_days, all_days[0], all_days[-1])
        if tab != "all" and change != tab:
            continue
        items.append(
            {
                "prefix": prefix,
                "active": all_days[-1] in seen,
                "change": change,
                "first_seen": seen[0],
                "last_seen": seen[-1],
                "has_roa": prefix in has_roa,
                "has_route_object": prefix in has_route_object,
            }
        )
    items.sort(key=lambda i: i["prefix"])
    return {"asn": asn, "start": start, "end": end, "items": items}


@router.get("/asns/{asn}/neighbors", summary="Voisins BGP directs, par type de relation")
def asn_neighbors(
    asn: int,
    relation: str = Query("all", pattern="^(all|providers|customers|peerings|unspecified)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    bounds = _day_bounds(data, asn, date_from, date_to)
    if bounds is None:
        return {"asn": asn, "start": None, "end": None, "items": []}
    start, end = bounds

    elements = data.table("bgp_elements")
    conditions = ["list_contains(as_path_dedup, ?)", "ts >= ?", "ts <= ?"]
    params: list[object] = [asn, start, end + "T23:59:59"]
    rows = data.query(
        f"""SELECT as_path_dedup, prefix_ip_version, strftime(ts, '%Y-%m-%d') AS day
            FROM {elements} WHERE {" AND ".join(conditions)}""",
        params,
    )

    # Un voisin direct est l'AS immédiatement adjacent à `asn` dans un
    # chemin observé — pas de complétion vers des AS non vus sur un chemin
    # réel (voir ADR 0004, même principe pour le futur graphe de nœuds).
    neighbors: dict[int, dict[str, Any]] = {}
    for r in rows:
        path: list[int] = r["as_path_dedup"]
        try:
            i = path.index(asn)
        except ValueError:
            continue
        for j in (i - 1, i + 1):
            if not (0 <= j < len(path)) or path[j] == asn:
                continue
            n = path[j]
            entry = neighbors.setdefault(n, {"days": set(), "v4": 0, "v6": 0})
            entry["days"].add(r["day"])
            if r["prefix_ip_version"] == 4:
                entry["v4"] += 1
            else:
                entry["v6"] += 1

    index = RelationshipIndex(
        _load_reference(data.settings, "ref_as_rel"),
        _load_reference(data.settings, "ref_as_rel_evidence"),
    )
    countries = {
        int(r["asn"]): r["country_iso2"]
        for r in (
            data.query(f"SELECT asn, country_iso2 FROM {data.table('ref_asn')}")
            if data.exists("ref_asn")
            else []
        )
    }
    names = org_names(data, neighbors.keys())

    items: list[dict[str, Any]] = []
    for n, entry in neighbors.items():
        bucket = _RELATION_BUCKET[index.get(n, asn).value]
        if relation != "all" and bucket != relation:
            continue
        days = sorted(entry["days"])
        items.append(
            {
                "asn": n,
                "as_name": names.get(n),
                "country_iso2": countries.get(n),
                "relation": bucket,
                "active": days[-1] == end,
                "has_v4": entry["v4"] > 0,
                "has_v6": entry["v6"] > 0,
                "v4_prefixes": entry["v4"],
                "v6_prefixes": entry["v6"],
                "first_seen": days[0],
                "last_seen": days[-1],
            }
        )
    items.sort(key=lambda i: i["asn"])
    return {"asn": asn, "start": start, "end": end, "items": items}


def _current_origins(data: DataAccess, prefix: str) -> set[int]:
    """Origine(s) BGP actuellement observée(s) pour ce préfixe (dernier jour
    disponible), pour la colonne ``match`` des historiques ROA/Route Object.
    """
    if not data.exists("bgp_elements"):
        return set()
    elements = data.table("bgp_elements")
    rows = data.query(
        f"""SELECT DISTINCT origin_asn FROM {elements}
            WHERE prefix = ? AND origin_asn IS NOT NULL
              AND ts >= (SELECT max(ts) FROM {elements}) - INTERVAL 1 DAY""",
        [prefix],
    )
    return {int(r["origin_asn"]) for r in rows}


@router.get("/prefixes/{prefix:path}/roa-history", summary="Historique des ROA d'un préfixe")
def prefix_roa_history(
    prefix: str,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    dates = snapshot_dates(
        data.settings.reference_dir,
        "ref_roa",
        (date_from.date().isoformat() if date_from else "0000-01-01"),
        (date_to.date().isoformat() if date_to else "9999-12-31"),
    )
    if not dates:
        return {"prefix": prefix, "items": []}
    current = _current_origins(data, prefix)
    rows = diff_entities(
        data.settings.reference_dir,
        "ref_roa",
        ["prefix", "asn", "max_len", "ta"],
        dates[0],
        dates[-1],
        filters={"prefix": prefix},
    )
    for r in rows:
        r["match"] = int(r["asn"]) in current
    return {"prefix": prefix, "items": rows}


@router.get(
    "/prefixes/{prefix:path}/route-object-history",
    summary="Historique des objets route (IRR) d'un préfixe",
)
def prefix_route_object_history(
    prefix: str,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    dates = snapshot_dates(
        data.settings.reference_dir,
        "ref_irr_route",
        (date_from.date().isoformat() if date_from else "0000-01-01"),
        (date_to.date().isoformat() if date_to else "9999-12-31"),
    )
    if not dates:
        return {"prefix": prefix, "items": []}
    current = _current_origins(data, prefix)
    rows = diff_entities(
        data.settings.reference_dir,
        "ref_irr_route",
        ["prefix", "asn", "source"],
        dates[0],
        dates[-1],
        filters={"prefix": prefix},
    )
    for r in rows:
        r["match"] = int(r["asn"]) in current
    return {"prefix": prefix, "items": rows}
