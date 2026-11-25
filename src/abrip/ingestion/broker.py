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
from abrip.logging_conf import get_logger, log_http_error

log = get_logger(__name__)

FileType = Literal["rib", "updates"]

# Taille maximale acceptée par l'API BGPKIT (1-1000). Une fenêtre d'updates de
# plusieurs jours dépasse largement une page : sans boucle, les fichiers
# suivants étaient ignorés silencieusement.
PAGE_SIZE = 1000
MAX_PAGES = 10_000


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
    def _query(self, params: dict[str, str | int]) -> dict:
        with httpx.Client(timeout=self.settings.ingestion.request_timeout) as client:
            response = client.get(
                self.settings.ingestion.broker_url, params=params, headers=self._headers
            )
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, list):
            return {"data": payload}
        return payload if isinstance(payload, dict) else {"data": []}

    def _search_pages(
        self, collector: Collector, start: datetime, end: datetime, file_type: FileType
    ) -> list[dict]:
        """Parcourt toutes les pages du broker, pas seulement la première."""
        base: dict[str, str | int] = {
            "collector_id": collector.name,
            "data_type": file_type,
            "ts_start": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "ts_end": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "page_size": PAGE_SIZE,
        }
        raw: list[dict] = []
        seen: set[str] = set()
        page = 1
        while page <= MAX_PAGES:
            payload = self._query({**base, "page": page})
            batch = payload.get("data") or []
            if not isinstance(batch, list):
                break
            for item in batch:
                url = item.get("url") if isinstance(item, dict) else None
                if url and url in seen:
                    continue
                if url:
                    seen.add(url)
                raw.append(item)
            if not batch:
                break
            total = payload.get("total")
            if isinstance(total, int) and len(raw) >= total:
                break
            if isinstance(total, str) and total.isdigit() and len(raw) >= int(total):
                break
            if len(batch) < PAGE_SIZE:
                break
            page += 1
        else:
            log.warning(
                "pagination broker interrompue à la limite de sécurité",
                extra={"collector": collector.name, "pages": MAX_PAGES, "files": len(raw)},
            )
        return raw

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
                raw = self._search_pages(collector, start, end, file_type)
                files.extend(self._to_files(raw, collector, file_type))
                log.info(
                    "broker interrogé",
                    extra={"collector": collector.name, "files": len(raw), "type": file_type},
                )
            except Exception as exc:
                log_http_error(
                    log,
                    "broker indisponible, reconstruction des URL",
                    exc,
                    collector=collector.name,
                )
                files.extend(build_archive_urls(collector, start, end, file_type, self.settings))
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
    collector: Collector,
    start: datetime,
    end: datetime,
    file_type: FileType = "updates",
    settings: Settings | None = None,
) -> list[MRTFile]:
    """Reconstruit les URL d'archive sans appeler de service tiers.

    RouteViews : ``/<collector>/bgpdata/YYYY.MM/UPDATES/updates.YYYYMMDD.HHMM.bz2``
    RIPE RIS    : ``/<rrc>/YYYY.MM/updates.YYYYMMDD.HHMM.gz``

    ``settings`` par défaut à ``get_settings()`` : la cadence et la racine
    d'archive viennent de la configuration (`ingestion.cadence`,
    `ingestion.archive_root`) plutôt que de constantes figées dans le code.
    """
    if settings is None:
        from abrip.config import get_settings

        settings = get_settings()
    step = timedelta(minutes=settings.ingestion.cadence[collector.project][file_type])
    root = settings.ingestion.archive_root[collector.project]
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
    # Les dates du broker sont des dates UTC, mais plusieurs appelants
    # fournissent des ``datetime`` naïfs. ``timestamp()`` interprète un datetime
    # naïf dans le fuseau local : sur Windows, cela décalait le curseur d'une
    # heure et produisait des fichiers hors de la fenêtre demandée.
    utc_moment = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    epoch = int(utc_moment.replace(second=0, microsecond=0).timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC).replace(tzinfo=None)
