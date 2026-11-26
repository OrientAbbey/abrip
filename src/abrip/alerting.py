"""Alertes sur les incidents : webhook Slack, déduplication, échec sans douceur.

Une alerte n'est jamais bloquante : si le webhook est injoignable, on journalise
et on continue. L'état « déjà envoyé » vit dans le catalogue, pas dans un fichier
local, pour rester cohérent entre plusieurs exécutions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
import polars as pl
from pydantic import ValidationError

from abrip.config import Settings
from abrip.logging_conf import get_logger
from abrip.models import Incident
from abrip.storage.catalog import Catalog

log = get_logger(__name__)

RANK = {"info": 0, "watch": 1, "critical": 2}


class Client(Protocol):
    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> Any: ...


def format_message(incident: Incident) -> str:
    """Message lisible, valable aussi bien dans Slack que dans un webhook générique."""
    when = incident.first_seen.strftime("%Y-%m-%d %H:%M UTC")
    detectors = ", ".join(incident.detectors) or "détecteurs inconnus"
    return (
        f"[{incident.severity.value.upper()}] {incident.prefix or 'préfixe inconnu'} — "
        f"{incident.summary}\n"
        f"Détecteurs : {detectors} · score {incident.score:.2f} · depuis {when}"
    )


def load_recent_incidents(settings: Settings, days: int) -> list[Incident]:
    """Lit les incidents persistés sur les `days` derniers jours."""
    root = settings.analytics_dir / "incidents"
    paths = sorted(root.glob("*.parquet"))
    if not paths:
        return []
    frame = pl.read_parquet(paths)
    # Sur Windows, convertir un datetime polars fuseau en datetime Python
    # demande tzdata ; retirer le fuseau ici garde l'heure UTC numérique.
    for column, dtype in list(frame.schema.items()):
        if isinstance(dtype, pl.Datetime) and dtype.time_zone is not None:
            frame = frame.with_columns(pl.col(column).dt.replace_time_zone(None))
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    incidents: list[Incident] = []
    for row in frame.to_dicts():
        seen = row.get("last_seen")
        if isinstance(seen, datetime):
            value = seen.replace(tzinfo=UTC) if seen.tzinfo is None else seen
            if value.astimezone(UTC).replace(tzinfo=None) < cutoff:
                continue
        try:
            incidents.append(Incident.model_validate(row))
        except ValidationError:
            log.warning("incident illisible, ignoré pour l'alerte", extra={"row": row})
    return incidents


def _notify(
    settings: Settings,
    catalog: Catalog,
    incidents: list[Incident],
    client: Client,
) -> dict[str, int]:
    from abrip.qualification import is_allowed, load_allowlist

    alerts = settings.alerts
    catalog.prune_alerts(alerts.dedupe_days)
    allowlist = load_allowlist()
    candidates = [
        incident
        for incident in incidents
        if RANK[incident.severity.value] >= RANK[alerts.min_severity]
        and not is_allowed(
            allowlist,
            prefix=incident.prefix,
            asns=[],
            detectors=incident.detectors,
        )
    ]
    already = catalog.already_alerted([incident.incident_id for incident in candidates])

    sent = failed = 0
    for incident in candidates:
        if incident.incident_id in already:
            continue
        try:
            response = client.post(
                alerts.webhook_url or "",
                json={"text": format_message(incident)},
                timeout=alerts.timeout_seconds,
            )
            status = getattr(response, "status_code", 200)
            if not 200 <= status < 300:
                raise RuntimeError(f"webhook: HTTP {status}")
        except Exception as exc:
            failed += 1
            log.warning(
                "envoi d'alerte impossible",
                extra={"incident_id": incident.incident_id, "error": str(exc)},
            )
            continue
        catalog.record_alert(incident.incident_id)
        sent += 1
    return {
        "candidates": len(incidents),
        "selected": len(candidates),
        "sent": sent,
        "already_sent": len(already),
        "failed": failed,
    }


def notify_incidents(
    settings: Settings,
    catalog: Catalog,
    incidents: list[Incident],
    client: Client | None = None,
) -> dict[str, int]:
    """Envoie les alertes dues ; sans webhook configuré, ne fait rien."""
    if not settings.alerts.webhook_url:
        return {"candidates": len(incidents), "skipped": len(incidents)}
    if client is not None:
        return _notify(settings, catalog, incidents, client)
    with httpx.Client() as http:
        return _notify(settings, catalog, incidents, http)
