"""Générateur de jeu de données synthétique.

Objectif : permettre de lancer la plateforme entière sans télécharger un seul
octet, et fournir aux tests un jeu contenant des anomalies **connues à
l'avance**, ce qui rend la détection vérifiable.

Les numéros d'AS sont pris dans des plages réellement gérées par AFRINIC pour
que les jointures de référentiel soient réalistes, mais **les noms d'opérateurs
sont fictifs** : ce jeu ne décrit aucun réseau réel et ne doit jamais être
présenté comme une observation.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from abrip.etl.normalize import to_element_dict


@dataclass(frozen=True, slots=True)
class SyntheticAsn:
    asn: int
    name: str
    country: str
    prefixes: tuple[str, ...]
    upstreams: tuple[int, ...]


# Opérateurs fictifs, ASN dans les plages AFRINIC, préfixes dans les blocs AFRINIC.
AFRICAN_ASNS: tuple[SyntheticAsn, ...] = (
    SyntheticAsn(
        37100, "Littoral Telecom (fictif)", "CM", ("197.155.64.0/22", "102.22.8.0/22"), (3320, 6939)
    ),
    # AS jumeau de 37100 (même organisation, cf. ref_as_org ci-dessous) : les
    # deux annoncent "102.22.8.0/22" tout au long du jeu de données. Sans le
    # filtre "même organisation" du détecteur MOAS (L6), ce multihoming
    # ordinaire produirait un événement MOAS en continu — c'est le cas que
    # tests/test_detection.py::test_meme_organisation_non_signalee vérifie.
    SyntheticAsn(37105, "Littoral Telecom Backup (fictif)", "CM", ("102.22.8.0/22",), (3320, 6939)),
    SyntheticAsn(37200, "Wouri Networks (fictif)", "CM", ("196.216.32.0/20",), (3320,)),
    SyntheticAsn(
        36900, "Sahel Connect (fictif)", "SN", ("105.16.0.0/16", "196.1.96.0/20"), (6939, 174)
    ),
    SyntheticAsn(37300, "Rift Valley IP (fictif)", "KE", ("197.248.0.0/16",), (174, 3320)),
    SyntheticAsn(
        36800, "Gulf of Guinea Net (fictif)", "GH", ("102.176.0.0/14",), (6939, 3320, 174)
    ),
    SyntheticAsn(
        37400, "Cape Fibre (fictif)", "ZA", ("196.60.0.0/18", "105.184.0.0/13"), (3320, 174, 6939)
    ),
    SyntheticAsn(37500, "Nile Backbone (fictif)", "EG", ("197.32.0.0/13",), (174,)),
    SyntheticAsn(
        36700,
        "Atlantic Ridge (fictif)",
        "NG",
        ("102.64.0.0/12", "197.210.0.0/15"),
        (6939, 3320, 174),
    ),
)

# Transitaires internationaux, designes par leur numero uniquement.
TRANSIT_ASNS: tuple[int, ...] = (174, 3320, 6939, 2914)

COLLECTOR_PEERS: dict[str, tuple[int, ...]] = {
    "route-views.napafrica": (37400, 36700, 37300, 3320, 6939),
    "rrc19": (37400, 37100, 36900, 174),
    "route-views2": (174, 3320, 2914, 6939),
    "rrc00": (174, 6939, 2914),
}

PEER_IPS = {
    asn: f"196.60.{asn % 250}.{(asn // 7) % 250}"
    for asn in [a.asn for a in AFRICAN_ASNS] + list(TRANSIT_ASNS)
}


@dataclass(frozen=True, slots=True)
class PlantedAnomaly:
    """Anomalie injectée volontairement, avec son étiquette de vérité terrain."""

    kind: str
    prefix: str
    day_offset: int
    hour: int
    detail: dict[str, Any]


PLANTED: tuple[PlantedAnomaly, ...] = (
    PlantedAnomaly(
        kind="moas",
        prefix="197.155.64.0/22",
        day_offset=3,
        hour=9,
        detail={"legitimate_origin": 37100, "hijacking_origin": 45090, "duration_hours": 4},
    ),
    PlantedAnomaly(
        kind="subprefix",
        prefix="197.248.160.0/20",
        day_offset=5,
        hour=14,
        detail={
            "covering": "197.248.0.0/16",
            "legitimate_origin": 37300,
            "hijacking_origin": 45090,
            "duration_hours": 2,
        },
    ),
    PlantedAnomaly(
        kind="valley_free",
        prefix="102.64.0.0/12",
        day_offset=4,
        hour=11,
        detail={
            "leaker": 36800,
            "victim_origin": 36700,
            "path": [3320, 36800, 174, 36700],
            "duration_hours": 3,
        },
    ),
    PlantedAnomaly(
        kind="churn_spike",
        prefix="196.60.0.0/18",
        day_offset=6,
        hour=2,
        detail={"multiplier": 25, "duration_hours": 3},
    ),
    PlantedAnomaly(
        kind="visibility_drop",
        prefix="197.32.0.0/13",
        day_offset=6,
        hour=15,
        detail={"remaining_peer_ratio": 0.25, "duration_hours": 6},
    ),
)

BASE_DATE = datetime(2026, 8, 24)
DEFAULT_DAYS = 7


def _origin_path(asn: SyntheticAsn, peer: int, rng: random.Random) -> list[int]:
    if peer == asn.asn:
        return [asn.asn]
    upstream = rng.choice(asn.upstreams)
    if peer in TRANSIT_ASNS:
        if peer == upstream:
            return [peer, asn.asn]
        return [peer, upstream, asn.asn]
    return [peer, rng.choice(asn.upstreams), upstream, asn.asn]


def generate_day(
    collector: str, day: datetime, seed: int = 42, source_file: str = "synthetic"
) -> Iterator[dict[str, Any]]:
    """Produit les éléments BGP d'une journée pour un collecteur."""
    rng = random.Random(f"{collector}-{day:%Y%m%d}-{seed}")
    peers = COLLECTOR_PEERS.get(collector, COLLECTOR_PEERS["rrc00"])
    day_offset = (day.date() - BASE_DATE.date()).days

    planted_by_hour: dict[int, list[PlantedAnomaly]] = {}
    for anomaly in PLANTED:
        if anomaly.day_offset != day_offset:
            continue
        span = int(anomaly.detail.get("duration_hours", 1))
        for hour in range(anomaly.hour, min(24, anomaly.hour + span)):
            planted_by_hour.setdefault(hour, []).append(anomaly)

    for hour in range(24):
        active = planted_by_hour.get(hour, [])
        hidden = {
            a.prefix
            for a in active
            if a.kind == "visibility_drop" and rng.random() > a.detail["remaining_peer_ratio"]
        }

        for operator in AFRICAN_ASNS:
            for prefix in operator.prefixes:
                if prefix in hidden:
                    continue
                boost = next(
                    (
                        a.detail["multiplier"]
                        for a in active
                        if a.kind == "churn_spike" and a.prefix == prefix
                    ),
                    1,
                )
                updates = max(1, int(rng.gauss(2.2, 0.9))) * boost
                for _ in range(updates):
                    peer = rng.choice(peers)
                    minute = rng.randrange(60)
                    ts = day + timedelta(hours=hour, minutes=minute, seconds=rng.randrange(60))
                    withdraw = rng.random() < 0.18
                    record = to_element_dict(
                        timestamp=ts,
                        collector=collector,
                        peer_asn=peer,
                        peer_ip=PEER_IPS.get(peer, "0.0.0.0"),
                        elem_type="W" if withdraw else "A",
                        prefix=prefix,
                        as_path=None if withdraw else _origin_path(operator, peer, rng),
                        next_hop=None if withdraw else PEER_IPS.get(peer),
                        communities=None,
                        source_file=source_file,
                    )
                    if record:
                        yield record

        for anomaly in active:
            yield from _emit_anomaly(anomaly, collector, day, hour, peers, rng, source_file)


def _emit_anomaly(
    anomaly: PlantedAnomaly,
    collector: str,
    day: datetime,
    hour: int,
    peers: tuple[int, ...],
    rng: random.Random,
    source_file: str,
) -> Iterator[dict[str, Any]]:
    base = day + timedelta(hours=hour)

    if anomaly.kind == "moas":
        bad = anomaly.detail["hijacking_origin"]
        for peer in peers[:3]:
            for repeat in range(4):
                record = to_element_dict(
                    timestamp=base + timedelta(minutes=7 * repeat + rng.randrange(5)),
                    collector=collector,
                    peer_asn=peer,
                    peer_ip=PEER_IPS.get(peer, "0.0.0.0"),
                    elem_type="A",
                    prefix=anomaly.prefix,
                    as_path=[peer, 4809, bad],
                    source_file=source_file,
                )
                if record:
                    yield record

    elif anomaly.kind == "subprefix":
        bad = anomaly.detail["hijacking_origin"]
        for peer in peers[:3]:
            for repeat in range(3):
                record = to_element_dict(
                    timestamp=base + timedelta(minutes=11 * repeat),
                    collector=collector,
                    peer_asn=peer,
                    peer_ip=PEER_IPS.get(peer, "0.0.0.0"),
                    elem_type="A",
                    prefix=anomaly.prefix,
                    as_path=[peer, 4809, bad],
                    source_file=source_file,
                )
                if record:
                    yield record

    elif anomaly.kind == "valley_free":
        path = anomaly.detail["path"]
        for peer in peers[:2]:
            for repeat in range(5):
                record = to_element_dict(
                    timestamp=base + timedelta(minutes=9 * repeat),
                    collector=collector,
                    peer_asn=peer,
                    peer_ip=PEER_IPS.get(peer, "0.0.0.0"),
                    elem_type="A",
                    prefix=anomaly.prefix,
                    as_path=[peer, *path],
                    source_file=source_file,
                )
                if record:
                    yield record


def generate_elements(
    collector: str,
    seed: int = 42,
    source_file: str = "synthetic",
    start: datetime | None = None,
    days: int = 1,
) -> Iterator[dict[str, Any]]:
    origin = start or BASE_DATE
    for offset in range(days):
        yield from generate_day(collector, origin + timedelta(days=offset), seed, source_file)


def generate_rib(collector: str, snapshot: datetime) -> Iterator[dict[str, Any]]:
    """Photographie de table de routage, base du calcul de visibilité."""
    rng = random.Random(f"rib-{collector}-{snapshot:%Y%m%d%H}")
    peers = COLLECTOR_PEERS.get(collector, COLLECTOR_PEERS["rrc00"])
    day_offset = (snapshot.date() - BASE_DATE.date()).days

    hidden: set[str] = set()
    for anomaly in PLANTED:
        if (
            anomaly.kind == "visibility_drop"
            and anomaly.day_offset == day_offset
            and anomaly.hour <= snapshot.hour < anomaly.hour + anomaly.detail["duration_hours"]
        ):
            hidden.add(anomaly.prefix)

    for operator in AFRICAN_ASNS:
        for prefix in operator.prefixes:
            for peer in peers:
                if prefix in hidden and rng.random() > 0.25:
                    continue
                if rng.random() < 0.05:  # visibilite naturellement imparfaite
                    continue
                path = _origin_path(operator, peer, rng)
                yield {
                    "snapshot_ts": snapshot,
                    "collector": collector,
                    "peer_asn": peer,
                    "prefix": prefix,
                    "prefix_ip_version": 6 if ":" in prefix else 4,
                    "prefix_len": int(prefix.split("/")[1]),
                    "origin_asn": operator.asn,
                    "as_path_dedup": path,
                    "as_path_len": len(path),
                }


def reference_frames(snapshot_date: str = "2026-08-30") -> dict[str, list[dict[str, Any]]]:
    """Référentiels cohérents avec le jeu synthétique (ASN, ROA, relations)."""
    asns = [
        {
            "asn": a.asn,
            "country_iso2": a.country,
            "rir": "afrinic",
            "is_african": True,
            "allocation_date": "20050101",
            "snapshot_date": snapshot_date,
        }
        for a in AFRICAN_ASNS
    ] + [
        {
            "asn": t,
            "country_iso2": "US",
            "rir": "arin",
            "is_african": False,
            "allocation_date": "19980101",
            "snapshot_date": snapshot_date,
        }
        for t in (*TRANSIT_ASNS, 4809, 45090)
    ]

    roas = [
        {
            "prefix": prefix,
            "asn": a.asn,
            "max_len": int(prefix.split("/")[1]) + 2,
            "ta": "afrinic",
            "snapshot_date": snapshot_date,
        }
        for a in AFRICAN_ASNS
        for prefix in a.prefixes
    ]

    relations: list[dict[str, Any]] = []
    for a in AFRICAN_ASNS:
        for upstream in a.upstreams:
            relations.append(
                {
                    "as_a": upstream,
                    "as_b": a.asn,
                    "relationship": "p2c",
                    "source": "synthetic",
                    "snapshot_date": snapshot_date,
                }
            )
    for i, left in enumerate(TRANSIT_ASNS):
        for right in TRANSIT_ASNS[i + 1 :]:
            relations.append(
                {
                    "as_a": left,
                    "as_b": right,
                    "relationship": "p2p",
                    "source": "synthetic",
                    "snapshot_date": snapshot_date,
                }
            )
    relations.append(
        {
            "as_a": 4809,
            "as_b": 45090,
            "relationship": "p2c",
            "source": "synthetic",
            "snapshot_date": snapshot_date,
        }
    )

    # L6 — AS2Org synthétique : seuls 37100 et 37105 partagent une organisation,
    # ce qui donne au filtre "même organisation" du détecteur MOAS une donnée
    # réelle à consulter (voir SyntheticAsn 37105 ci-dessus). Les autres AS ne
    # sont volontairement pas renseignés : leur absence doit se traduire par
    # `same_organisation() -> False`, pas par une exception.
    as_org = [
        {
            "asn": 37100,
            "org_id": "LITTORAL-FICTIF-ORG",
            "org_name": "Littoral Telecom (fictif)",
            "snapshot_date": snapshot_date,
        },
        {
            "asn": 37105,
            "org_id": "LITTORAL-FICTIF-ORG",
            "org_name": "Littoral Telecom (fictif)",
            "snapshot_date": snapshot_date,
        },
    ]

    return {"ref_asn": asns, "ref_roa": roas, "ref_as_rel": relations, "ref_as_org": as_org}


def ground_truth() -> list[dict[str, Any]]:
    """Vérité terrain : ce que la détection doit retrouver."""
    return [
        {
            "kind": a.kind,
            "prefix": a.prefix,
            "expected_date": (BASE_DATE + timedelta(days=a.day_offset)).strftime("%Y-%m-%d"),
            "expected_hour": a.hour,
            **a.detail,
        }
        for a in PLANTED
    ]
