"""Socle commun aux détecteurs.

Chaque détecteur reçoit le même contexte — données curées de la fenêtre,
référentiels datés, configuration — et retourne des ``Event``. Cette uniformité
permet d'en ajouter un sans toucher au moteur.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, cast

import polars as pl

from abrip.models import Confidence, Event, Severity
from abrip.reference.relationships import RelationshipIndex
from abrip.reference.rpki import RpkiValidator


@dataclass
class DetectionContext:
    """Tout ce dont un détecteur a besoin, et rien de plus."""

    start: date
    end: date
    elements: pl.LazyFrame
    rib: pl.LazyFrame | None = None
    rpki: RpkiValidator | None = None
    irr: Any = None  # IrrValidator — typé Any pour éviter un import circulaire
    relationships: RelationshipIndex | None = None
    asn_country: dict[int, str] = field(default_factory=dict)
    asn_org: dict[int, str] = field(default_factory=dict)
    african_asns: set[int] = field(default_factory=set)
    # L6 — couples (préfixe, origine) stables sur la période de référence
    # précédant la fenêtre de détection : une origine déjà présente depuis
    # plusieurs semaines n'est pas « nouvelle », même sans donnée AS2Org.
    stable_pairs: frozenset[tuple[str, int]] = field(default_factory=frozenset)
    # L2 — couverture observationnelle par pays (metric_coverage), consultée
    # par build_event pour plafonner la confiance dans les pays peu couverts.
    coverage: dict[str, float] = field(default_factory=dict)
    # L6 (filtre 3) — catalogue public d'anycast connu (bgp.tools/anycatch).
    anycast_prefixes: frozenset[str] = field(default_factory=frozenset)
    config: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""

    def country_of(self, asns: list[int]) -> str | None:
        for asn in asns:
            country = self.asn_country.get(asn)
            if country:
                return country
        return None

    def same_organisation(self, left: int, right: int) -> bool:
        a, b = self.asn_org.get(left), self.asn_org.get(right)
        return bool(a and b and a == b)

    def is_stable_origin(self, prefix: str, asn: int) -> bool:
        return (prefix, asn) in self.stable_pairs


class Detector(abc.ABC):
    """Interface d'un détecteur."""

    name: str = "abstract"
    default_weight: float = 0.1

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    @property
    def weight(self) -> float:
        return float(self.config.get("score_weight", self.default_weight))

    @abc.abstractmethod
    def detect(self, context: DetectionContext) -> list[Event]:
        """Retourne les candidats d'anomalie de la fenêtre."""

    # --- utilitaires partages -------------------------------------------
    def build_event(
        self,
        *,
        context: DetectionContext,
        prefix: str | None,
        asns: list[int],
        first_seen: datetime,
        last_seen: datetime,
        score: float,
        confidence: Confidence,
        evidence: dict[str, Any],
        explanation: str,
        collectors: list[str] | None = None,
    ) -> Event:
        score = max(0.0, min(1.0, score))
        country_iso2 = context.country_of(asns)
        confidence = _apply_coverage_ceiling(confidence, context.coverage.get(country_iso2 or ""))
        return Event(
            event_id=Event.make_id(self.name, prefix, asns, first_seen),
            detector=self.name,
            severity=severity_from_score(score, context.config),
            score=score,
            confidence=confidence,
            first_seen=first_seen,
            last_seen=last_seen,
            prefix=prefix,
            asns_involved=asns,
            country_iso2=country_iso2,
            collectors=collectors or [],
            evidence=evidence,
            explanation=explanation,
            run_id=context.run_id,
        )


def _apply_coverage_ceiling(confidence: Confidence, country_coverage: float | None) -> Confidence:
    """Plafonne la confiance quand la couverture observationnelle du pays est faible (L2).

    Appliqué de façon centrale dans ``build_event`` plutôt que dans chaque
    détecteur : un même principe, un seul endroit à faire évoluer. Un signal
    vu par beaucoup de peers dans un pays dont on n'observe que 8 % des AS
    alloués reste moins solide que le même compte de peers là où la couverture
    est quasi complète — voir ``docs/limites-et-remediations.md`` (L2).
    """
    if country_coverage is None or country_coverage >= LOW_COVERAGE_THRESHOLD:
        return confidence
    return Confidence.MEDIUM if confidence is Confidence.HIGH else confidence


def severity_from_score(score: float, config: dict[str, Any] | None = None) -> Severity:
    thresholds = ((config or {}).get("correlation", {}) or {}).get("severity_thresholds", {})
    critical = float(thresholds.get("critical", 0.65))
    watch = float(thresholds.get("watch", 0.35))
    if score >= critical:
        return Severity.CRITICAL
    if score >= watch:
        return Severity.WATCH
    return Severity.INFO


LOW_COVERAGE_THRESHOLD = 0.3


def confidence_from_peers(
    peers: int, corroborating_collectors: int = 1, country_coverage: float | None = None
) -> Confidence:
    """La confiance vient du nombre de points de vue concordants, pas du score.

    Un signal vu par un seul peer peut être un artefact de session ; le même
    signal vu par plusieurs collecteurs distincts est difficile à expliquer
    autrement que par un changement réel du routage. ``country_coverage``,
    quand fourni, plafonne le résultat (L2) — mais ``build_event`` applique
    déjà ce plafond de façon centrale : ce paramètre sert surtout aux appels
    directs et aux tests unitaires de cette fonction.
    """
    if peers >= 5 and corroborating_collectors >= 2:
        base = Confidence.HIGH
    elif peers >= 3 or corroborating_collectors >= 2:
        base = Confidence.MEDIUM
    else:
        base = Confidence.LOW
    if country_coverage is not None and country_coverage < LOW_COVERAGE_THRESHOLD:
        return Confidence.MEDIUM if base is Confidence.HIGH else base
    return base


def robust_zscore(series: pl.Series) -> pl.Series:
    """Score z robuste : (x - médiane) / (1,4826 x MAD).

    Le facteur 1,4826 rend le MAD comparable à un écart-type sur une
    distribution normale. On préfère le MAD à l'écart-type parce que le churn BGP
    est très asymétrique : un seul pic ferait exploser un écart-type classique et
    masquerait les pics suivants.
    """
    median = series.median()
    if median is None:
        return pl.Series([0.0] * len(series))
    mad = (series - median).abs().median()
    if mad is None or mad == 0:
        std = series.std()
        if not std:
            return pl.Series([0.0] * len(series))
        return (series - median) / std
    return (series - median) / (1.4826 * cast(float, mad))
