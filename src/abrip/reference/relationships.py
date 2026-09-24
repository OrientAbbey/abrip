"""Relations entre AS (CAIDA serial-2) et modèle valley-free.

Format CAIDA : ``<as_a>|<as_b>|<relation>`` avec ``0`` = peer-to-peer et
``-1`` = ``as_a`` est le fournisseur de ``as_b``.

Limite assumée : ces relations sont **inférées**, pas déclarées. Une violation
détectée peut donc résulter d'une inférence erronée, ce qui justifie de ne
jamais présenter une fuite de routes comme un fait.
"""

from __future__ import annotations

import bz2
from datetime import date
from pathlib import Path

import polars as pl

from abrip.logging_conf import get_logger
from abrip.models import REF_AS_REL_SCHEMA, Confidence, Relationship

log = get_logger(__name__)


def parse_as_rel(path: Path, snapshot_date: date | None = None) -> pl.DataFrame:
    opener = bz2.open if path.suffix == ".bz2" else open
    records: list[dict] = []
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            parts = line.strip().split("|")
            if len(parts) < 3:
                continue
            try:
                as_a, as_b, code = int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                continue
            relationship = Relationship.P2P.value if code == 0 else Relationship.P2C.value
            records.append(
                {
                    "as_a": as_a,
                    "as_b": as_b,
                    "relationship": relationship,
                    "source": "caida-serial2",
                    "snapshot_date": (snapshot_date or date.today()).isoformat(),
                }
            )
    frame = (
        pl.DataFrame(records, schema=REF_AS_REL_SCHEMA)
        if records
        else pl.DataFrame(schema=REF_AS_REL_SCHEMA)
    )
    log.info("relations AS chargées", extra={"rows": frame.height})
    return frame


class RelationshipIndex:
    """Recherche de la relation entre deux AS, dans les deux sens.

    Accepte en option une table de corroboration (``ref_as_rel_evidence``,
    produite par ``abrip.reference.peeringdb.build_relationship_evidence``) :
    quand elle est fournie, chaque lien porte la liste des sources qui
    s'accordent, et ``confidence()`` distingue une relation confirmée par
    PeeringDB ou l'IRR d'une relation où CAIDA est seul à trancher (L3).
    """

    def __init__(self, frame: pl.DataFrame, evidence: pl.DataFrame | None = None) -> None:
        self._map: dict[tuple[int, int], Relationship] = {}
        self._sources: dict[tuple[int, int], frozenset[str]] = {}
        for row in frame.iter_rows(named=True):
            a, b = int(row["as_a"]), int(row["as_b"])
            rel = Relationship(row["relationship"])
            if rel is Relationship.P2P:
                self._map[(a, b)] = Relationship.P2P
                self._map[(b, a)] = Relationship.P2P
            else:  # a est fournisseur de b
                self._map[(a, b)] = Relationship.P2C
                self._map[(b, a)] = Relationship.C2P

        if evidence is not None and not evidence.is_empty():
            for row in evidence.iter_rows(named=True):
                a, b = int(row["as_a"]), int(row["as_b"])
                sources = frozenset(row["sources"] or ["caida"])
                self._sources[(a, b)] = sources
                self._sources[(b, a)] = sources

    def get(self, upstream: int, downstream: int) -> Relationship:
        return self._map.get((upstream, downstream), Relationship.UNKNOWN)

    def sources(self, a: int, b: int) -> frozenset[str]:
        """Sources ayant corroboré ce lien. ``{"caida"}`` si non enrichi —
        c'est-à-dire la situation par défaut, une seule source, jamais absente
        puisque le lien lui-même vient forcément de CAIDA."""
        return self._sources.get(
            (a, b),
            frozenset({"caida"}) if self.get(a, b) is not Relationship.UNKNOWN else frozenset(),
        )

    def confidence(self, a: int, b: int) -> Confidence:
        """Confiance dans le lien (a, b), pour moduler la sévérité d'un événement.

        Une seule source (CAIDA, inférée) reste utilisable mais ne doit pas
        justifier à elle seule une alerte ``critical`` — voir ADR 0003 et
        ``docs/limites-et-remediations.md`` (L3).
        """
        n = len(self.sources(a, b))
        if n >= 2:
            return Confidence.HIGH
        if n == 1:
            return Confidence.LOW
        return Confidence.LOW

    def providers_of(self, asn: int) -> set[int]:
        return {a for (a, b), rel in self._map.items() if b == asn and rel is Relationship.P2C}

    def __len__(self) -> int:
        return len(self._map)


def classify_path(path: list[int], index: RelationshipIndex) -> list[Relationship]:
    """Qualifie chaque lien d'un AS-path, du plus proche du collecteur à l'origine."""
    return [index.get(path[i], path[i + 1]) for i in range(len(path) - 1)]


def valley_free_violation(path: list[int], index: RelationshipIndex) -> int | None:
    """Retourne l'indice du lien fautif, ou ``None`` si le chemin est conforme.

    Modèle valley-free : un chemin valide est une suite de liens montants (c2p),
    suivie d'au plus un lien latéral (p2p), suivie de liens descendants (p2c).
    Tout retour vers un lien montant ou latéral après une descente est une
    violation — signature classique d'une fuite de routes.
    """
    links = classify_path(path, index)
    known = [(i, rel) for i, rel in enumerate(links) if rel is not Relationship.UNKNOWN]
    if len(known) < 2:
        return None

    state = "up"  # up -> peer -> down, sans retour en arriere
    for position, rel in known:
        if state == "up":
            if rel is Relationship.P2P:
                state = "peer"
            elif rel is Relationship.P2C:
                state = "down"
        elif state == "peer":
            if rel in (Relationship.C2P, Relationship.P2P):
                return position
            state = "down"
        elif rel in (Relationship.C2P, Relationship.P2P):
            return position
    return None
