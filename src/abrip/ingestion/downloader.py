"""Téléchargement des fichiers MRT vers la couche brute.

Trois garanties :
  - **reprise** : un fichier déjà téléchargé avec succès n'est jamais retéléchargé ;
  - **atomicité** : écriture dans un fichier temporaire puis renommage, donc pas
    de fichier tronqué dans la couche brute ;
  - **traçabilité** : chaque tentative est consignée dans le catalogue.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

import httpx

from abrip.config import Settings
from abrip.ingestion.broker import MRTFile
from abrip.logging_conf import get_logger
from abrip.storage.catalog import Catalog

log = get_logger(__name__)

MRT_MAGIC_MIN_BYTES = 12


@dataclass
class DownloadReport:
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_total: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "downloaded": self.downloaded,
            "skipped": self.skipped,
            "failed": self.failed,
            "bytes_total": self.bytes_total,
        }


class Downloader:
    def __init__(self, settings: Settings, catalog: Catalog) -> None:
        self.settings = settings
        self.catalog = catalog
        self.raw_dir = settings.raw_dir

    def target_path(self, mrt: MRTFile) -> Path:
        return self.raw_dir / mrt.collector / mrt.file_type / f"date={mrt.date_str}" / mrt.filename

    def plan(self, files: list[MRTFile]) -> tuple[list[MRTFile], int]:
        """Retourne les fichiers restant à télécharger et le volume estimé."""
        known = self.catalog.already_ingested([f.url for f in files])
        todo = [f for f in files if f.url not in known and not self.target_path(f).exists()]
        return todo, sum(f.size_bytes for f in todo)

    def run(self, files: list[MRTFile], dry_run: bool = False) -> DownloadReport:
        report = DownloadReport()
        todo, estimated = self.plan(files)
        report.skipped = len(files) - len(todo)

        if dry_run:
            log.info(
                "simulation de téléchargement",
                extra={"files": len(todo), "estimated_mb": round(estimated / 1e6, 1)},
            )
            report.bytes_total = estimated
            return report

        workers = max(1, self.settings.ingestion.concurrency)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._fetch_one, mrt): mrt for mrt in todo}
            for future in as_completed(futures):
                mrt = futures[future]
                try:
                    size = future.result()
                except Exception as exc:
                    report.failed += 1
                    self.catalog.record_ingestion(
                        file_url=mrt.url,
                        collector=mrt.collector,
                        file_type=mrt.file_type,
                        file_ts=mrt.timestamp,
                        status="failed",
                        error=str(exc)[:500],
                    )
                    log.warning("téléchargement échoué", extra={"url": mrt.url, "error": str(exc)})
                else:
                    report.downloaded += 1
                    report.bytes_total += size
        return report

    def _fetch_one(self, mrt: MRTFile) -> int:
        destination = self.target_path(mrt)
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(destination.suffix + ".part")
        digest = hashlib.sha256()
        size = 0

        headers = {"User-Agent": self.settings.ingestion.user_agent}
        timeout = self.settings.ingestion.request_timeout
        with (
            httpx.Client(timeout=timeout, follow_redirects=True) as client,
            client.stream("GET", mrt.url, headers=headers) as response,
        ):
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size=1 << 20):
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)

        if size < MRT_MAGIC_MIN_BYTES:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"fichier vide ou tronqué ({size} octets)")

        tmp.replace(destination)
        self.catalog.record_ingestion(
            file_url=mrt.url,
            collector=mrt.collector,
            file_type=mrt.file_type,
            file_ts=mrt.timestamp,
            status="ok",
            local_path=str(destination),
            size_bytes=size,
            sha256=digest.hexdigest(),
        )
        log.info(
            "fichier ingéré",
            extra={"collector": mrt.collector, "bytes": size, "file": mrt.filename},
        )
        return size

    def purge_raw(self, older_than_days: int | None = None) -> int:
        """Purge la couche brute au-delà de la rétention configurée."""
        from datetime import datetime, timedelta

        days = older_than_days or self.settings.ingestion.raw_retention_days
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        removed = 0
        for date_dir in self.raw_dir.rglob("date=*"):
            if date_dir.name.split("=", 1)[1] < cutoff:
                for file in date_dir.iterdir():
                    file.unlink()
                    removed += 1
                date_dir.rmdir()
        log.info("purge de la couche brute", extra={"removed": removed, "cutoff": cutoff})
        return removed
