"""Passage de la couche brute à la couche curée.

Contrat d'idempotence : une partition ``(date, collector)`` retraitée est
**remplacée** atomiquement. Rejouer une plage ne crée jamais de doublon, ce qui
autorise à relancer le pipeline sans réfléchir après un incident.
"""

from __future__ import annotations

import gc
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from abrip.config import Settings
from abrip.etl.mrt_parser import MRTParser, get_parser
from abrip.etl.pch_parser import PchTextDumpParser
from abrip.ingestion.ris_live import ris_live_to_elements
from abrip.logging_conf import get_logger
from abrip.models import BGP_ELEMENTS_SCHEMA, RIB_SNAPSHOT_SCHEMA
from abrip.storage.catalog import Catalog, RunContext
from abrip.storage.parquet import ParquetBatchWriter, partition_path, write_frame

log = get_logger(__name__)


def _parser_for(settings: Settings, collector: str) -> MRTParser:
    """Le format PCH (texte Cisco) diffère du MRT : pas de repli configurable,
    c'est le seul parseur qui sait le lire — voir ``etl.pch_parser`` (L2)."""
    entry = next((c for c in settings.collectors if c.name == collector), None)
    if entry is not None and entry.project == "pch":
        return PchTextDumpParser()
    return get_parser(settings.etl.parser)


def _raw_files(
    settings: Settings, day: date, collectors: list[str] | None
) -> list[tuple[Path, str, str]]:
    """Retourne les triplets (chemin, collecteur, type) de la couche brute pour un jour."""
    found: list[tuple[Path, str, str]] = []
    if not settings.raw_dir.exists():
        return found
    for collector_dir in sorted(settings.raw_dir.iterdir()):
        if not collector_dir.is_dir():
            continue
        if collectors and collector_dir.name not in collectors:
            continue
        for type_dir in sorted(collector_dir.iterdir()):
            partition = type_dir / f"date={day.isoformat()}"
            if not partition.exists():
                continue
            for file in sorted(partition.iterdir()):
                if file.name.endswith(".part"):
                    continue
                found.append((file, collector_dir.name, type_dir.name))
    return found


def curate_file(
    path: Path, collector: str, settings: Settings, parser: MRTParser | None = None
) -> Iterator[dict]:
    """Parse un fichier et applique les filtres de configuration."""
    engine = parser or get_parser(settings.etl.parser)
    drop_v6 = settings.etl.drop_ipv6
    keep_communities = settings.etl.keep_communities
    for record in engine.parse(path, collector):
        if drop_v6 and record["prefix_ip_version"] == 6:
            continue
        if not keep_communities:
            record["communities"] = None
        yield record


def curate_day(
    settings: Settings,
    catalog: Catalog,
    day: date,
    collectors: list[str] | None = None,
    run_id: str = "",
    synthetic: bool = False,
) -> dict[str, int]:
    """Cure une journée : écrit ``bgp_elements`` et ``rib_snapshots``."""
    files = _raw_files(settings, day, collectors)

    if synthetic and not files:
        names = collectors or [c.name for c in settings.enabled_collectors()]
        files = [(Path(f"synthetic-{day:%Y%m%d}-{name}.mrt"), name, "updates") for name in names]

    if not files:
        log.warning("aucun fichier brut", extra={"date": day.isoformat()})
        return {"elements": 0, "rib_rows": 0}

    grouped: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    for path, collector, file_type in files:
        grouped[collector].append((path, file_type))

    totals = {"elements": 0, "rib_rows": 0}
    for collector, entries in grouped.items():
        parser = get_parser("synthetic") if synthetic else _parser_for(settings, collector)
        target = partition_path(
            settings.curated_dir, "bgp_elements", date=day.isoformat(), collector=collector
        )
        for stale in target.glob("*.parquet"):  # idempotence
            stale.unlink()

        with ParquetBatchWriter(
            target,
            BGP_ELEMENTS_SCHEMA,
            batch_rows=settings.etl.batch_rows,
            compression=settings.etl.compression,
        ) as writer:
            for path, _file_type in entries:
                if synthetic:
                    from abrip.demo.generator import generate_day

                    writer.extend(
                        generate_day(collector, datetime.combine(day, datetime.min.time()))
                    )
                else:
                    writer.extend(curate_file(path, collector, settings, parser))
                gc.collect()  # liberation explicite entre fichiers
        totals["elements"] += writer.rows_written

        if writer.rows_written:
            size = sum(f.stat().st_size for f in target.glob("*.parquet"))
            catalog.register_partition(
                "bgp_elements", str(target), writer.rows_written, size, run_id
            )

        rib_rows = _curate_rib(settings, catalog, day, collector, run_id, synthetic)
        totals["rib_rows"] += rib_rows

    log.info("journée curée", extra={"date": day.isoformat(), **totals})
    return totals


def _curate_rib(
    settings: Settings, catalog: Catalog, day: date, collector: str, run_id: str, synthetic: bool
) -> int:
    """Construit ``rib_snapshots`` (photographies de table de routage)."""
    target = partition_path(
        settings.curated_dir, "rib_snapshots", date=day.isoformat(), collector=collector
    )
    rows: list[dict] = []

    if synthetic:
        from abrip.demo.generator import generate_rib

        for hour in (0, 8, 16):
            snapshot = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)
            rows.extend(generate_rib(collector, snapshot))
    else:
        rib_files = [
            (p, c) for p, c, t in _raw_files(settings, day, [collector]) if t in ("rib", "ribs")
        ]
        parser = _parser_for(settings, collector)
        for path, _ in rib_files:
            snapshot = datetime.combine(day, datetime.min.time())
            for record in parser.parse(path, collector):
                if record["elem_type"] != "R":
                    continue
                rows.append(
                    {
                        "snapshot_ts": record["ts"] or snapshot,
                        "collector": collector,
                        "peer_asn": record["peer_asn"],
                        "prefix": record["prefix"],
                        "prefix_ip_version": record["prefix_ip_version"],
                        "prefix_len": record["prefix_len"],
                        "origin_asn": record["origin_asn"],
                        "as_path_dedup": record["as_path_dedup"],
                        "as_path_len": record["as_path_len"],
                    }
                )

    if not rows:
        return 0
    frame = pl.DataFrame(rows, schema=RIB_SNAPSHOT_SCHEMA, strict=False)
    write_frame(frame, target)
    catalog.register_partition(
        "rib_snapshots",
        str(target),
        frame.height,
        sum(f.stat().st_size for f in target.glob("*.parquet")),
        run_id,
    )
    return frame.height


def curate_ris_live_window(
    settings: Settings,
    catalog: Catalog,
    jsonl_path: Path,
    run_id: str = "",
) -> dict[str, int]:
    """Intègre une fenêtre RIS Live capturée dans la couche curée (L7).

    Les archives MRT sont publiées avec 5 à 15 minutes de retard minimum, ce
    qui borne la finesse temporelle d'un incident détectable — voir
    ``docs/limites-et-remediations.md`` (L7). RIS Live pousse les messages en
    direct : une fenêtre capturée peut être curée et soumise à la détection en
    quelques secondes, sans attendre la publication d'archive suivante.

    Fusionne avec la partition existante plutôt que de l'écraser : plusieurs
    fenêtres successives d'un même jour doivent s'accumuler. La déduplication
    sur ``(ts, collector, peer_asn, peer_ip, prefix, elem_type)`` rend
    l'opération idempotente si la même fenêtre est curée deux fois — même
    contrat que ``curate_day`` pour les archives.
    """
    records = ris_live_to_elements(jsonl_path)
    if not records:
        return {"elements": 0}

    frame = pl.DataFrame(records, schema=BGP_ELEMENTS_SCHEMA, strict=False).with_columns(
        pl.col("ts").dt.date().alias("_day")
    )
    dedup_keys = ["ts", "collector", "peer_asn", "peer_ip", "prefix", "elem_type"]
    total = 0

    with RunContext(catalog, "etl.curate_ris_live", source=str(jsonl_path)) as run:
        for (day, collector), group in frame.group_by(["_day", "collector"]):
            group = group.drop("_day")
            target = partition_path(
                settings.curated_dir, "bgp_elements", date=str(day), collector=str(collector)
            )
            if target.exists() and any(target.glob("*.parquet")):
                existing = pl.read_parquet(sorted(target.glob("*.parquet")))
                merged = pl.concat([existing, group], how="diagonal_relaxed").unique(
                    subset=dedup_keys, keep="last"
                )
            else:
                merged = group.unique(subset=dedup_keys, keep="last")
            write_frame(merged, target)
            size = sum(f.stat().st_size for f in target.glob("*.parquet"))
            catalog.register_partition(
                "bgp_elements", str(target), merged.height, size, run_id or run.run_id
            )
            total += group.height
        run.rows_out = total

    log.info("fenêtre RIS Live curée", extra={"elements": total, "source": jsonl_path.name})
    return {"elements": total}


def curate_range(
    settings: Settings,
    catalog: Catalog,
    start: date,
    end: date,
    collectors: list[str] | None = None,
    synthetic: bool = False,
) -> dict[str, int]:
    totals = {"elements": 0, "rib_rows": 0, "days": 0}
    with RunContext(
        catalog, "etl.curate", start=str(start), end=str(end), collectors=collectors
    ) as run:
        for day in _date_range(start, end):
            day_totals = curate_day(settings, catalog, day, collectors, run.run_id, synthetic)
            totals["elements"] += day_totals["elements"]
            totals["rib_rows"] += day_totals["rib_rows"]
            totals["days"] += 1
        run.rows_out = totals["elements"]
    return totals


def _date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
