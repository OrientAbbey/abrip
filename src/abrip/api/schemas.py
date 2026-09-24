"""Schémas de réponse de l'API.

Ils sont distincts des modèles internes : l'API est un contrat public, elle ne
doit pas exposer la forme des tables ni changer quand le stockage change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class LayerStatus(BaseModel):
    name: str
    present: bool
    rows: int | None = None
    oldest: str | None = None
    newest: str | None = None


class Health(BaseModel):
    status: str
    version: str
    generated_at: datetime
    layers: list[LayerStatus]
    last_run: dict[str, Any] | None = None


class CollectorInfo(BaseModel):
    name: str
    project: str
    location: str
    role: str
    enabled: bool
    files_ingested: int = 0
    last_file_ts: datetime | None = None


class Overview(BaseModel):
    window_from: str | None
    window_to: str | None
    prefixes_tracked: int
    asns_tracked: int
    countries_tracked: int
    median_visibility: float | None
    events_by_severity: dict[str, int]
    events_by_detector: dict[str, int]
    top_unstable_prefixes: list[dict[str, Any]]


class AsnSummary(BaseModel):
    asn: int
    as_name: str | None = None
    country_iso2: str | None = None
    is_african: bool = False
    prefixes: int = 0
    updates: int = 0
    upstream_count: int | None = None
    primary_upstream: int | None = None
    primary_upstream_name: str | None = None
    hhi_transit: float | None = None
    open_events: int = 0


class PrefixSummary(BaseModel):
    prefix: str
    origin_asn: int | None = None
    origin_as_name: str | None = None
    country_iso2: str | None = None
    visibility_ratio: float | None = None
    distinct_origins: int | None = None
    updates: int = 0
    open_events: int = 0


class TimePoint(BaseModel):
    ts: datetime
    values: dict[str, float | int | None]


class Series(BaseModel):
    metric: str
    granularity: str
    subject: str
    points: list[TimePoint]


class EventOut(BaseModel):
    event_id: str
    detector: str
    severity: str
    score: float
    confidence: str
    first_seen: datetime
    last_seen: datetime
    prefix: str | None = None
    asns_involved: list[int] = Field(default_factory=list)
    country_iso2: str | None = None
    collectors: list[str] = Field(default_factory=list)
    explanation: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    # L1 — confirmation par le plan de données (IODA, RIPE Atlas, Cloudflare Radar).
    dataplane_verdict: str = "not_attempted"
    dataplane_evidence: dict[str, Any] = Field(default_factory=dict)


class SearchHit(BaseModel):
    kind: str
    value: str
    label: str
    detail: dict[str, Any] = Field(default_factory=dict)
