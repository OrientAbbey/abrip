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
  country_iso2: string | null;
  is_african: boolean;
  prefixes: number;
  updates: number;
  upstream_count: number | null;
  primary_upstream: number | null;
  hhi_transit: number | null;
  open_events: number;
}

export interface PrefixSummary {
  prefix: string;
  origin_asn: number | null;
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

// --- explorateurs d'un AS ---------------------------------------------------
export type PrefixStatus = "stable" | "new" | "left" | "unstable";
export type NeighbourType = "provider" | "customer" | "peer" | "unspecified";

export interface PrefixRow {
  prefix: string;
  /** Page pays : l'AS du pays qui annonce le préfixe. */
  origin_asn?: number;
  ip_version: 4 | 6;
  active: boolean;
  status: PrefixStatus;
  first_seen: string;
  last_seen: string;
  days_active: number;
  days_total: number;
  rpki_status: "valid" | "invalid" | "not-found";
  irr_status: "irr_consistent" | "irr_inconsistent" | "irr_absent";
}

export interface HistoryRow {
  prefix: string;
  origin: number;
  trust_anchor?: string;
  max_length?: number;
  source?: string;
  first_seen: string | null;
  last_seen: string | null;
  /** new / left / unstable / stable ; unknown quand aucun instantané daté n'existe. */
  change?: string;
  /** Dernière vue = dernier instantané de la plage. */
  active?: boolean;
  match: boolean;
}

/** Comptes exacts renvoyés par `/prefixes/facets`, indépendamment des filtres actifs. */
export interface PrefixFacets {
  ip_version: Record<string, number>;
  status: Record<PrefixStatus, number>;
}

export interface HistoryResponse {
  prefix: string;
  specified_asn: number;
  rows: HistoryRow[];
}

export interface NeighbourRow {
  asn: number;
  /** Page pays : l'AS du pays dont `asn` est voisin. */
  member_asn?: number;
  /** Évolution sur la plage, d'après les jours de présence (même règle que les préfixes). */
  status?: PrefixStatus;
  type: NeighbourType;
  country_iso2: string | null;
  ipv4: boolean;
  ipv6: boolean;
  first_seen: string;
  last_seen: string;
  active_now: boolean;
  history: string[];
}

export interface NeighboursResponse {
  asn: number;
  days: string[];
  counts: Record<NeighbourType, number>;
  status_counts?: Record<PrefixStatus, number>;
  items: NeighbourRow[];
}

export interface CountryRelation {
  asn: number;
  country_iso2: string | null;
  local_asns: number[];
}

export interface CountryRelationships {
  country_iso2: string;
  asns: number[];
  providers: CountryRelation[];
  customers: CountryRelation[];
  peers: CountryRelation[];
}

/** Période continue de présence (jours de collecte consécutifs). */
export interface PeriodRun {
  first_seen: string;
  last_seen: string;
  days: number;
  /** Messages BGP de la période (historique d'un préfixe) ; absent pour une relation. */
  observations?: number;
  /** La période atteint le dernier jour de la plage. */
  active: boolean;
}

export interface PrefixAnnouncementHistory {
  asn: number;
  prefix: string;
  start: string | null;
  end: string | null;
  items: PeriodRun[];
  daily: Array<{ day: string; observations: number }>;
}

export interface NeighbourHistory {
  asn: number;
  neighbour: number;
  type: NeighbourType;
  start: string | null;
  end: string | null;
  ipv4: PeriodRun[];
  ipv6: PeriodRun[];
  daily: Array<{ day: string; ipv4: boolean; ipv6: boolean }>;
}
