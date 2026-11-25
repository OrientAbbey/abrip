"""Schémas de réponse de l'API.

Ils sont distincts des modèles internes : l'API est un contrat public, elle ne
doit pas exposer la forme des tables ni changer quand le stockage change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, RootModel, field_serializer


def _serialize_datetimes(value: Any) -> Any:
    """Sérialise tous les datetimes comme des instants UTC explicites."""
    if isinstance(value, datetime):
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return aware.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _serialize_datetimes(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_datetimes(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_serialize_datetimes(item) for item in value)
    return value


class ApiModel(BaseModel):
    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_datetimes(self, value: Any) -> Any:
        return _serialize_datetimes(value)


class Page[T](ApiModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(ApiModel):
    error: ErrorBody


class LayerStatus(ApiModel):
    name: str
    present: bool
    rows: int | None = None
    oldest: str | None = None
    newest: str | None = None


class Health(ApiModel):
    status: str
    version: str
    generated_at: datetime
    layers: list[LayerStatus]
    last_run: dict[str, Any] | None = None


class CollectorInfo(ApiModel):
    name: str
    project: str
    location: str
    role: str
    enabled: bool
    files_ingested: int = 0
    last_file_ts: datetime | None = None


class Overview(ApiModel):
    window_from: str | None
    window_to: str | None
    prefixes_tracked: int
    asns_tracked: int
    countries_tracked: int
    median_visibility: float | None
    events_by_severity: dict[str, int]
    events_by_detector: dict[str, int]
    top_unstable_prefixes: list[dict[str, Any]]


class AsnSummary(ApiModel):
    asn: int
    country_iso2: str | None = None
    is_african: bool = False
    prefixes: int = 0
    updates: int = 0
    upstream_count: int | None = None
    primary_upstream: int | None = None
    hhi_transit: float | None = None
    open_events: int = 0


class PrefixSummary(ApiModel):
    prefix: str
    origin_asn: int | None = None
    country_iso2: str | None = None
    visibility_ratio: float | None = None
    distinct_origins: int | None = None
    updates: int = 0
    open_events: int = 0


class TimePoint(ApiModel):
    ts: datetime
    values: dict[str, float | int | None]


class Series(ApiModel):
    metric: str
    granularity: str
    subject: str
    points: list[TimePoint]


class EventOut(ApiModel):
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


class SearchHit(ApiModel):
    kind: str
    value: str
    label: str
    detail: dict[str, Any] = Field(default_factory=dict)


class AsnNames(RootModel[dict[str, str]]):
    """Table plate ASN → nom : les clés sont des numéros d'AS, pas des champs."""

    root: dict[str, str]


class EventFacets(ApiModel):
    detector: dict[str, int] = Field(default_factory=dict)
    severity: dict[str, int] = Field(default_factory=dict)
    country_iso2: dict[str, int] = Field(default_factory=dict)
    confidence: dict[str, int] = Field(default_factory=dict)


class CountryIndicator(ApiModel):
    country_iso2: str
    transit_dependency_ratio: float | None = None
    hhi_transit: float | None = None
    avg_upstream_count: float | None = None
    asns_observed: int | None = None
    avg_visibility: float | None = None
    prefixes_visible: int | None = None
    coverage_ratio: float | None = None
    rpki_coverage_ratio: float | None = None


class IncidentOut(ApiModel):
    """Version publique d'un incident : les datetimes passent par `ApiModel`."""

    incident_id: str
    prefix: str | None = None
    severity: str
    score: float
    first_seen: datetime
    last_seen: datetime
    event_ids: list[str] = Field(default_factory=list)
    detectors: list[str] = Field(default_factory=list)
    summary: str = ""


class CountryRelation(ApiModel):
    asn: int
    country_iso2: str | None = None
    local_asns: list[int] = Field(default_factory=list)


class CountryRelationships(ApiModel):
    country_iso2: str
    asns: list[int] = Field(default_factory=list)
    providers: list[CountryRelation] = Field(default_factory=list)
    customers: list[CountryRelation] = Field(default_factory=list)
    peers: list[CountryRelation] = Field(default_factory=list)


class PrefixFacets(ApiModel):
    """Comptes exacts par famille d'adresses et par statut, sur une plage."""

    ip_version: dict[str, int]
    status: dict[str, int]


class PrefixRow(ApiModel):
    prefix: str
    origin_asn: int
    ip_version: int
    active: bool
    status: str
    first_seen: datetime
    last_seen: datetime
    days_active: int
    days_total: int
    rpki_status: str
    irr_status: str


class NeighbourRow(ApiModel):
    asn: int
    type: str
    ipv4: bool
    ipv6: bool
    first_seen: datetime
    last_seen: datetime
    history: list[str]
    active_now: bool
    status: str
    country_iso2: str | None = None


class CountryNeighbourRow(NeighbourRow):
    member_asn: int


class NeighboursResponse(ApiModel):
    asn: int
    days: list[str]
    counts: dict[str, int]
    status_counts: dict[str, int]
    items: list[NeighbourRow]


class CountryNeighboursResponse(ApiModel):
    country_iso2: str
    days: list[str]
    counts: dict[str, int]
    status_counts: dict[str, int]
    items: list[CountryNeighbourRow]


class HistoryRow(ApiModel):
    prefix: str
    origin: int
    first_seen: str | None = None
    last_seen: str | None = None
    change: str
    active: bool
    match: bool


class RoaHistoryRow(HistoryRow):
    trust_anchor: str | None = None
    max_length: int | None = None


class RouteHistoryRow(HistoryRow):
    source: str | None = None


class HistoryResponse[T](ApiModel):
    prefix: str
    specified_asn: int
    rows: list[T]


class RoaHistoryResponse(HistoryResponse):
    rows: list[RoaHistoryRow]


class RouteHistoryResponse(HistoryResponse):
    rows: list[RouteHistoryRow]


class PeriodRun(ApiModel):
    first_seen: str
    last_seen: str
    days: int
    observations: int
    active: bool


class PeriodPresence(ApiModel):
    first_seen: str
    last_seen: str
    days: int
    active: bool


class DailyObservation(ApiModel):
    day: str
    observations: int


class DailyPresence(ApiModel):
    day: str
    ipv4: bool
    ipv6: bool


class PrefixHistoryResponse(ApiModel):
    asn: int
    prefix: str
    start: str | None = None
    end: str | None = None
    items: list[PeriodRun] = Field(default_factory=list)
    daily: list[DailyObservation] = Field(default_factory=list)


class NeighbourHistoryResponse(ApiModel):
    asn: int
    neighbour: int
    type: str
    start: str | None = None
    end: str | None = None
    ipv4: list[PeriodPresence] = Field(default_factory=list)
    ipv6: list[PeriodPresence] = Field(default_factory=list)
    daily: list[DailyPresence] = Field(default_factory=list)


class AsnIdentity(ApiModel):
    asn: int | None = None
    country_iso2: str | None = None
    rir: str | None = None
    is_african: bool | None = None
    allocation_date: str | None = None
    snapshot_date: str | None = None


class AsnPrefix(ApiModel):
    prefix: str
    updates: int
    first_seen: datetime
    last_seen: datetime
    peers: int


class AsnUpstream(ApiModel):
    primary_upstream: int | None = None
    hhi_transit: float | None = None
    upstream_count: int | None = None
    windows: int


class AsnEvent(ApiModel):
    event_id: str
    detector: str
    severity: str
    score: float
    prefix: str | None = None
    first_seen: datetime
    explanation: str


class AsnDetail(ApiModel):
    asn: int
    identity: AsnIdentity
    prefixes: list[AsnPrefix]
    upstreams: list[AsnUpstream]
    events: list[AsnEvent]


class PrefixOrigin(ApiModel):
    origin_asn: int
    announcements: int
    first_seen: datetime
    last_seen: datetime
    peers: int


class TopPath(ApiModel):
    as_path: str | None = None
    observations: int
    peers: int


class VisibilitySnapshot(ApiModel):
    snapshot_ts: datetime
    visibility_ratio: float | None = None
    peers_seeing: int | None = None
    peers_total: int | None = None
    collectors_seeing: int | None = None


class RoaEntry(ApiModel):
    prefix: str
    asn: int
    max_len: int | None = None
    ta: str | None = None


class PrefixEvent(ApiModel):
    event_id: str
    detector: str
    severity: str
    score: float
    confidence: str
    first_seen: datetime
    explanation: str


class PrefixDetail(ApiModel):
    prefix: str
    origins: list[PrefixOrigin]
    top_paths: list[TopPath]
    visibility: list[VisibilitySnapshot]
    roa: list[RoaEntry]
    events: list[PrefixEvent]


class ChurnPoint(ApiModel):
    ts: datetime
    announcements: int
    withdrawals: int
    updates_total: int


class VisibilityPoint(ApiModel):
    ts: datetime
    visibility_ratio: float | None = None
    visibility_local: float | None = None
    visibility_external: float | None = None
    peers_seeing: int | None = None
    peers_total: int | None = None


class EventTimeline(ApiModel):
    event: EventOut
    incident: IncidentOut | None = None
    related_events: list[EventOut] = Field(default_factory=list)
    churn: list[ChurnPoint] = Field(default_factory=list)
    visibility: list[VisibilityPoint] = Field(default_factory=list)


class GraphNode(ApiModel):
    asn: int
    as_name: str | None = None
    org_name: str | None = None
    country_iso2: str | None = None
    rpki: str | None = None


class PropagationNode(GraphNode):
    paths: list[list[int]]
    hidden_paths: int
    observations: int


class GraphEdge(ApiModel):
    source: int
    target: int
    relation: str
    violation_observations: int


class PropagationEdge(GraphEdge):
    observations: int


class PathRecord(ApiModel):
    path: list[int]
    observations: int
    valley_violation: bool


class PropagationResponse(ApiModel):
    prefix: str
    asn: int | None = None
    start: str | None = None
    end: str | None = None
    nodes: list[PropagationNode]
    edges: list[PropagationEdge]
    paths: list[PathRecord]
    paths_total: int
    paths_hidden: int
    max_observations: int
    moas: bool


class ReplayFrame(ApiModel):
    ts: str
    announcements: int
    withdrawals: int
    path_count: int
    nodes: list[int]
    edges: list[int]


class ReplayFrameWithPaths(ReplayFrame):
    path_ids: list[int]


class PropagationReplayResponse(ApiModel):
    prefix: str
    asn: int | None = None
    start: str | None = None
    end: str | None = None
    step_minutes: int
    warmup_hours: int
    clamped: bool
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    paths: list[list[int]] | None = None
    frames: list[ReplayFrame | ReplayFrameWithPaths]


class Upstream(ApiModel):
    asn: int
    as_name: str | None = None
    peak_peers: int


class UpstreamPoint(ApiModel):
    ts: str
    values: dict[str, int]


class UpstreamsResponse(ApiModel):
    prefix: str
    asn: int | None = None
    bucket_hours: int
    upstreams: list[Upstream]
    points: list[UpstreamPoint]
