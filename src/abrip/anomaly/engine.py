"""Moteur de détection : assemblage du contexte, exécution, corrélation.

La corrélation est ce qui distingue une liste d'alertes d'un outil utilisable :
cinq détecteurs qui signalent le même préfixe sur la même heure décrivent un seul
incident, pas cinq.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any

import polars as pl

from abrip.analytics.metrics import _load_reference
from abrip.anomaly.base import DetectionContext, Detector, severity_from_score
from abrip.anomaly.detectors import (
    BogonDetector,
    ChurnSpikeDetector,
    MoasDetector,
    RpkiInvalidDetector,
    SubprefixDetector,
    ValleyFreeDetector,
    VisibilityDropDetector,
)
from abrip.config import Settings
from abrip.logging_conf import get_logger
from abrip.models import EVENTS_SCHEMA, Event, Incident
from abrip.reference.irr import IrrValidator
from abrip.reference.relationships import RelationshipIndex
from abrip.reference.rpki import RpkiValidator
from abrip.storage.catalog import Catalog, RunContext
from abrip.storage.parquet import read_partitions, write_frame

log = get_logger(__name__)

DETECTORS: dict[str, type[Detector]] = {
    MoasDetector.name: MoasDetector,
    SubprefixDetector.name: SubprefixDetector,
    RpkiInvalidDetector.name: RpkiInvalidDetector,
    ValleyFreeDetector.name: ValleyFreeDetector,
    ChurnSpikeDetector.name: ChurnSpikeDetector,
    VisibilityDropDetector.name: VisibilityDropDetector,
    BogonDetector.name: BogonDetector,
}


def build_context(
    settings: Settings,
    start: date,
    end: date,
    run_id: str = "",
    collectors: list[str] | None = None,
) -> DetectionContext:
    elements = read_partitions(
        settings.curated_dir,
        "bgp_elements",
        date_from=start.isoformat(),
        date_to=end.isoformat(),
        collectors=collectors,
    )
    try:
        rib = read_partitions(
            settings.curated_dir,
            "rib_snapshots",
            date_from=start.isoformat(),
            date_to=end.isoformat(),
            collectors=collectors,
        )
    except FileNotFoundError:
        rib = None
        log.warning("rib_snapshots absent : le détecteur de visibilité sera inactif")

    ref_asn = _load_reference(settings, "ref_asn")
    ref_roa = _load_reference(settings, "ref_roa")
    ref_rel = _load_reference(settings, "ref_as_rel")
    ref_org = _load_reference(settings, "ref_as_org")
    ref_rel_evidence = _load_reference(settings, "ref_as_rel_evidence")
    ref_irr = _load_reference(settings, "ref_irr_route")
    ref_anycast = _load_reference(settings, "ref_anycast")
    anycast_prefixes: frozenset[str] = (
        frozenset(ref_anycast.get_column("prefix").to_list())
        if not ref_anycast.is_empty()
        else frozenset()
    )

    asn_country: dict[int, str] = {}
    african: set[int] = set()
    if not ref_asn.is_empty():
        for row in ref_asn.iter_rows(named=True):
            asn = int(row["asn"])
            if row.get("country_iso2"):
                asn_country[asn] = row["country_iso2"]
            if row.get("is_african"):
                african.add(asn)

    asn_org: dict[int, str] = {}
    if not ref_org.is_empty():
        asn_org = {int(r["asn"]): str(r["org_id"]) for r in ref_org.iter_rows(named=True)}

    moas_config = settings.detection.get("detectors", {}).get("moas", {})
    stable_pairs = _compute_stable_pairs(settings, start, moas_config, collectors)
    coverage = _load_coverage(settings)

    return DetectionContext(
        start=start,
        end=end,
        elements=elements,
        rib=rib,
        rpki=RpkiValidator.from_frame(ref_roa) if not ref_roa.is_empty() else None,
        irr=IrrValidator.from_frame(ref_irr) if not ref_irr.is_empty() else None,
        relationships=(
            RelationshipIndex(
                ref_rel, ref_rel_evidence if not ref_rel_evidence.is_empty() else None
            )
            if not ref_rel.is_empty()
            else None
        ),
        asn_country=asn_country,
        asn_org=asn_org,
        african_asns=african,
        stable_pairs=stable_pairs,
        coverage=coverage,
        anycast_prefixes=anycast_prefixes,
        config=settings.detection,
        run_id=run_id,
    )


def _load_coverage(settings: Settings) -> dict[str, float]:
    """Dernière couverture connue par pays (``metric_coverage``), pour L2.

    Absente tant que ``abrip analytics compute`` n'a pas tourné : le
    plafonnement de confiance ne s'applique alors simplement pas, ce qui
    revient au comportement précédent plutôt que de bloquer la détection.
    """
    path = settings.analytics_dir / "metric_coverage"
    if not path.exists():
        return {}
    files = sorted(path.glob("**/*.parquet"))
    if not files:
        return {}
    frame = (
        pl.read_parquet(files)
        .sort("window_start")
        .group_by("country_iso2")
        .agg(pl.col("coverage_ratio").last())
    )
    return {
        row["country_iso2"]: float(row["coverage_ratio"]) for row in frame.iter_rows(named=True)
    }


def _compute_stable_pairs(
    settings: Settings,
    start: date,
    moas_config: dict[str, Any],
    collectors: list[str] | None,
) -> frozenset[tuple[str, int]]:
    """Couples (préfixe, origine) stables sur la période précédant ``start`` (L6).

    Lit une fenêtre d'historique *avant* le début de la détection — ce que
    ``context.elements`` (borné à ``[start, end]``) ne couvre jamais. En
    production, où la détection tourne au jour le jour, cet historique est
    simplement « hier » et les jours précédents ; sur un tout premier
    déploiement sans historique, cette fonction rend un ensemble vide et le
    filtre n'a alors aucun effet — ce qui est le comportement correct : on ne
    peut pas juger « stable » ce qu'on n'a jamais observé.
    """
    if not moas_config.get("ignore_stable_origins", True):
        return frozenset()
    lookback_days = int(moas_config.get("stability_lookback_days", 14))
    min_days = int(moas_config.get("stability_min_days_seen", 3))
    lookback_end = start - timedelta(days=1)
    lookback_start = start - timedelta(days=lookback_days)
    if lookback_end < lookback_start:
        return frozenset()

    try:
        history = read_partitions(
            settings.curated_dir,
            "bgp_elements",
            date_from=lookback_start.isoformat(),
            date_to=lookback_end.isoformat(),
            collectors=collectors,
        )
    except FileNotFoundError:
        return frozenset()

    pairs = (
        history.filter((pl.col("elem_type") == "A") & pl.col("origin_asn").is_not_null())
        .with_columns(pl.col("ts").dt.date().alias("day"))
        .group_by(["prefix", "origin_asn"])
        .agg(days_seen=pl.col("day").n_unique())
        .filter(pl.col("days_seen") >= min_days)
        .select("prefix", "origin_asn")
        .collect(engine="streaming")
    )
    return frozenset((row["prefix"], int(row["origin_asn"])) for row in pairs.iter_rows(named=True))


def run_detection(
    settings: Settings,
    catalog: Catalog,
    start: date,
    end: date,
    detectors: list[str] | None = None,
    collectors: list[str] | None = None,
    african_only: bool = True,
) -> dict[str, Any]:
    configs = settings.detection.get("detectors", {})
    names = detectors or list(DETECTORS)

    with RunContext(catalog, "detect.run", start=str(start), end=str(end), detectors=names) as run:
        context = build_context(settings, start, end, run.run_id, collectors)
        all_events: list[Event] = []
        per_detector: dict[str, int] = {}

        for name in names:
            if name not in DETECTORS:
                log.warning("détecteur inconnu ignoré", extra={"detector": name})
                continue
            detector = DETECTORS[name](configs.get(name, {}))
            if not detector.enabled:
                continue
            try:
                events = detector.detect(context)
            except Exception as exc:
                log.error("détecteur en échec", extra={"detector": name, "error": str(exc)})
                continue
            if african_only and context.african_asns:
                events = [e for e in events if _touches_africa(e, context)]
            per_detector[name] = len(events)
            all_events.extend(events)

        if settings.enrichment.dataplane_enabled and all_events:
            all_events = _enrich_dataplane(settings, all_events)

        incidents = correlate(all_events, settings.detection)
        rows = persist_events(settings, catalog, all_events, run.run_id)
        persist_incidents(settings, catalog, incidents, run.run_id)
        run.rows_out = rows

    log.info(
        "détection terminée",
        extra={"events": len(all_events), "incidents": len(incidents), **per_detector},
    )
    return {
        "events": len(all_events),
        "incidents": len(incidents),
        "per_detector": per_detector,
        "run_id": context.run_id,
    }


def _enrich_dataplane(settings: Settings, events: list[Event]) -> list[Event]:
    """Confirme les événements ``watch``/``critical`` par IODA et RIPE Atlas (L1).

    Ne lève jamais : une source injoignable (réseau restreint, domaine bloqué)
    laisse simplement les événements concernés en ``inconclusive`` — voir
    ``enrichment.dataplane``. C'est pourquoi cette étape reste activée par
    défaut plutôt que traitée comme une option à activer manuellement.
    """
    from abrip.enrichment.dataplane import (
        CloudflareRadarClient,
        IodaClient,
        RipeAtlasClient,
        enrich_events,
    )

    cfg = settings.enrichment
    try:
        with (
            IodaClient(cfg.ioda_base_url, cfg.request_timeout) as ioda,
            RipeAtlasClient(cfg.ripe_atlas_base_url, cfg.request_timeout) as atlas,
            CloudflareRadarClient(
                cfg.cloudflare_radar_token, cfg.cloudflare_radar_base_url, cfg.request_timeout
            ) as radar,
        ):
            return enrich_events(events, ioda, atlas, radar, cfg.dataplane_min_severity)
    except Exception as exc:
        log.warning("enrichissement plan de données indisponible", extra={"error": str(exc)})
        return events


def _touches_africa(event: Event, context: DetectionContext) -> bool:
    """Ne garde que les événements concernant un AS africain ou un pays identifié."""
    if event.country_iso2:
        return True
    return any(asn in context.african_asns for asn in event.asns_involved)


def correlate(events: list[Event], config: dict[str, Any]) -> list[Incident]:
    """Regroupe les événements par préfixe et fenêtre temporelle.

    Le score de l'incident combine les scores pondérés des détecteurs qui l'ont
    signalé : la concordance de plusieurs signaux indépendants pèse plus lourd
    qu'un signal unique, même fort.
    """
    if not events:
        return []
    minutes = int((config.get("correlation", {}) or {}).get("incident_window_minutes", 60))
    span = timedelta(minutes=minutes)

    buckets: dict[str, list[Event]] = {}
    for event in sorted(events, key=lambda e: (e.prefix or "", e.first_seen)):
        placed = False
        for key, group in buckets.items():
            if not key.startswith(f"{event.prefix or '-'}|"):
                continue
            if abs(group[0].first_seen - event.first_seen) <= span:
                group.append(event)
                placed = True
                break
        if not placed:
            buckets[f"{event.prefix or '-'}|{event.first_seen.isoformat()}"] = [event]

    incidents: list[Incident] = []
    for key, group in buckets.items():
        detectors = sorted({e.detector for e in group})
        base = max(e.score for e in group)
        bonus = min(0.25, 0.08 * (len(detectors) - 1))
        score = min(1.0, base + bonus)
        incidents.append(
            Incident(
                incident_id=hashlib.sha1(key.encode()).hexdigest()[:16],
                prefix=group[0].prefix,
                severity=severity_from_score(score, config),
                score=round(score, 3),
                first_seen=min(e.first_seen for e in group),
                last_seen=max(e.last_seen for e in group),
                event_ids=[e.event_id for e in group],
                detectors=detectors,
                summary=_summarise(group, detectors),
            )
        )
    return sorted(incidents, key=lambda i: (-i.score, i.first_seen))


def _summarise(group: list[Event], detectors: list[str]) -> str:
    prefix = group[0].prefix or "plusieurs préfixes"
    if len(detectors) == 1:
        return f"{prefix} : signalé par le détecteur {detectors[0]}."
    return (
        f"{prefix} : {len(detectors)} détecteurs concordants "
        f"({', '.join(detectors)}), ce qui renforce la vraisemblance du signal."
    )


def events_to_frame(events: list[Event]) -> pl.DataFrame:
    if not events:
        return pl.DataFrame(schema=EVENTS_SCHEMA)
    return pl.DataFrame(
        [
            {
                "event_id": e.event_id,
                "detector": e.detector,
                "severity": e.severity.value,
                "score": e.score,
                "confidence": e.confidence.value,
                "first_seen": e.first_seen,
                "last_seen": e.last_seen,
                "prefix": e.prefix,
                "asns_involved": [int(a) for a in e.asns_involved],
                "country_iso2": e.country_iso2,
                "collectors": e.collectors,
                "evidence": json.dumps(e.evidence, default=str, ensure_ascii=False),
                "explanation": e.explanation,
                "run_id": e.run_id,
                "dataplane_verdict": e.dataplane_verdict.value,
                "dataplane_evidence": json.dumps(
                    e.dataplane_evidence, default=str, ensure_ascii=False
                ),
            }
            for e in events
        ],
        schema=EVENTS_SCHEMA,
        strict=False,
    )


def persist_events(settings: Settings, catalog: Catalog, events: list[Event], run_id: str) -> int:
    """Écrit les événements en fusionnant avec l'existant sur ``event_id``.

    L'identifiant étant déterministe, rejouer une fenêtre met à jour les
    événements au lieu de les dupliquer.
    """
    frame = events_to_frame(events)
    target = settings.analytics_dir / "events"
    existing = target / "part-00000.parquet"

    if existing.exists():
        previous = pl.read_parquet(existing)
        if not frame.is_empty():
            frame = pl.concat([previous, frame], how="vertical_relaxed").unique(
                subset=["event_id"], keep="last"
            )
        else:
            frame = previous
    if frame.is_empty():
        return 0

    frame = frame.sort("first_seen", descending=True)
    write_frame(frame, target)
    catalog.register_partition(
        "events",
        str(target),
        frame.height,
        sum(f.stat().st_size for f in target.glob("*.parquet")),
        run_id,
    )
    return frame.height


def persist_incidents(
    settings: Settings, catalog: Catalog, incidents: list[Incident], run_id: str
) -> int:
    if not incidents:
        return 0
    frame = pl.DataFrame([i.model_dump() for i in incidents], strict=False).with_columns(
        pl.col("severity").cast(pl.Utf8)
    )
    target = settings.analytics_dir / "incidents"
    write_frame(frame, target)
    catalog.register_partition(
        "incidents",
        str(target),
        frame.height,
        sum(f.stat().st_size for f in target.glob("*.parquet")),
        run_id,
    )
    return frame.height
