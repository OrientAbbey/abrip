"""Découverte des fichiers MRT disponibles.

Deux stratégies, dans cet ordre :
  1. l'API BGPKIT Broker, qui indexe RouteViews et RIPE RIS ;
  2. un repli déterministe qui reconstruit les URL d'archive à partir des
     conventions de nommage, utilisable si le broker est indisponible.

Le repli n'est pas décoratif : il garantit que le projet ne dépend d'aucun
service tiers pour fonctionner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from abrip.config import Collector, Settings
from abrip.logging_conf import get_logger

log = get_logger(__name__)

FileType = Literal["rib", "updates"]


@dataclass(frozen=True, slots=True)
class MRTFile:
    url: str
    collector: str
    project: str
    file_type: FileType
    timestamp: datetime
    size_bytes: int = 0

    @property
    def date_str(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


class BrokerClient:
    """Client du broker BGPKIT, avec repli sur reconstruction d'URL."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._headers = {"User-Agent": settings.ingestion.user_agent}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
    def _query(self, params: dict[str, str | int]) -> list[dict]:
        with httpx.Client(timeout=self.settings.ingestion.request_timeout) as client:
            response = client.get(
                self.settings.ingestion.broker_url, params=params, headers=self._headers
            )
            response.raise_for_status()
            payload = response.json()
        return payload.get("data", payload if isinstance(payload, list) else [])

    def search(
        self,
        collectors: list[Collector],
        start: datetime,
        end: datetime,
        file_type: FileType = "updates",
    ) -> list[MRTFile]:
        files: list[MRTFile] = []
        for collector in collectors:
            try:
                raw = self._query(
                    {
                        "collector_id": collector.name,
                        "data_type": file_type,
                        "ts_start": start.strftime("%Y-%m-%dT%H:%M:%S"),
                        "ts_end": end.strftime("%Y-%m-%dT%H:%M:%S"),
                        "page_size": 1000,
                    }
                )
                files.extend(self._to_files(raw, collector, file_type))
                log.info(
                    "broker interrogé",
                    extra={"collector": collector.name, "files": len(raw), "type": file_type},
                )
            except Exception as exc:
                log.warning(
                    "broker indisponible, reconstruction des URL",
                    extra={"collector": collector.name, "error": str(exc)},
                )
                files.extend(build_archive_urls(self.settings, collector, start, end, file_type))
        return sorted(files, key=lambda f: (f.collector, f.timestamp))

    @staticmethod
    def _to_files(raw: list[dict], collector: Collector, file_type: FileType) -> list[MRTFile]:
        out: list[MRTFile] = []
        for item in raw:
            ts_value = item.get("ts_start") or item.get("timestamp")
            if ts_value is None:
                continue
            ts = (
                datetime.fromtimestamp(ts_value, tz=UTC).replace(tzinfo=None)
                if isinstance(ts_value, (int, float))
                else datetime.fromisoformat(str(ts_value).replace("Z", "")).replace(tzinfo=None)
            )
            out.append(
                MRTFile(
                    url=item["url"],
                    collector=collector.name,
                    project=collector.project,
                    file_type=file_type,
                    timestamp=ts,
                    size_bytes=int(item.get("rough_size") or item.get("exact_size") or 0),
                )
            )
        return out


def build_archive_urls(
    settings: Settings,
    collector: Collector,
    start: datetime,
    end: datetime,
    file_type: FileType = "updates",
) -> list[MRTFile]:
    """Reconstruit les URL d'archive sans appeler de service tiers.

    RouteViews : ``/<collector>/bgpdata/YYYY.MM/UPDATES/updates.YYYYMMDD.HHMM.bz2``
    RIPE RIS    : ``/<rrc>/YYYY.MM/updates.YYYYMMDD.HHMM.gz``

    Cadence et racine d'archive viennent de ``settings.ingestion.projects``
    (configurables) plutôt que de constantes en dur.
    """
    step = timedelta(minutes=settings.ingestion.cadence_minutes(collector.project, file_type))
    root = settings.ingestion.projects[collector.project].archive_root
    files: list[MRTFile] = []

    cursor = _floor(start, step)
    while cursor <= end:
        stamp = cursor.strftime("%Y%m%d.%H%M")
        month = cursor.strftime("%Y.%m")
        if collector.project == "routeviews":
            sub = "UPDATES" if file_type == "updates" else "RIBS"
            name = ("updates." if file_type == "updates" else "rib.") + stamp + ".bz2"
            # route-views2 est publie sans prefixe de collecteur dans le chemin
            base = "" if collector.name == "route-views2" else f"/{collector.name}"
            url = f"{root}{base}/bgpdata/{month}/{sub}/{name}"
        elif collector.project == "pch":
            # Format et chemin réels : voir etl.pch_parser (relevé quotidien
            # texte, pas MRT). Un seul fichier par jour, indépendant de
            # file_type — RIB et "updates" pointent vers la même ressource.
            name = f"{collector.name}-ipv4_bgp_routes.{cursor:%Y.%m.%d}.gz"
            url = f"{root}/{month}/{collector.name}/{name}"
        else:
            name = ("updates." if file_type == "updates" else "bview.") + stamp + ".gz"
            url = f"{root}/{collector.name}/{month}/{name}"
        files.append(
            MRTFile(
                url=url,
                collector=collector.name,
                project=collector.project,
                file_type=file_type,
                timestamp=cursor,
            )
        )
        cursor += step
    return files


def _floor(moment: datetime, step: timedelta) -> datetime:
    seconds = int(step.total_seconds())
    epoch = int(moment.replace(second=0, microsecond=0).timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC).replace(tzinfo=None)
