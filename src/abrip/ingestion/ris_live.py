"""Client RIS Live (WebSocket).

Étape optionnelle du projet : elle démontre la capacité à traiter un flux, sans
que le reste de la plateforme en dépende. Les messages sont écrits en JSONL par
fenêtres de cinq minutes, ce qui garde la couche brute immuable et découpée.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from abrip.config import Settings
from abrip.logging_conf import get_logger

log = get_logger(__name__)

RIS_LIVE_URL = "wss://ris-live.ripe.net/v1/ws/?client=abrip"
WINDOW = timedelta(minutes=5)


def _window_path(settings: Settings, moment: datetime) -> Path:
    floored = moment - timedelta(
        minutes=moment.minute % 5, seconds=moment.second, microseconds=moment.microsecond
    )
    return (
        settings.raw_dir
        / "ris-live"
        / "stream"
        / f"date={floored:%Y-%m-%d}"
        / f"ris-live.{floored:%Y%m%d.%H%M}.jsonl"
    )


async def capture(
    settings: Settings,
    duration: int = 300,
    prefixes: list[str] | None = None,
    host: str | None = None,
) -> int:
    """Écoute le flux pendant ``duration`` secondes et retourne le nombre de messages."""
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Client live indisponible. Installer l'extra : pip install -e '.[live]'"
        ) from exc

    subscription: dict[str, Any] = {"type": "ris_subscribe", "data": {"moreSpecific": True}}
    if host:
        subscription["data"]["host"] = host
    if prefixes:
        subscription["data"]["prefix"] = prefixes[0]

    deadline = datetime.now(UTC) + timedelta(seconds=duration)
    written = 0
    handle = None
    current: Path | None = None

    while datetime.now(UTC) < deadline:
        try:
            async with websockets.connect(RIS_LIVE_URL, ping_interval=20) as socket:
                await socket.send(json.dumps(subscription))
                log.info("flux RIS Live connecté", extra={"prefixes": prefixes})

                while datetime.now(UTC) < deadline:
                    remaining = (deadline - datetime.now(UTC)).total_seconds()
                    try:
                        raw = await asyncio.wait_for(socket.recv(), timeout=min(30, remaining))
                    except TimeoutError:
                        continue

                    message = json.loads(raw)
                    if message.get("type") != "ris_message":
                        continue

                    target = _window_path(settings, datetime.now(UTC))
                    if target != current:
                        if handle:
                            handle.close()
                        target.parent.mkdir(parents=True, exist_ok=True)
                        handle = target.open("a", encoding="utf-8")
                        current = target
                    assert handle is not None  # le premier message ouvre toujours le flux
                    handle.write(json.dumps(message["data"], ensure_ascii=False) + "\n")
                    written += 1
        except Exception as exc:
            log.warning("flux interrompu, reconnexion", extra={"error": str(exc)})
            await asyncio.sleep(3)

    if handle:
        handle.close()
    log.info("capture terminée", extra={"messages": written})
    return written


def ris_live_to_elements(path: Path, collector_prefix: str = "ris-live") -> list[dict[str, Any]]:
    """Convertit un fichier JSONL RIS Live en éléments normalisés."""
    from abrip.etl.normalize import to_element_dict

    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            collector = f"{collector_prefix}.{message.get('host', 'unknown')}"
            base = {
                "timestamp": message.get("timestamp"),
                "collector": collector,
                "peer_asn": message.get("peer_asn"),
                "peer_ip": message.get("peer", ""),
                "source_file": path.name,
            }
            for announcement in message.get("announcements", []) or []:
                for prefix in announcement.get("prefixes", []):
                    record = to_element_dict(
                        **base,
                        elem_type="A",
                        prefix=prefix,
                        as_path=message.get("path"),
                        next_hop=announcement.get("next_hop"),
                        communities=[f"{a}:{b}" for a, b in message.get("community", [])] or None,
                    )
                    if record:
                        records.append(record)
            for prefix in message.get("withdrawals", []) or []:
                record = to_element_dict(**base, elem_type="W", prefix=prefix)
                if record:
                    records.append(record)
    return records
