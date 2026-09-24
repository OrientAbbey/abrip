"""Amorçage de la démonstration : jeu complet en une commande.

Objectif de conception : un évaluateur clone le dépôt, lance ``abrip demo
bootstrap``, ouvre l'interface, et voit des données — sans télécharger un seul
fichier MRT ni attendre.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import polars as pl

from abrip.analytics.metrics import compute_all
from abrip.anomaly.engine import run_detection
from abrip.config import Settings
from abrip.demo.generator import BASE_DATE, DEFAULT_DAYS, ground_truth, reference_frames
from abrip.etl.curate import curate_range
from abrip.logging_conf import get_logger
from abrip.models import REF_AS_ORG_SCHEMA, REF_AS_REL_SCHEMA, REF_ASN_SCHEMA, REF_ROA_SCHEMA
from abrip.storage.catalog import Catalog
from abrip.storage.parquet import write_frame

log = get_logger(__name__)

SCHEMAS = {
    "ref_asn": REF_ASN_SCHEMA,
    "ref_roa": REF_ROA_SCHEMA,
    "ref_as_rel": REF_AS_REL_SCHEMA,
    "ref_as_org": REF_AS_ORG_SCHEMA,
}


def write_reference(settings: Settings) -> dict[str, int]:
    written: dict[str, int] = {}
    for name, rows in reference_frames().items():
        frame = pl.DataFrame(rows, schema=SCHEMAS[name], strict=False)
        write_frame(frame, settings.reference_dir / name)
        written[name] = frame.height
    return written


def bootstrap(settings: Settings, days: int = DEFAULT_DAYS) -> dict[str, object]:
    settings.ensure_dirs()
    catalog = Catalog(settings.catalog_path)

    start = BASE_DATE.date()
    end = start + timedelta(days=days - 1)

    reference = write_reference(settings)
    log.info("référentiels de démonstration écrits", extra=reference)

    curated = curate_range(
        settings,
        catalog,
        start,
        end,
        collectors=[c.name for c in settings.enabled_collectors()],
        synthetic=True,
    )
    metrics = compute_all(settings, catalog, start, end)
    detection = run_detection(settings, catalog, start, end)

    truth = ground_truth()
    _write_ground_truth(settings, truth)

    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "reference": reference,
        "curated": curated,
        "metrics": metrics,
        "detection": detection,
        "planted_anomalies": len(truth),
    }


def _write_ground_truth(settings: Settings, truth: list[dict]) -> None:
    frame = pl.DataFrame(truth, strict=False)
    write_frame(frame, settings.analytics_dir / "ground_truth")


def verify(settings: Settings) -> dict[str, object]:
    """Compare les anomalies plantées aux événements détectés.

    C'est le test de non-régression le plus utile du projet : il mesure ce que la
    détection retrouve réellement, sans dépendre d'un incident réel.
    """
    events_path = settings.analytics_dir / "events"
    files = sorted(events_path.glob("*.parquet")) if events_path.exists() else []
    if not files:
        return {"status": "no-events", "matched": [], "missed": ground_truth()}

    events = pl.read_parquet(files)
    matched, missed = [], []
    for planted in ground_truth():
        hits = events.filter(
            (pl.col("prefix") == planted["prefix"])
            & (pl.col("first_seen").dt.strftime("%Y-%m-%d") == planted["expected_date"])
        )
        if hits.height:
            matched.append(
                {
                    **planted,
                    "detected_by": sorted(set(hits.get_column("detector").to_list())),
                    "max_score": float(cast(Any, hits.get_column("score").max()) or 0.0),
                    "expected_detector_fired": planted["kind"]
                    in set(hits.get_column("detector").to_list()),
                }
            )
        else:
            missed.append(planted)

    return {
        "status": "ok",
        "planted": len(ground_truth()),
        "matched": matched,
        "missed": missed,
        "recall": round(len(matched) / max(1, len(ground_truth())), 2),
    }
