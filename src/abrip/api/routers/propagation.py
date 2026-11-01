"""Graphe de propagation d'un préfixe (ADR 0004) et rejeu dans le temps.

Lecture seule, comme le reste de l'API. Le graphe est « réduit » : seuls les
AS effectivement vus sur un chemin observé pour le préfixe y figurent.
Portage depuis la branche dev_cl5 ; les noms d'AS viennent de ``ref_as_org``
(``asn_name`` = nom court CAIDA, ``org_name`` = nom complet de l'organisation).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

from fastapi import APIRouter, Depends, Query

from abrip.analytics.metrics import _load_reference
from abrip.analytics.replay import ReplayEvent, effective_step, orient_path, replay
from abrip.api.deps import DataAccess, get_data_access
from abrip.reference.relationships import RelationshipIndex, valley_free_violation
from abrip.reference.rpki import RpkiValidator

router = APIRouter(tags=["propagation"])

_RELATION_BUCKET = {
    "p2c": "providers",  # le voisin est fournisseur de cet AS
    "c2p": "customers",  # le voisin est client de cet AS
    "p2p": "peerings",
    "s2s": "peerings",  # même organisation : pas de hiérarchie, comme un peering
    "unknown": "unspecified",
}


def _relationship_index(data: DataAccess) -> RelationshipIndex:
    return RelationshipIndex(
        _load_reference(data.settings, "ref_as_rel"),
        _load_reference(data.settings, "ref_as_rel_evidence"),
    )


def _asn_countries(data: DataAccess) -> dict[int, str]:
    if not data.exists("ref_asn"):
        return {}
    return {
        int(r["asn"]): r["country_iso2"]
        for r in data.query(f"SELECT asn, country_iso2 FROM {data.table('ref_asn')}")
    }


def _as_names(data: DataAccess, asns: Iterable[int]) -> dict[int, tuple[str | None, str | None]]:
    """ASN -> (nom court, nom complet de l'organisation), au mieux : beaucoup
    d'AS africains n'ont pas d'entrée AS2Org, le client retombe alors sur le
    numéro seul."""
    ids = sorted(set(asns))
    if not ids or not data.exists("ref_as_org"):
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = data.query(
        f"""SELECT asn, any_value(asn_name) AS asn_name, any_value(org_name) AS org_name
            FROM {data.table("ref_as_org")} WHERE asn IN ({placeholders}) GROUP BY 1""",
        ids,
    )
    return {int(r["asn"]): (r["asn_name"], r["org_name"]) for r in rows}


def _annotate(
    data: DataAccess,
    prefix: str,
    paths: Iterable[tuple[int, ...]],
    index: RelationshipIndex,
    weights: dict[tuple[int, ...], int] | None = None,
) -> tuple[dict[tuple[int, int], int], dict[int, str], set[tuple[int, ...]]]:
    """Surcouches d'anomalie du graphe : (liens fautifs -> observations,
    statut RPKI de chaque origine, chemins qui violent le modèle valley-free).

    Les chemins arrivent orientés origine -> collecteur ; le modèle valley-free
    (relationships.valley_free_violation) lit du collecteur vers l'origine, d'où
    le renversement. Le lien fautif est rendu dans le sens du graphe."""
    roa = _load_reference(data.settings, "ref_roa")
    validator = RpkiValidator.from_frame(roa) if not roa.is_empty() else None
    violations: dict[tuple[int, int], int] = {}
    violating: set[tuple[int, ...]] = set()
    origins: set[int] = set()
    for path in paths:
        if not path:
            continue
        origins.add(path[0])
        seen = list(reversed(path))
        position = valley_free_violation(seen, index)
        if position is None:
            continue
        edge = (seen[position + 1], seen[position])
        violations[edge] = violations.get(edge, 0) + (weights.get(path, 1) if weights else 1)
        violating.add(path)
    # Sans aucun ROA chargé, aucune conclusion : « unknown », pas « not-found ».
    rpki = {o: (validator.validate(prefix, o).value if validator else "unknown") for o in origins}
    return violations, rpki, violating


def _node(
    asn: int,
    names: dict[int, tuple[str | None, str | None]],
    countries: dict[int, str],
    rpki: dict[int, str] | None = None,
):
    short, full = names.get(asn, (None, None))
    return {
        "asn": asn,
        "as_name": short or full,
        "org_name": full or short,
        "country_iso2": countries.get(asn),
        # Statut RPKI de l'AS en tant qu'origine de ce préfixe ; absent pour un AS de transit.
        "rpki": (rpki or {}).get(asn),
    }


@router.get(
    "/prefixes/{prefix:path}/propagation",
    summary="Graphe de propagation d'un préfixe (nœuds d'AS) — ADR 0004",
)
def prefix_propagation(
    prefix: str,
    asn: int | None = Query(
        None, description="Restreindre à cette origine (utile si le préfixe a plusieurs)"
    ),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    targets: str | None = Query(
        None,
        description="ASN séparés par des virgules ; chaque chemin est tronqué à la première "
        "cible rencontrée depuis l'origine (au-delà, rien de nouveau à montrer)",
    ),
    max_paths: int = Query(
        10, ge=1, le=100, description="Chemins montrés par nœud dans l'info-bulle"
    ),
    min_observations: int = Query(
        1,
        ge=1,
        description="Seuil de bruit : un chemin vu moins de N fois (messages BGP) est écarté",
    ),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    """Graphe réduit (pas étendu, voir ADR 0004) : seuls les AS effectivement
    vus sur un chemin observé pour ce préfixe apparaissent — aucune
    complétion vers des voisins connus mais non observés.
    """
    empty: dict[str, Any] = {
        "prefix": prefix,
        "asn": asn,
        "start": date_from.date().isoformat() if date_from else None,
        "end": date_to.date().isoformat() if date_to else None,
        "nodes": [],
        "edges": [],
        "paths": [],
        "paths_total": 0,
        "paths_hidden": 0,
        "max_observations": 0,
        "moas": False,
    }
    if not data.exists("bgp_elements"):
        return empty

    elements = data.table("bgp_elements")
    conditions = ["prefix = ?"]
    params: list[Any] = [prefix]
    if asn is not None:
        conditions.append("origin_asn = ?")
        params.append(asn)
    if date_from:
        conditions.append("ts >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("ts <= ?")
        params.append(date_to)
    rows = data.query(
        f"""SELECT as_path_dedup, count(*) AS n FROM {elements}
            WHERE {" AND ".join(conditions)} GROUP BY as_path_dedup""",
        params,
    )

    target_set = {int(t) for t in targets.split(",") if t.strip()} if targets else None
    observed: dict[tuple[int, ...], int] = {}
    for r in rows:
        # `as_path_dedup` va du collecteur vers l'origine (voir
        # etl/pch_parser.py) ; orient_path l'inverse pour raisonner dans le
        # sens de propagation, origine -> collecteur.
        oriented = orient_path(r["as_path_dedup"] or (), None, target_set)
        if oriented is not None:
            # Plusieurs chemins bruts peuvent donner le même chemin une fois
            # tronqué aux cibles : on additionne leurs observations.
            observed[oriented] = observed.get(oriented, 0) + int(r["n"])

    paths_total = len(observed)
    paths = {p: n for p, n in observed.items() if n >= min_observations}
    if not paths:
        return {**empty, "paths_total": paths_total, "paths_hidden": paths_total}

    node_paths: dict[int, list[tuple[int, ...]]] = {}
    node_obs: dict[int, int] = {}
    edge_counts: dict[tuple[int, int], int] = {}  # arête -> observations cumulées
    for path in sorted(paths):
        for node in set(path):
            node_paths.setdefault(node, []).append(path)
            node_obs[node] = node_obs.get(node, 0) + paths[path]
        for a, b in pairwise(path):
            edge_counts[(a, b)] = edge_counts.get((a, b), 0) + paths[path]

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
    names = _as_names(data, node_paths.keys())

    violations, origin_rpki, violating = _annotate(data, prefix, paths, index, paths)

    nodes = [
        {
            **_node(node, names, countries, origin_rpki),
            "paths": [list(p) for p in node_path_list[:max_paths]],
            "hidden_paths": max(0, len(node_path_list) - max_paths),
            "observations": node_obs[node],
        }
        for node, node_path_list in sorted(node_paths.items())
    ]
    edges = [
        {
            "source": a,
            "target": b,
            "relation": _RELATION_BUCKET[index.get(b, a).value],
            "observations": edge_counts[(a, b)],
            "violation_observations": violations.get((a, b), 0),
        }
        for a, b in sorted(edge_counts)
    ]
    # Liste complète (export CSV) : plafonnée pour garder la réponse légère.
    ranked = sorted(paths.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "prefix": prefix,
        "asn": asn,
        "start": date_from.date().isoformat() if date_from else None,
        "end": date_to.date().isoformat() if date_to else None,
        "nodes": nodes,
        "edges": edges,
        "paths": [
            {"path": list(p), "observations": n, "valley_violation": p in violating}
            for p, n in ranked[:500]
        ],
        "moas": len(origin_rpki) > 1,
        "paths_total": paths_total,
        "paths_hidden": paths_total - len(paths),
        "max_observations": max(edge_counts.values()),
    }


REPLAY_MAX_DAYS = 7
REPLAY_WARMUP = timedelta(days=1)
# Bornes de la liste de chemins du rejeu : au-delà, on l'omet (voir `paths`).
REPLAY_MAX_PATHS = 3000
REPLAY_MAX_PATH_REFS = 400_000  # somme, sur les tranches, des chemins actifs


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.get(
    "/prefixes/{prefix:path}/propagation/replay",
    summary="Rejeu de la propagation d'un préfixe sur une tranche de temps",
)
def prefix_propagation_replay(
    prefix: str,
    asn: int | None = Query(None, description="Restreindre à cette origine"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    targets: str | None = Query(None, description="ASN séparés par des virgules (troncature)"),
    step: int = Query(15, ge=1, le=1440, description="Pas d'une tranche, en minutes"),
    max_frames: int = Query(200, ge=10, le=500, description="Nombre maximal de tranches"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    """Une tranche par pas de temps, chacune portant l'état du graphe à sa
    fin (voir ``analytics/replay.py``). Les nœuds et arêtes sont l'union de
    toutes les tranches : le client calcule une disposition unique, les
    tranches ne listent que ce qui est actif à cet instant.

    La fenêtre est bornée à ``REPLAY_MAX_DAYS`` jours (``clamped``), et le pas
    élargi si besoin pour rester sous ``max_frames`` (``step_minutes`` donne
    le pas réellement utilisé). L'état est amorcé avec ``REPLAY_WARMUP`` avant
    le début : un pair silencieux depuis plus longtemps est absent au départ.
    """
    empty: dict[str, Any] = {
        "prefix": prefix,
        "asn": asn,
        "start": None,
        "end": None,
        "step_minutes": step,
        "warmup_hours": int(REPLAY_WARMUP.total_seconds() // 3600),
        "clamped": False,
        "nodes": [],
        "edges": [],
        "paths": [],
        "frames": [],
    }
    if not data.exists("bgp_elements"):
        return empty
    elements = data.table("bgp_elements")
    bounds = data.query(
        f"SELECT min(ts) AS lo, max(ts) AS hi FROM {elements} WHERE prefix = ?", [prefix]
    )
    if not bounds or bounds[0]["lo"] is None:
        return empty

    start = _utc(date_from) or _utc(bounds[0]["lo"])
    end = _utc(date_to) or _utc(bounds[0]["hi"])
    assert start is not None and end is not None
    if end <= start:
        return empty
    clamped = end - start > timedelta(days=REPLAY_MAX_DAYS)
    if clamped:
        start = end - timedelta(days=REPLAY_MAX_DAYS)
    step_td = effective_step(end - start, timedelta(minutes=step), max_frames)

    rows = data.query(
        f"""SELECT ts, elem_type, collector, peer_ip, as_path_dedup FROM {elements}
            WHERE prefix = ? AND ts >= ? AND ts <= ? ORDER BY ts""",
        [prefix, start - REPLAY_WARMUP, end],
    )
    events = [
        ReplayEvent(
            ts=_utc(r["ts"]) or start,
            kind=r["elem_type"],
            peer=(str(r["collector"]), str(r["peer_ip"])),
            path=tuple(r["as_path_dedup"] or ()),
        )
        for r in rows
    ]
    target_set = {int(t) for t in targets.split(",") if t.strip()} if targets else None
    frames = replay(events, start, end, step_td, origin=asn, targets=target_set)

    all_edges = sorted({e for f in frames for path in f.paths for e in pairwise(path)})
    edge_index = {e: i for i, e in enumerate(all_edges)}
    all_nodes = sorted({n for f in frames for path in f.paths for n in path})

    index = _relationship_index(data)
    countries = _asn_countries(data)
    names = _as_names(data, all_nodes)
    path_list = sorted({path for f in frames for path in f.paths})
    path_id = {path: i for i, path in enumerate(path_list)}
    distinct = [list(path) for path in path_list]
    with_paths = (
        len(path_list) <= REPLAY_MAX_PATHS
        and sum(len(f.paths) for f in frames) <= REPLAY_MAX_PATH_REFS
    )
    violations, origin_rpki, _ = _annotate(
        data, prefix, {path for f in frames for path in f.paths}, index
    )

    return {
        **empty,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step_minutes": int(step_td.total_seconds() // 60),
        "clamped": clamped,
        "nodes": [_node(n, names, countries, origin_rpki) for n in all_nodes],
        "edges": [
            {
                "source": a,
                "target": b,
                "relation": _RELATION_BUCKET[index.get(b, a).value],
                "violation_observations": violations.get((a, b), 0),
            }
            for a, b in all_edges
        ],
        # Chemins distincts de la fenêtre, et ceux de chaque tranche par indice :
        # le client met en évidence exactement les chemins actifs qui traversent
        # un AS. Au-delà de la borne, on omet la liste plutôt que de gonfler la
        # réponse ; le client se rabat alors sur les liens directs de l'AS.
        "paths": distinct if with_paths else None,
        "frames": [
            {
                "ts": f.ts.isoformat(),
                "announcements": f.announcements,
                "withdrawals": f.withdrawals,
                "path_count": len(f.paths),
                "nodes": sorted({n for path in f.paths for n in path}),
                "edges": sorted({edge_index[e] for path in f.paths for e in pairwise(path)}),
                **({"path_ids": sorted(path_id[p] for p in f.paths)} if with_paths else {}),
            }
            for f in frames
        ],
    }


def _auto_bucket_hours(span: timedelta) -> int:
    """Pas de la courbe selon la durée : assez fin pour voir un basculement,
    assez large pour que la courbe reste lisible (une quarantaine de barres)."""
    days = span.total_seconds() / 86400
    for limit, hours in ((1.5, 1), (4, 3), (8, 6), (16, 12)):
        if days <= limit:
            return hours
    return 24


@router.get(
    "/prefixes/{prefix:path}/upstreams",
    summary="Fournisseurs amont d'un préfixe dans le temps (pairs qui le voient via chacun)",
)
def prefix_upstreams(
    prefix: str,
    asn: int | None = Query(None, description="Restreindre à cette origine"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    bucket_hours: int | None = Query(None, ge=1, le=168, description="Pas ; auto si absent"),
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    """Pour chaque tranche de temps, le nombre de pairs (collecteur, adresse) qui
    ont annoncé le préfixe par un chemin dont l'avant-dernier AS — le voisin de
    l'origine, côté collecteur — est tel fournisseur. Un basculement de
    fournisseur y est visible comme une barre qui en remplace une autre.

    Les chemins d'un seul AS (l'origine est elle-même le pair) n'ont pas de
    fournisseur amont observable et sont ignorés."""
    empty: dict[str, Any] = {
        "prefix": prefix,
        "asn": asn,
        "bucket_hours": bucket_hours or 0,
        "upstreams": [],
        "points": [],
    }
    if not data.exists("bgp_elements"):
        return empty
    elements = data.table("bgp_elements")
    conditions = ["prefix = ?", "elem_type = 'A'", "len(as_path_dedup) >= 2"]
    params: list[Any] = [prefix]
    if asn is not None:
        conditions.append("as_path_dedup[-1] = ?")
        params.append(asn)
    if date_from:
        conditions.append("ts >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("ts <= ?")
        params.append(date_to)
    where = " AND ".join(conditions)

    # Un seul parcours des données : (heure, fournisseur, collecteur, adresse) distincts.
    # Au plus quelques dizaines de milliers de lignes même sur de gros volumes ; la
    # tranche choisie (6 h, 24 h…) se calcule ensuite ici. C'est exact : compter des
    # pairs distincts par tranche exige les pairs eux-mêmes, pas des comptes horaires
    # (un pair vu à 1 h et à 4 h compte pour 1 dans la tranche 0-6 h, pas pour 2).
    rows = data.query(
        f"""SELECT time_bucket(to_hours(1), ts) AS hour, as_path_dedup[-2] AS upstream,
                   collector, peer_ip
            FROM {elements} WHERE {where} GROUP BY ALL""",
        params,
    )
    if not rows:
        return empty
    hours_seen = [_utc(r["hour"]) for r in rows]
    lo, hi = min(hours_seen), max(hours_seen)  # type: ignore[type-var]
    hours = bucket_hours or _auto_bucket_hours(hi - lo)  # type: ignore[operator]

    # Mêmes tranches que `time_bucket(to_hours(h), ts)` : alignées sur le lundi
    # 3 janvier 2000, l'origine de DuckDB pour les pas en heures.
    origin = datetime(2000, 1, 3, tzinfo=UTC)

    def bucket_of(moment: datetime) -> datetime:
        elapsed = int((moment - origin).total_seconds() // 3600)
        return origin + timedelta(hours=(elapsed // hours) * hours)

    pairs: dict[datetime, dict[int, set[tuple[str, str]]]] = {}
    for r, hour in zip(rows, hours_seen, strict=True):
        assert hour is not None
        pairs.setdefault(bucket_of(hour), {}).setdefault(int(r["upstream"]), set()).add(
            (r["collector"], r["peer_ip"])
        )
    by_bucket = {b: {u: len(peers) for u, peers in ups.items()} for b, ups in pairs.items()}
    totals: dict[int, int] = {}
    for ups in by_bucket.values():
        for u, n in ups.items():
            totals[u] = max(totals.get(u, 0), n)

    ranked = sorted(totals, key=lambda u: (-totals[u], u))
    names = _as_names(data, ranked)
    # Toutes les tranches de la première à la dernière, zéro compris : une tranche
    # sans annonce doit se voir comme un creux, pas être sautée.
    first, last = min(by_bucket), max(by_bucket)
    points = []
    cursor = first
    while cursor <= last:
        seen = by_bucket.get(cursor, {})
        points.append(
            {"ts": cursor.isoformat(), "values": {f"as{u}": seen.get(u, 0) for u in ranked}}
        )
        cursor += timedelta(hours=hours)
    return {
        **empty,
        "bucket_hours": hours,
        "upstreams": [
            {
                "asn": u,
                "as_name": (names.get(u) or (None, None))[0] or (names.get(u) or (None, None))[1],
                "peak_peers": totals[u],
            }
            for u in ranked
        ],
        "points": points,
    }
