/** Miroir du contrat d'API (`/api/openapi.json`).
 *
 * Écrit à la main plutôt que généré : le contrat est petit et stable, et un
 * type écrit à la main se lit mieux qu'un type généré de 1 500 lignes.
 */

export type Severity = "info" | "watch" | "critical";
export type Confidence = "low" | "medium" | "high";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export interface LayerStatus {
  name: string;
  present: boolean;
  rows: number | null;
  oldest: string | null;
  newest: string | null;
}

export interface Health {
  status: string;
  version: string;
  generated_at: string;
  layers: LayerStatus[];
  last_run: Record<string, unknown> | null;
}

export interface CollectorInfo {
  name: string;
  project: string;
  location: string;
  role: "local" | "external";
  enabled: boolean;
  files_ingested: number;
  last_file_ts: string | null;
}

export interface Overview {
  window_from: string | null;
  window_to: string | null;
  prefixes_tracked: number;
  asns_tracked: number;
  countries_tracked: number;
  median_visibility: number | null;
  events_by_severity: Record<string, number>;
  events_by_detector: Record<string, number>;
  top_unstable_prefixes: Array<Record<string, unknown>>;
}

export interface AsnSummary {
  asn: number;
  as_name: string | null;
  country_iso2: string | null;
  is_african: boolean;
  prefixes: number;
  updates: number;
  upstream_count: number | null;
  primary_upstream: number | null;
  primary_upstream_name: string | null;
  hhi_transit: number | null;
  open_events: number;
}

export interface PrefixSummary {
  prefix: string;
  origin_asn: number | null;
  origin_as_name: string | null;
  country_iso2: string | null;
  visibility_ratio: number | null;
  distinct_origins: number | null;
  updates: number;
  open_events: number;
}

export interface TimePoint {
  ts: string;
  values: Record<string, number | null>;
}

export interface Series {
  metric: string;
  granularity: string;
  subject: string;
  points: TimePoint[];
}

export type DataplaneVerdict = "confirmed" | "contradicted" | "inconclusive" | "not_attempted";

export interface EventOut {
  event_id: string;
  detector: string;
  severity: Severity;
  score: number;
  confidence: Confidence;
  first_seen: string;
  last_seen: string;
  prefix: string | null;
  asns_involved: number[];
  country_iso2: string | null;
  collectors: string[];
  explanation: string;
  evidence: Record<string, unknown>;
  dataplane_verdict: DataplaneVerdict;
  dataplane_evidence: Record<string, unknown>;
}

export interface Incident {
  incident_id: string;
  prefix: string | null;
  severity: Severity;
  score: number;
  first_seen: string;
  last_seen: string;
  event_ids: string[];
  detectors: string[];
  summary: string;
}

export interface EventTimeline {
  event: EventOut;
  incident: Incident | null;
  related_events: EventOut[];
  churn: Array<{ ts: string; announcements: number; withdrawals: number; updates_total: number }>;
  visibility: Array<{
    ts: string;
    visibility_ratio: number | null;
    visibility_local: number | null;
    visibility_external: number | null;
    peers_seeing: number | null;
    peers_total: number | null;
  }>;
}

export interface SearchHit {
  kind: string;
  value: string;
  label: string;
  detail: Record<string, unknown>;
}

export interface CountryRow {
  country_iso2: string;
  transit_dependency_ratio: number | null;
  hhi_transit: number | null;
  avg_upstream_count: number | null;
  asns_observed: number | null;
  prefixes_visible: number | null;
  avg_visibility: number | null;
  coverage_ratio: number | null;
  rpki_coverage_ratio: number | null;
  [key: string]: unknown;
}

export interface Facets {
  detector: Record<string, number>;
  severity: Record<string, number>;
  country_iso2: Record<string, number>;
  confidence: Record<string, number>;
}
