"""Confirmation d'un événement de routage par une mesure de plan de données (L1).

BGP est le plan de **contrôle** : une route annoncée ne dit rien du trafic, de
la latence, ni de la joignabilité réelle — voir ``docs/adr`` et
``docs/limites-et-remediations.md``. Ce module relie un événement détecté à
deux sources de mesure indépendantes du contrôle de routage :

- **IODA** (CAIDA / Georgia Tech) : indice de coupure par pays ou par AS,
  agrégeant BGP, télescope réseau et sondage actif. API publique, sans clé.
  Schéma de réponse confirmé par le wiki public du projet
  (``https://github.com/CAIDA/ioda-api/wiki/API-Specification``) :
  ``{"type":..., "error":..., "data": [...]}``..
- **RIPE Atlas** : fraction des sondes d'un AS ou d'un pays actuellement
  connectées (API ``/probes/``, stable depuis des années). Une chute nette de
  sondes connectées corrobore une coupure réelle, indépendamment de BGP.

Chaque appel échoue en douceur : une source indisponible produit un verdict
``inconclusive``, jamais une exception qui interromprait la détection. C'est un
choix de conception assumé — voir ``EnrichmentSettings`` dans ``config.py`` —
plutôt qu'un mode dégradé optionnel : un déploiement sans accès réseau à ces
deux domaines continue de fonctionner normalement, simplement sans confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from abrip.logging_conf import get_logger
from abrip.models import DataplaneVerdict, Event

log = get_logger(__name__)

# Seuils de lecture des signaux IODA (0 = coupure totale, 1 = normalité).
IODA_OUTAGE_THRESHOLD = 0.5
# En dessous de ce ratio de sondes connectées, RIPE Atlas est jugé confirmer
# un problème de connectivité plutôt qu'une simple fluctuation normale.
ATLAS_CONNECTED_FLOOR = 0.6


class IodaClient:
    """Client de l'API IODA (``/v2/outages/summary/{entityType}/{entityCode}``)."""

    def __init__(
        self,
        base_url: str = "https://api.ioda.inetintel.cc.gatech.edu/v2",
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> IodaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def outage_summary(
        self, entity_type: str, entity_code: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Résumé des signaux de coupure pour l'entité, sur la fenêtre donnée.

        Retourne une liste vide sur toute erreur réseau ou de format : c'est
        l'appelant (``confirm_event``) qui décide alors de rendre
        ``inconclusive`` plutôt que de propager une exception.
        """
        try:
            response = self._client.get(
                f"/outages/summary/{entity_type}/{entity_code}",
                params={"from": int(start.timestamp()), "until": int(end.timestamp())},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("requête IODA en échec", extra={"entity": entity_code, "error": str(exc)})
            return []
        try:
            payload = response.json()
        except ValueError:
            return []
        if payload.get("error"):
            log.warning("IODA a renvoyé une erreur", extra={"error": payload["error"]})
            return []
        data = payload.get("data") or []
        return data if isinstance(data, list) else [data]

    def worst_score(
        self, entity_type: str, entity_code: str, start: datetime, end: datetime
    ) -> float | None:
        """Score de gravité le plus élevé sur la fenêtre (0 = normal, 1 = coupure totale).

        Chaque entrée du résumé IODA porte un score par source de données
        (``bgp``, ``ping-slash24``, ``merit-nt``) ; on retient le plus sévère,
        car une seule source en alerte suffit à corroborer un problème.
        """
        summary = self.outage_summary(entity_type, entity_code, start, end)
        scores: list[float] = []
        for entry in summary:
            for key in ("overall_score", "score", "value"):
                if isinstance(entry.get(key), (int, float)):
                    scores.append(float(entry[key]))
                    break
            for source_entry in entry.get("scores", []) or []:
                if isinstance(source_entry.get("value"), (int, float)):
                    scores.append(float(source_entry["value"]))
        return max(scores) if scores else None


class RipeAtlasClient:
    """Client de l'API RIPE Atlas — probes (``/api/v2/probes/``).

    On s'appuie sur l'état de connexion des sondes plutôt que sur des
    identifiants de mesure spécifiques : l'API ``/probes/`` est stable et
    documentée depuis longtemps, alors qu'une mesure « intégrée » donnée peut
    changer d'identifiant. ``status_name=Connected`` est la valeur officielle
    de l'API pour une sonde active.
    """

    def __init__(
        self,
        base_url: str = "https://atlas.ripe.net/api/v2",
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RipeAtlasClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _count(self, params: dict[str, Any]) -> int | None:
        try:
            response = self._client.get("/probes/", params={**params, "page_size": 1})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("requête RIPE Atlas en échec", extra={"params": params, "error": str(exc)})
            return None
        try:
            return int(response.json().get("count", 0))
        except (ValueError, TypeError):
            return None

    def connectivity_ratio(
        self, *, asn: int | None = None, country: str | None = None
    ) -> float | None:
        """Part des sondes connectées pour cet AS ou ce pays, ou ``None`` si indéterminable."""
        base: dict[str, Any] = {}
        if asn is not None:
            base["asn_v4"] = asn
        if country is not None:
            base["country_code"] = country
        if not base:
            return None
        total = self._count(base)
        if not total:
            return None
        connected = self._count({**base, "status_name": "Connected"})
        if connected is None:
            return None
        return connected / total


class CloudflareRadarClient:
    """Client de l'API Cloudflare Radar (``/radar/annotations/outages``).

    Seule des trois sources de ce module à exiger une clé — gratuite, mais à
    créer (``dashboard.cloudflare.com`` → My Profile → API Tokens). Sans
    ``api_token``, ce client rend systématiquement une liste vide plutôt que
    d'échouer : un déploiement sans clé Cloudflare continue de fonctionner
    avec IODA et RIPE Atlas seuls, exactement comme le prévoit
    ``docs/limites-et-remediations.md`` (L1).
    """

    def __init__(
        self,
        api_token: str | None = None,
        base_url: str = "https://api.cloudflare.com/client/v4",
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._enabled = bool(api_token)
        headers = {"Accept": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout, transport=transport, headers=headers
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CloudflareRadarClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def outages(
        self,
        *,
        location: str | None = None,
        asn: int | None = None,
        date_start: datetime | None = None,
        date_end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Annotations de coupure Radar recoupant les filtres donnés.

        Rend une liste vide sans requête si aucune clé n'est configurée : ce
        n'est pas une erreur, c'est une source optionnelle qui se désactive
        proprement.
        """
        if not self._enabled:
            return []
        params: dict[str, Any] = {}
        if location:
            params["location"] = location
        if asn:
            params["asn"] = asn
        if date_start:
            params["dateStart"] = date_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        if date_end:
            params["dateEnd"] = date_end.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            response = self._client.get("/radar/annotations/outages", params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("requête Cloudflare Radar en échec", extra={"error": str(exc)})
            return []
        try:
            payload = response.json()
        except ValueError:
            return []
        if not payload.get("success"):
            return []
        annotations = (payload.get("result") or {}).get("annotations") or []
        return annotations if isinstance(annotations, list) else []

    def has_outage(
        self,
        *,
        location: str | None = None,
        asn: int | None = None,
        date_start: datetime | None = None,
        date_end: datetime | None = None,
    ) -> bool | None:
        """``True``/``False`` si le token est configuré, ``None`` sinon (source non consultée)."""
        if not self._enabled:
            return None
        return bool(
            self.outages(location=location, asn=asn, date_start=date_start, date_end=date_end)
        )


@dataclass
class DataplaneReport:
    verdict: DataplaneVerdict
    evidence: dict[str, Any] = field(default_factory=dict)


def confirm_event(
    event: Event,
    ioda: IodaClient,
    atlas: RipeAtlasClient,
    radar: CloudflareRadarClient | None = None,
    outage_threshold: float = IODA_OUTAGE_THRESHOLD,
    connected_floor: float = ATLAS_CONNECTED_FLOOR,
) -> DataplaneReport:
    """Confirme ou contredit un événement de routage par une mesure indépendante.

    Trois sources indépendantes (IODA, RIPE Atlas, Cloudflare Radar) sont
    consultées quand disponibles ; ``radar`` est optionnel car seule cette
    troisième source exige une clé API — voir ``CloudflareRadarClient``. Un
    événement `critical` contredit par les sources consultées est un signal
    fort que le changement de routage n'a pas eu d'impact perceptible — voir
    ``anomaly.engine.enrich_with_dataplane`` pour la règle de rétrogradation.
    Ni confirmation ni contradiction franche ne force le verdict :
    ``inconclusive`` reste la réponse honnête en l'absence de signal exploitable.
    """
    evidence: dict[str, Any] = {}
    signals: list[bool | None] = []

    entity_code = event.country_iso2
    if entity_code:
        score = ioda.worst_score("country", entity_code, event.first_seen, event.last_seen)
        if score is not None:
            evidence["ioda_score"] = round(score, 3)
            signals.append(score >= outage_threshold)
        ratio = atlas.connectivity_ratio(country=entity_code)
        if ratio is not None:
            evidence["atlas_connected_ratio"] = round(ratio, 3)
            signals.append(ratio < connected_floor)
        if radar is not None:
            outage = radar.has_outage(
                location=entity_code, date_start=event.first_seen, date_end=event.last_seen
            )
            if outage is not None:
                evidence["radar_outage_reported"] = outage
                signals.append(outage)

    for asn in event.asns_involved:
        score = ioda.worst_score("asn", str(asn), event.first_seen, event.last_seen)
        if score is not None:
            evidence.setdefault("ioda_asn_scores", {})[str(asn)] = round(score, 3)
            signals.append(score >= outage_threshold)
        if radar is not None:
            outage = radar.has_outage(
                asn=asn, date_start=event.first_seen, date_end=event.last_seen
            )
            if outage is not None:
                evidence.setdefault("radar_asn_outage", {})[str(asn)] = outage
                signals.append(outage)

    observed = [s for s in signals if s is not None]
    if not observed:
        return DataplaneReport(DataplaneVerdict.INCONCLUSIVE, evidence)
    if any(observed):
        return DataplaneReport(DataplaneVerdict.CONFIRMED, evidence)
    return DataplaneReport(DataplaneVerdict.CONTRADICTED, evidence)


def enrich_events(
    events: list[Event],
    ioda: IodaClient,
    atlas: RipeAtlasClient,
    radar: CloudflareRadarClient | None = None,
    min_severity: str = "watch",
    outage_threshold: float = IODA_OUTAGE_THRESHOLD,
    connected_floor: float = ATLAS_CONNECTED_FLOOR,
) -> list[Event]:
    """Confirme chaque événement éligible et rétrograde les faux positifs probables.

    Seuls les événements ``watch`` ou ``critical`` sont soumis à confirmation
    (configurable via ``enrichment.dataplane_min_severity``) : dépenser un
    appel réseau sur un événement déjà ``info`` n'apporterait rien.
    """
    from abrip.models import Severity

    order = {Severity.INFO: 0, Severity.WATCH: 1, Severity.CRITICAL: 2}
    floor = order[Severity(min_severity)]

    enriched: list[Event] = []
    for event in events:
        if order[event.severity] < floor:
            enriched.append(event)
            continue
        report = confirm_event(
            event,
            ioda,
            atlas,
            radar,
            outage_threshold=outage_threshold,
            connected_floor=connected_floor,
        )
        updated = event.model_copy(
            update={"dataplane_verdict": report.verdict, "dataplane_evidence": report.evidence}
        )
        # Un `critical` contredit par les sources consultées est probablement
        # un changement de routage sans impact réel : on le rétrograde plutôt
        # que de laisser une fausse alerte au sommet.
        if report.verdict is DataplaneVerdict.CONTRADICTED and event.severity is Severity.CRITICAL:
            updated = updated.model_copy(update={"severity": Severity.WATCH})
        enriched.append(updated)
    return enriched
