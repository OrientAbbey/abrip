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


def _scheduled_path(
    operator: SyntheticAsn, peer: int, rng: random.Random, operators: dict[int, SyntheticAsn]
) -> list[int]:
    """Chemin d'un préfixe à calendrier. Un client (dont l'amont est un autre
    opérateur du jeu) hérite du chemin de son fournisseur, allongé d'un saut :
    il ne se retrouve ainsi jamais directement collé à un pair de collecteur."""
    parent = operators.get(operator.upstreams[0]) if operator.upstreams else None
    if parent is not None and parent.asn != operator.asn and parent.upstreams:
        return [*_origin_path(parent, peer, rng), operator.asn]
    return _origin_path(operator, peer, rng)


# Opérateurs qui n'apparaissent QUE via SCHEDULED_PREFIXES (jamais dans la
# boucle principale, pour ne pas décaler son flux aléatoire). 37110 est un
# client de 37100 : c'est ce qui donne un voisin « customer » à montrer dans
# l'explorateur de voisins BGP. Ses chemins passent par 37100 seul, donc
# restent valley-free (descente uniquement).
EXTRA_ASNS: tuple[SyntheticAsn, ...] = (
    SyntheticAsn(37110, "Douala Broadband (fictif)", "CM", (), (37100,)),
)
ALL_ASNS: tuple[SyntheticAsn, ...] = (*AFRICAN_ASNS, *EXTRA_ASNS)

# Préfixes dont l'activité varie dans le temps, pour que les onglets
# « New / Left / Unstable » et « IPv4 / IPv6 » de l'explorateur de préfixes
# aient chacun un exemple réel à montrer. Chaque entrée :
# (ASN d'origine, préfixe, jours d'activité par rapport à BASE_DATE).
#
# Générés dans une boucle *séparée*, avec leur propre générateur aléatoire :
# les insérer dans la boucle principale décalerait le flux aléatoire de tous
# les préfixes suivants et modifierait en silence des données déjà vérifiées
# (vérité terrain, comptes d'événements).
SCHEDULED_PREFIXES: tuple[tuple[int, str, frozenset[int]], ...] = (
    (37300, "105.20.0.0/22", frozenset({3, 4, 5, 6})),  # new : apparaît au jour 3
    (37300, "105.20.4.0/22", frozenset({0, 1, 2, 3})),  # left : disparaît après le jour 3
    (37100, "102.22.16.0/22", frozenset({0, 1, 3, 5, 6})),  # unstable : va-et-vient
    (37100, "2c0f:fb50::/32", frozenset(range(7))),  # IPv6 stable
    (37100, "2c0f:fb50:100::/40", frozenset({4, 5, 6})),  # IPv6 new
    (37110, "102.30.0.0/22", frozenset(range(7))),  # préfixe du client 37110
)


def scheduled_prefixes_of(asn: int) -> tuple[str, ...]:
    return tuple(prefix for owner, prefix, _ in SCHEDULED_PREFIXES if owner == asn)


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

        scheduled_rng = random.Random(f"{collector}-{day:%Y%m%d}-{hour}-{seed}-scheduled")
        operators = {a.asn: a for a in ALL_ASNS}
        for owner, prefix, active_days in SCHEDULED_PREFIXES:
            if day_offset not in active_days:
                continue
            operator = operators[owner]
            for _ in range(max(1, int(scheduled_rng.gauss(2.2, 0.9)))):
                peer = scheduled_rng.choice(peers)
                ts = day + timedelta(
                    hours=hour,
                    minutes=scheduled_rng.randrange(60),
                    seconds=scheduled_rng.randrange(60),
                )
                record = to_element_dict(
                    timestamp=ts,
                    collector=collector,
                    peer_asn=peer,
                    peer_ip=PEER_IPS.get(peer, "0.0.0.0"),
                    elem_type="A",
                    prefix=prefix,
                    as_path=_scheduled_path(operator, peer, scheduled_rng, operators),
                    next_hop=PEER_IPS.get(peer),
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
        # Fin de l'incident : les pairs reviennent à l'origine légitime, sans
        # quoi le rejeu de propagation garderait le détournement indéfiniment
        # (un pair conserve son dernier chemin tant qu'il n'en annonce pas un
        # autre). Décalage fixe par pair et rng local : la séquence aléatoire
        # principale, donc le reste de la démo, n'est pas décalée.
        end = base + timedelta(hours=anomaly.detail["duration_hours"])
        legit = next(a for a in AFRICAN_ASNS if a.asn == anomaly.detail["legitimate_origin"])
        for offset, peer in enumerate(peers[:3]):
            record = to_element_dict(
                timestamp=end + timedelta(minutes=offset),
                collector=collector,
                peer_asn=peer,
                peer_ip=PEER_IPS.get(peer, "0.0.0.0"),
                elem_type="A",
                prefix=anomaly.prefix,
                as_path=_origin_path(legit, peer, random.Random(peer)),  # rng local
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
        for a in ALL_ASNS
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
        for a in ALL_ASNS
        for prefix in (*a.prefixes, *scheduled_prefixes_of(a.asn))
    ]

    relations: list[dict[str, Any]] = []
    for a in ALL_ASNS:
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

    # L6 — AS2Org synthétique : seuls 37100 et 37105 partagent une organisation
    # (le couple jumeau ci-dessus), ce qui donne au filtre "même organisation"
    # du détecteur MOAS une donnée réelle à consulter ; chaque autre AS a sa
    # propre organisation, donc `same_organisation() -> False`.
    # `asn_name` (nom court) est ajouté pour TOUS les opérateurs et transitaires
    # afin que l'affichage "AS{numéro} · {nom}" ait quelque chose à montrer
    # partout dans l'interface. 174/3320/6939/2914 sont de vrais transitaires
    # (Cogent, Deutsche Telekom, Hurricane Electric, NTT) : leurs noms courts
    # sont réels, à but illustratif dans ce jeu de données par ailleurs fictif.
    # 4809 et 45090, utilisés comme AS "détourneur" dans les scénarios plantés,
    # restent volontairement sans nom : associer un nom réel à un rôle fictif
    # de détournement serait trompeur.
    def _slug(name: str) -> str:
        return name.replace(" (fictif)", "").upper().replace(" ", "-")

    as_org = [
        {
            "asn": a.asn,
            "asn_name": _slug(a.name),
            "org_id": f"ORG-{a.asn}",
            "org_name": a.name,
            "snapshot_date": snapshot_date,
        }
        for a in ALL_ASNS
    ]
    as_org[0]["org_id"] = as_org[1]["org_id"] = "LITTORAL-FICTIF-ORG"

    TRANSIT_NAMES = {174: "COGENT-174", 3320: "DTAG", 6939: "HURRICANE", 2914: "NTTAMERICA"}
    as_org.extend(
        {
            "asn": asn,
            "asn_name": name,
            "org_id": name,
            "org_name": None,
            "snapshot_date": snapshot_date,
        }
        for asn, name in TRANSIT_NAMES.items()
    )

    return {"ref_asn": asns, "ref_roa": roas, "ref_as_rel": relations, "ref_as_org": as_org}


def historical_reference_snapshots() -> dict[str, list[dict[str, Any]]]:
    """Instantanés datés antérieurs, pour que les modales « RPKI ROA History »
    et « Route Object History » de l'explorateur de préfixes aient un vrai
    historique à montrer.

    En production, cet historique s'accumule naturellement à chaque
    ``abrip reference sync`` exécuté un jour différent (voir
    ``reference.sync.sync_rpki``/``sync_irr``, qui écrivent chacun un
    instantané daté sous ``reference/history/``). Le jeu de démonstration
    n'exécute qu'un seul cycle de synchronisation : sans cette fonction, les
    deux modales n'auraient donc qu'une seule ligne à afficher. Les deux cas
    choisis sont volontairement différents l'un de l'autre :
      - le ROA de 37200 sur "196.216.32.0/20" se resserre (maxLength 24 → 22),
        un resserrement de sécurité authentique et fréquent en production ;
      - l'objet route IRR de 37400 sur "196.60.0.0/18" reste inchangé sur
        toute la période, l'autre cas courant (un enregistrement ancien,
        jamais retouché).
    """
    early = (BASE_DATE).date().isoformat()
    late = (BASE_DATE + timedelta(days=4)).date().isoformat()

    roa_early = [
        {
            "prefix": "196.216.32.0/20",
            "asn": 37200,
            "max_len": 24,
            "ta": "afrinic",
            "snapshot_date": early,
        }
    ]
    roa_late = [
        {
            "prefix": "196.216.32.0/20",
            "asn": 37200,
            "max_len": 22,
            "ta": "afrinic",
            "snapshot_date": late,
        }
    ]
    irr_route = [
        {
            "prefix": "196.60.0.0/18",
            "asn": 37400,
            "source": "RADB",
            "snapshot_date": early,
        }
    ]
    irr_route_late = [
        {
            "prefix": "196.60.0.0/18",
            "asn": 37400,
            "source": "RADB",
            "snapshot_date": late,
        }
    ]
    return {
        f"history/ref_roa/date={early}": roa_early,
        f"history/ref_roa/date={late}": roa_late,
        f"history/ref_irr_route/date={early}": irr_route,
        f"history/ref_irr_route/date={late}": irr_route_late,
        # Version courante : la dernière connue, pour que le bouton "Route
        # Object" du tableau de préfixes affiche "présent" sans détour.
        "ref_irr_route": irr_route_late,
    }


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
