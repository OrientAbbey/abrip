"""Événements d'anomalie et incidents corrélés.

`evidence` est stocké en JSON sérialisé dans le Parquet (une colonne de type
texte, parce que les preuves n'ont pas la même forme d'un détecteur à l'autre).
L'API le désérialise ici : le client reçoit un objet, jamais une chaîne à
reparser.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from abrip.api.deps import DataAccess, clamp_limit, get_data_access
from abrip.api.schemas import EventOut, Page

router = APIRouter(tags=["événements"])

SEVERITIES = ("info", "watch", "critical")
SORTS = {
    "score": "score DESC",
    "recent": "last_seen DESC",
    "oldest": "first_seen ASC",
}


def _decode_evidence(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {"raw": str(raw)}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def _to_event(row: dict[str, Any]) -> EventOut:
    return EventOut(
        event_id=row["event_id"],
        detector=row["detector"],
        severity=row["severity"],
        score=float(row["score"] or 0.0),
        confidence=row["confidence"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        prefix=row.get("prefix"),
        asns_involved=[int(a) for a in (row.get("asns_involved") or [])],
        country_iso2=row.get("country_iso2"),
        collectors=[str(c) for c in (row.get("collectors") or [])],
        explanation=row.get("explanation") or "",
        evidence=_decode_evidence(row.get("evidence")),
        dataplane_verdict=row.get("dataplane_verdict") or "not_attempted",
        dataplane_evidence=_decode_evidence(row.get("dataplane_evidence")),
    )


@router.get("/events", response_model=Page[EventOut], summary="Liste filtrable des événements")
def list_events(
    detector: list[str] | None = Query(None, description="Un ou plusieurs détecteurs"),
    severity: list[str] | None = Query(None, description="info, watch ou critical"),
    country: str | None = Query(None, min_length=2, max_length=2),
    asn: int | None = Query(None, ge=0),
    prefix: str | None = Query(None),
    min_score: float | None = Query(None, ge=0.0, le=1.0),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    sort: str = Query("score", pattern="^(score|recent|oldest)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    data: DataAccess = Depends(get_data_access),
) -> Page[EventOut]:
    limit = clamp_limit(limit)
    source = data.table("events")
    conditions: list[str] = []
    params: list[object] = []

    if detector:
        conditions.append(f"detector IN ({','.join('?' * len(detector))})")
        params.extend(detector)
    if severity:
        unknown = [s for s in severity if s not in SEVERITIES]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_parameters",
                    "message": f"Sévérité inconnue : {', '.join(unknown)}.",
                    "details": {"allowed": list(SEVERITIES)},
                },
            )
        conditions.append(f"severity IN ({','.join('?' * len(severity))})")
        params.extend(severity)
    if country:
        conditions.append("country_iso2 = ?")
        params.append(country.upper())
    if asn is not None:
        conditions.append("list_contains(asns_involved, ?)")
        params.append(asn)
    if prefix:
        conditions.append("prefix = ?")
        params.append(prefix)
    if min_score is not None:
        conditions.append("score >= ?")
        params.append(min_score)
    if date_from:
        conditions.append("last_seen >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("first_seen <= ?")
        params.append(date_to)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = int(data.scalar(f"SELECT count(*) FROM {source} {where}", params) or 0)
    rows = data.query(
        f"SELECT * FROM {source} {where} ORDER BY {SORTS[sort]}, event_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return Page(items=[_to_event(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/events/facets", summary="Cardinalités par détecteur, sévérité et pays")
def event_facets(data: DataAccess = Depends(get_data_access)) -> dict[str, dict[str, int]]:
    source = data.table("events")

    def counts(column: str) -> dict[str, int]:
        rows = data.query(
            f"SELECT {column} AS k, count(*) AS n FROM {source} "
            f"WHERE {column} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
        )
        return {str(r["k"]): int(r["n"]) for r in rows}

    return {
        "detector": counts("detector"),
        "severity": counts("severity"),
        "country_iso2": counts("country_iso2"),
        "confidence": counts("confidence"),
    }


@router.get("/events/{event_id}", response_model=EventOut, summary="Détail d'un événement")
def get_event(event_id: str, data: DataAccess = Depends(get_data_access)) -> EventOut:
    rows = data.query(f"SELECT * FROM {data.table('events')} WHERE event_id = ?", [event_id])
    if not rows:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Événement inconnu : {event_id}."},
        )
    return _to_event(rows[0])


@router.get("/events/{event_id}/timeline", summary="Contexte temporel autour d'un événement")
def event_timeline(
    event_id: str,
    data: DataAccess = Depends(get_data_access),
) -> dict[str, Any]:
    """Renvoie le churn et la visibilité du préfixe concerné, plus les autres
    événements du même incident. C'est ce qui permet au frontend d'afficher une
    page de détail justifiant l'alerte au lieu de l'asséner."""
    rows = data.query(f"SELECT * FROM {data.table('events')} WHERE event_id = ?", [event_id])
    if not rows:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Événement inconnu : {event_id}."},
        )
    event = _to_event(rows[0])

    churn: list[dict[str, Any]] = []
    visibility: list[dict[str, Any]] = []
    if event.prefix:
        if data.exists("metric_churn_prefix"):
            churn = data.query(
                f"""SELECT window_start AS ts, sum(announcements) AS announcements,
                           sum(withdrawals) AS withdrawals, sum(updates_total) AS updates_total
                    FROM {data.table("metric_churn_prefix")}
                    WHERE prefix = ? GROUP BY 1 ORDER BY 1""",
                [event.prefix],
            )
        if data.exists("metric_visibility"):
            visibility = data.query(
                f"""SELECT snapshot_ts AS ts, visibility_ratio, visibility_local,
                           visibility_external, peers_seeing, peers_total
                    FROM {data.table("metric_visibility")}
                    WHERE prefix = ? ORDER BY 1""",
                [event.prefix],
            )

    related: list[dict[str, Any]] = []
    incident: dict[str, Any] | None = None
    if data.exists("incidents"):
        found = data.query(
            f"SELECT * FROM {data.table('incidents')} WHERE list_contains(event_ids, ?)",
            [event_id],
        )
        if found:
            incident = dict(found[0])
            incident["event_ids"] = [str(e) for e in incident.get("event_ids") or []]
            incident["detectors"] = [str(d) for d in incident.get("detectors") or []]
            siblings = [e for e in incident["event_ids"] if e != event_id]
            if siblings:
                placeholders = ",".join("?" * len(siblings))
                related = [
                    _to_event(r).model_dump()
                    for r in data.query(
                        f"SELECT * FROM {data.table('events')} "
                        f"WHERE event_id IN ({placeholders}) ORDER BY score DESC",
                        siblings,
                    )
                ]

    return {
        "event": event.model_dump(),
        "incident": incident,
        "related_events": related,
        "churn": churn,
        "visibility": visibility,
    }


@router.get("/incidents", summary="Incidents corrélés (plusieurs détecteurs, même préfixe)")
def list_incidents(
    severity: list[str] | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    data: DataAccess = Depends(get_data_access),
) -> Page[dict[str, Any]]:
    limit = clamp_limit(limit)
    source = data.table("incidents")
    conditions: list[str] = []
    params: list[object] = []
    if severity:
        conditions.append(f"severity IN ({','.join('?' * len(severity))})")
        params.extend(severity)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = int(data.scalar(f"SELECT count(*) FROM {source} {where}", params) or 0)
    rows = data.query(
        f"SELECT * FROM {source} {where} ORDER BY score DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    items = []
    for row in rows:
        item = dict(row)
        item["event_ids"] = [str(e) for e in item.get("event_ids") or []]
        item["detectors"] = [str(d) for d in item.get("detectors") or []]
        items.append(item)
    return Page(items=items, total=total, limit=limit, offset=offset)
