"""Schémas partagés : enregistrements BGP, référentiels, événements.

Ces définitions sont la source de vérité unique. Les schémas Polars en bas de
fichier doivent rester alignés sur les modèles Pydantic correspondants ; un test
vérifie cette cohérence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

ABRIP_NAMESPACE = uuid.UUID("6f2b4f3a-1c2d-5e6f-8a9b-0c1d2e3f4a5b")


class ElemType(StrEnum):
    ANNOUNCE = "A"
    WITHDRAW = "W"
    RIB = "R"


class Severity(StrEnum):
    INFO = "info"
    WATCH = "watch"
    CRITICAL = "critical"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RpkiStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    NOT_FOUND = "not-found"


class IrrStatus(StrEnum):
    """Statut de repli quand RPKI est muet (`not-found`), L4a.

    Un objet route IRR n'a pas la force d'une preuve cryptographique — il est
    déclaratif, non signé, parfois périmé — mais son absence quasi-totale de
    couverture RPKI dans la zone AFRINIC (L4) en fait un second avis rarement
    inutile.
    """

    CONSISTENT = "irr_consistent"
    INCONSISTENT = "irr_inconsistent"
    ABSENT = "irr_absent"


class DataplaneVerdict(StrEnum):
    """Confirmation d'un événement par une mesure de plan de données, L1.

    BGP est le plan de contrôle : il ne dit rien du trafic. Ce verdict relie un
    événement de routage à une mesure de joignabilité réelle (IODA, RIPE Atlas)
    sur la même fenêtre — sans jamais trancher à la place de l'opérateur.
    """

    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"
    NOT_ATTEMPTED = "not_attempted"


class Relationship(StrEnum):
    P2C = "p2c"  # provider -> customer
    C2P = "c2p"  # customer -> provider
    P2P = "p2p"  # peer <-> peer
    S2S = "s2s"  # meme organisation (sibling)
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Enregistrements
# ---------------------------------------------------------------------------
class BgpElement(BaseModel):
    """Un élément BGP normalisé, indépendant de la bibliothèque de parsing."""

    model_config = ConfigDict(frozen=True)

    ts: datetime
    collector: str
    peer_asn: int
    peer_ip: str
    elem_type: ElemType
    prefix: str
    prefix_ip_version: int
    prefix_len: int
    origin_asn: int | None = None
    as_path: list[int] = Field(default_factory=list)
    as_path_dedup: list[int] = Field(default_factory=list)
    as_path_len: int = 0
    has_as_set: bool = False
    next_hop: str | None = None
    communities: list[str] | None = None
    med: int | None = None
    local_pref: int | None = None
    source_file: str = ""


class RoaEntry(BaseModel):
    prefix: str
    asn: int
    max_len: int
    ta: str = ""


class AsnInfo(BaseModel):
    asn: int
    country_iso2: str | None = None
    rir: str | None = None
    is_african: bool = False
    holder_name: str | None = None
    org_id: str | None = None


class Event(BaseModel):
    """Un candidat d'anomalie. Jamais une affirmation catégorique."""

    event_id: str
    detector: str
    severity: Severity
    score: float = Field(ge=0.0, le=1.0)
    confidence: Confidence
    first_seen: datetime
    last_seen: datetime
    prefix: str | None = None
    asns_involved: list[int] = Field(default_factory=list)
    country_iso2: str | None = None
    collectors: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""
    run_id: str = ""
    # L1 — confirmation par le plan de données (IODA, RIPE Atlas). Absente tant
    # que l'enrichissement n'a pas tourné : `not_attempted` n'est pas un verdict,
    # c'est l'état par défaut avant toute vérification.
    dataplane_verdict: DataplaneVerdict = DataplaneVerdict.NOT_ATTEMPTED
    dataplane_evidence: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def make_id(detector: str, prefix: str | None, asns: list[int], window_start: datetime) -> str:
        """Identifiant déterministe : mêmes entrées, même identifiant.

        Garantit l'idempotence de la détection — rejouer une fenêtre ne crée pas
        de doublons d'événements.
        """
        key = f"{detector}|{prefix or '-'}|{','.join(str(a) for a in sorted(asns))}|{window_start.isoformat()}"
        return str(uuid.uuid5(ABRIP_NAMESPACE, key))


class Incident(BaseModel):
    """Regroupement d'événements corrélés sur un même préfixe et une même fenêtre."""

    incident_id: str
    prefix: str | None
    severity: Severity
    score: float
    first_seen: datetime
    last_seen: datetime
    event_ids: list[str]
    detectors: list[str]
    summary: str


# ---------------------------------------------------------------------------
# Schémas Polars
# ---------------------------------------------------------------------------
BGP_ELEMENTS_SCHEMA: dict[str, Any] = {
    "ts": pl.Datetime("us"),
    "collector": pl.Categorical,
    "peer_asn": pl.UInt32,
    "peer_ip": pl.Utf8,
    "elem_type": pl.Utf8,
    "prefix": pl.Utf8,
    "prefix_ip_version": pl.UInt8,
    "prefix_len": pl.UInt8,
    "origin_asn": pl.UInt32,
    "as_path": pl.List(pl.UInt32),
    "as_path_dedup": pl.List(pl.UInt32),
    "as_path_len": pl.UInt16,
    "has_as_set": pl.Boolean,
    "next_hop": pl.Utf8,
    "communities": pl.List(pl.Utf8),
    "med": pl.UInt32,
    "local_pref": pl.UInt32,
    "source_file": pl.Utf8,
}

RIB_SNAPSHOT_SCHEMA: dict[str, Any] = {
    "snapshot_ts": pl.Datetime("us"),
    "collector": pl.Categorical,
    "peer_asn": pl.UInt32,
    "prefix": pl.Utf8,
    "prefix_ip_version": pl.UInt8,
    "prefix_len": pl.UInt8,
    "origin_asn": pl.UInt32,
    "as_path_dedup": pl.List(pl.UInt32),
    "as_path_len": pl.UInt16,
}

REF_ASN_SCHEMA: dict[str, Any] = {
    "asn": pl.UInt32,
    "country_iso2": pl.Utf8,
    "rir": pl.Utf8,
    "is_african": pl.Boolean,
    "allocation_date": pl.Utf8,
    "snapshot_date": pl.Utf8,
}

REF_ROA_SCHEMA: dict[str, Any] = {
    "prefix": pl.Utf8,
    "asn": pl.UInt32,
    "max_len": pl.UInt8,
    "ta": pl.Utf8,
    "snapshot_date": pl.Utf8,
}

REF_AS_REL_SCHEMA: dict[str, Any] = {
    "as_a": pl.UInt32,
    "as_b": pl.UInt32,
    "relationship": pl.Utf8,
    "source": pl.Utf8,
    "snapshot_date": pl.Utf8,
}

EVENTS_SCHEMA: dict[str, Any] = {
    "event_id": pl.Utf8,
    "detector": pl.Utf8,
    "severity": pl.Utf8,
    "score": pl.Float64,
    "confidence": pl.Utf8,
    "first_seen": pl.Datetime("us"),
    "last_seen": pl.Datetime("us"),
    "prefix": pl.Utf8,
    "asns_involved": pl.List(pl.UInt32),
    "country_iso2": pl.Utf8,
    "collectors": pl.List(pl.Utf8),
    "evidence": pl.Utf8,  # JSON sérialisé
    "explanation": pl.Utf8,
    "run_id": pl.Utf8,
    "dataplane_verdict": pl.Utf8,
    "dataplane_evidence": pl.Utf8,  # JSON sérialisé
}

# L2 — couverture observationnelle : quelle part des AS alloués à un pays sont
# effectivement vus depuis les collecteurs. Une métrique publiée plutôt qu'une
# limite subie.
METRIC_COVERAGE_SCHEMA: dict[str, Any] = {
    "window_start": pl.Datetime("us"),
    "country_iso2": pl.Utf8,
    "asns_allocated": pl.UInt32,
    "asns_observed": pl.UInt32,
    "coverage_ratio": pl.Float64,
}

# L4b — taux de couverture ROA par pays : transforme l'absence de preuve RPKI
# en indicateur suivi dans le temps.
METRIC_RPKI_COVERAGE_SCHEMA: dict[str, Any] = {
    "window_start": pl.Datetime("us"),
    "country_iso2": pl.Utf8,
    "prefixes_announced": pl.UInt32,
    "prefixes_valid": pl.UInt32,
    "prefixes_invalid": pl.UInt32,
    "prefixes_not_found": pl.UInt32,
    "rpki_coverage_ratio": pl.Float64,
}

# L4a — référentiel IRR de repli (objets route/route6 déclarés), indexé comme
# les ROA pour réutiliser la même logique de recherche par supernet.
REF_IRR_ROUTE_SCHEMA: dict[str, Any] = {
    "prefix": pl.Utf8,
    "asn": pl.UInt32,
    "source": pl.Utf8,  # RADB, RIPE, APNIC, ARIN...
    "snapshot_date": pl.Utf8,
}

# L6 (filtre 3) — catalogue public d'anycast connu (bgp.tools/anycatch).
REF_ANYCAST_SCHEMA: dict[str, Any] = {
    "prefix": pl.Utf8,
    "source": pl.Utf8,
    "snapshot_date": pl.Utf8,
}

# CAIDA AS2Org — nécessaire pour que le filtre « même organisation » du
# détecteur MOAS (L6) ait des données à consulter.
REF_AS_ORG_SCHEMA: dict[str, Any] = {
    "asn": pl.UInt32,
    "org_id": pl.Utf8,
    "org_name": pl.Utf8,
    "snapshot_date": pl.Utf8,
}

# L3 — corroboration multi-source d'une relation CAIDA. `sources` porte les
# origines qui s'accordent ; la confiance en découle plutôt que d'être stockée
# séparément, pour qu'il n'y ait jamais de désaccord entre les deux colonnes.
REF_AS_REL_EVIDENCE_SCHEMA: dict[str, Any] = {
    "as_a": pl.UInt32,
    "as_b": pl.UInt32,
    "relationship": pl.Utf8,
    "sources": pl.List(pl.Utf8),
    "snapshot_date": pl.Utf8,
}


def empty_frame(schema: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)
