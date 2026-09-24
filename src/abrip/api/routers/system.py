"""Santé, métadonnées et vue d'ensemble."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query

from abrip import __version__
from abrip.api.deps import DataAccess, get_data_access
from abrip.api.schemas import CollectorInfo, Health, LayerStatus, Overview
from abrip.config import get_settings
from abrip.storage.catalog import Catalog

router = APIRouter(tags=["système"])


@router.get("/health", response_model=Health, summary="État du service et fraîcheur des données")
def health(data: DataAccess = Depends(get_data_access)) -> Health:
    layers: list[LayerStatus] = []
    for table in ("bgp_elements", "rib_snapshots", "events", "metric_visibility", "ref_asn"):
        if not data.exists(table):
            layers.append(LayerStatus(name=table, present=False))
            continue
        source = data.table(table)
        rows = data.scalar(f"SELECT count(*) FROM {source}")
        column = _time_column(table)
        oldest = newest = None
        if column:
            bounds = data.query(f"SELECT min({column}) AS a, max({column}) AS b FROM {source}")
            if bounds:
                oldest, newest = str(bounds[0]["a"]), str(bounds[0]["b"])
        layers.append(
            LayerStatus(name=table, present=True, rows=int(rows or 0), oldest=oldest, newest=newest)
        )

    last_run = None
    settings = get_settings()
    if settings.catalog_path.exists():
        last_run = Catalog(settings.catalog_path, read_only=True).coverage().get("last_run")

    degraded = any(
        layer.name in ("bgp_elements", "events") and not layer.present for layer in layers
    )
    return Health(
        status="degraded" if degraded else "ok",
        version=__version__,
        generated_at=datetime.now(UTC),
        layers=layers,
        last_run=last_run,
    )


def _time_column(table: str) -> str | None:
    return {
        "bgp_elements": "ts",
        "rib_snapshots": "snapshot_ts",
        "events": "first_seen",
        "metric_visibility": "snapshot_ts",
    }.get(table)


@router.get("/meta/collectors", response_model=list[CollectorInfo], summary="Collecteurs suivis")
def collectors() -> list[CollectorInfo]:
    settings = get_settings()
    stats: dict[str, dict] = {}
    if settings.catalog_path.exists():
        coverage = Catalog(settings.catalog_path, read_only=True).coverage()
        for row in coverage["ingestion"]:
            entry = stats.setdefault(row["collector"], {"files": 0, "last": None})
            entry["files"] += row["files"]
            entry["last"] = max(filter(None, [entry["last"], row["to"]]), default=None)

    return [
        CollectorInfo(
            name=c.name,
            project=c.project,
            location=c.location,
            role=c.role,
            enabled=c.enabled,
            files_ingested=stats.get(c.name, {}).get("files", 0),
            last_file_ts=stats.get(c.name, {}).get("last"),
        )
        for c in settings.collectors
    ]


@router.get("/overview", response_model=Overview, summary="Synthèse du routage africain")
def overview(
    window: str = Query("7d", pattern=r"^\d+d$", description="Profondeur, par exemple 7d"),
    data: DataAccess = Depends(get_data_access),
) -> Overview:
    days = int(window.rstrip("d"))
    return data.cached(f"overview:{days}", lambda: _build_overview(data, days))


def _build_overview(data: DataAccess, days: int) -> Overview:
    elements = data.table("bgp_elements")
    bounds = data.query(f"SELECT min(ts) AS a, max(ts) AS b FROM {elements}")[0]
    end = bounds["b"]
    start = data.scalar(f"SELECT max(ts) - INTERVAL {days} DAY FROM {elements}")

    totals = data.query(
        f"""SELECT count(DISTINCT prefix) AS prefixes,
                   count(DISTINCT origin_asn) AS asns
            FROM {elements} WHERE ts >= ?""",
        [start],
    )[0]

    countries = 0
    if data.exists("ref_asn"):
        countries = int(
            data.scalar(
                f"SELECT count(DISTINCT country_iso2) FROM {data.table('ref_asn')} WHERE is_african"
            )
            or 0
        )

    median_visibility = None
    if data.exists("metric_visibility"):
        median_visibility = data.scalar(
            f"SELECT median(visibility_ratio) FROM {data.table('metric_visibility')}"
        )

    by_severity: dict[str, int] = {}
    by_detector: dict[str, int] = {}
    if data.exists("events"):
        events = data.table("events")
        by_severity = {
            r["severity"]: int(r["n"])
            for r in data.query(
                f"SELECT severity, count(*) AS n FROM {events} WHERE first_seen >= ? GROUP BY 1",
                [start],
            )
        }
        by_detector = {
            r["detector"]: int(r["n"])
            for r in data.query(
                f"SELECT detector, count(*) AS n FROM {events} WHERE first_seen >= ? GROUP BY 1",
                [start],
            )
        }

    top = data.query(
        f"""SELECT prefix, count(*) AS updates,
                   count(DISTINCT origin_asn) AS origins,
                   sum(CASE WHEN elem_type = 'W' THEN 1 ELSE 0 END) AS withdrawals
            FROM {elements} WHERE ts >= ? AND elem_type <> 'R'
            GROUP BY 1 ORDER BY updates DESC LIMIT 10""",
        [start],
    )

    return Overview(
        window_from=str(start) if start else None,
        window_to=str(end) if end else None,
        prefixes_tracked=int(totals["prefixes"] or 0),
        asns_tracked=int(totals["asns"] or 0),
        countries_tracked=countries,
        median_visibility=float(median_visibility) if median_visibility is not None else None,
        events_by_severity=by_severity,
        events_by_detector=by_detector,
        top_unstable_prefixes=[
            {
                k: (int(v) if isinstance(v, (int, float)) and k != "prefix" else v)
                for k, v in row.items()
            }
            for row in top
        ],
    )
