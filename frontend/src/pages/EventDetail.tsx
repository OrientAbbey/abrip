import { Link, useParams } from "react-router-dom";
import { useApi, useTitle } from "../lib/useApi";
import type { EventTimeline } from "../lib/types";
import { AsyncBlock } from "../components/StateBlock";
import { ConfidenceBadge, DataplaneVerdictBadge, ScoreBar, SeverityBadge } from "../components/Badges";
import { PALETTE, TimeChart } from "../components/TimeChart";
import { countryLabel, detectorLabel, dt, num } from "../lib/format";

/** Rend une preuve brute lisible : les détecteurs déposent des structures de
 *  formes différentes, on les affiche telles quelles plutôt que d'en cacher
 *  une partie derrière une mise en forme partielle. */
function EvidenceValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  if (Array.isArray(value)) {
    return (
      <span>
        {value.slice(0, 12).map((v, i) => (
          <span key={i} className="tag mono">
            {typeof v === "object" ? JSON.stringify(v) : String(v)}
          </span>
        ))}
        {value.length > 12 && <span className="muted">+{value.length - 12}</span>}
      </span>
    );
  }
  if (typeof value === "object") {
    return <pre className="mono" style={{ margin: 0 }}>{JSON.stringify(value, null, 2)}</pre>;
  }
  if (typeof value === "number") return <span className="mono">{num(value)}</span>;
  if (typeof value === "boolean") return <span>{value ? "oui" : "non"}</span>;
  return <span className="mono">{String(value)}</span>;
}

const EVIDENCE_LABEL: Record<string, string> = {
  origins: "AS d'origine observés",
  expected_origin: "Origine attendue (ROA)",
  covering_prefix: "Préfixe couvrant (ROA)",
  covering_route: "Route couvrante (IRR)",
  covering_origin: "Origine du préfixe couvrant",
  rpki_status: "Statut RPKI",
  irr_status: "Statut IRR",
  irr_asn: "AS déclaré (IRR)",
  irr_source: "Source IRR",
  roa_asn: "AS autorisé (ROA)",
  roa_max_len: "Longueur maximale autorisée (ROA)",
  roa_max_length: "Longueur maximale autorisée (ROA)",
  observed_prefix_len: "Longueur du préfixe observé",
  announcing_asn: "AS annonçant",
  source: "Source de la preuve",
  peers: "Points de vue concordants",
  collectors: "Collecteurs",
  as_path: "Chemin d'AS",
  leaked_asn: "AS fuiteur",
  suspected_leaker: "AS suspecté d'avoir fuité la route",
  violation_index: "Position de la violation dans le chemin",
  relationship_sequence: "Séquence de relations",
  relationship_source: "Origine de la relation",
  corroborating_sources: "Sources ayant corroboré la relation",
  severity_capped: "Sévérité plafonnée (une seule source)",
  baseline_median: "Médiane de référence",
  baseline_mad: "Écart absolu médian",
  baseline_ratio: "Ratio de référence",
  observed: "Valeur observée",
  robust_z: "Score z robuste",
  peers_seeing: "Points de vue voyant le préfixe",
  peers_total: "Points de vue actifs",
  visibility_ratio: "Ratio de visibilité observé",
  visibility_before: "Visibilité avant",
  visibility_after: "Visibilité après",
  relative_drop: "Baisse relative",
  collectors_seeing: "Collecteurs voyant le préfixe",
  collectors_expected: "Collecteurs attendus sur la fenêtre",
  excluded_gap_snapshots: "Instantanés incomplets exclus",
  window_start: "Début de fenêtre",
  announcements: "Annonces",
  withdrawals: "Retraits",
  incumbent_origin: "Origine en place",
  incumbent_peers: "Peers de l'origine en place",
  incumbent_announcements: "Annonces de l'origine en place",
  competing_origin: "Origine concurrente",
  competing_peers: "Peers de l'origine concurrente",
  competing_announcements: "Annonces de l'origine concurrente",
};

const DATAPLANE_LABEL: Record<string, string> = {
  ioda_score: "Score de coupure IODA (pays)",
  ioda_asn_scores: "Score de coupure IODA (par AS)",
  atlas_connected_ratio: "Sondes RIPE Atlas connectées",
  radar_outage_reported: "Coupure signalée (Cloudflare Radar)",
  radar_asn_outage: "Coupure signalée par AS (Cloudflare Radar)",
};

export default function EventDetail() {
  const { eventId = "" } = useParams();
  useTitle("Événement");
  const state = useApi<EventTimeline>(`/events/${encodeURIComponent(eventId)}/timeline`);

  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }}>
        <Link to="/events">← Retour aux événements</Link>
      </p>

      <AsyncBlock state={state} rows={5}>
        {({ event, incident, related_events, churn, visibility }) => {
          const markers = [{ ts: event.first_seen, label: "début" }];
          if (event.last_seen !== event.first_seen) {
            markers.push({ ts: event.last_seen, label: "fin" });
          }
          const churnPoints = churn.map((row) => ({
            ts: row.ts,
            values: {
              announcements: row.announcements,
              withdrawals: row.withdrawals,
            },
          }));
          const visibilityPoints = visibility.map((row) => ({
            ts: row.ts,
            values: {
              visibility_ratio: row.visibility_ratio,
              visibility_local: row.visibility_local,
              visibility_external: row.visibility_external,
            },
          }));

          return (
            <>
              <div className="page-head">
                <h1>{detectorLabel(event.detector)}</h1>
                <div className="row" style={{ marginTop: "0.5rem" }}>
                  <SeverityBadge severity={event.severity} />
                  <ConfidenceBadge confidence={event.confidence} />
                  <ScoreBar score={event.score} />
                  {event.prefix && (
                    <Link className="mono" to={`/prefixes/${encodeURIComponent(event.prefix)}`}>
                      {event.prefix}
                    </Link>
                  )}
                </div>
              </div>

              <section className="card">
                <h2>Ce qui a été observé</h2>
                <p className="prose">{event.explanation}</p>
                <dl className="kv">
                  <dt>Première observation</dt>
                  <dd className="mono">{dt(event.first_seen)}</dd>
                  <dt>Dernière observation</dt>
                  <dd className="mono">{dt(event.last_seen)}</dd>
                  <dt>AS impliqués</dt>
                  <dd>
                    {event.asns_involved.length === 0 ? (
                      <span className="muted">—</span>
                    ) : (
                      event.asns_involved.map((asn) => (
                        <Link key={asn} className="tag mono" to={`/asns/${asn}`}>
                          AS{asn}
                        </Link>
                      ))
                    )}
                  </dd>
                  <dt>Pays</dt>
                  <dd>{countryLabel(event.country_iso2)}</dd>
                  <dt>Collecteurs</dt>
                  <dd>
                    {event.collectors.length === 0 ? (
                      <span className="muted">—</span>
                    ) : (
                      event.collectors.map((c) => (
                        <span key={c} className="tag mono">
                          {c}
                        </span>
                      ))
                    )}
                  </dd>
                  <dt>Identifiant</dt>
                  <dd className="mono">{event.event_id}</dd>
                </dl>
                <p className="card-note">
                  L'identifiant est déterministe : rejouer la détection sur la même fenêtre produit
                  le même événement, sans doublon.
                </p>
              </section>

              <section className="card">
                <h2>Preuves</h2>
                {Object.keys(event.evidence).length === 0 ? (
                  <p className="muted">Ce détecteur n'a pas déposé de preuve structurée.</p>
                ) : (
                  <dl className="kv">
                    {Object.entries(event.evidence).map(([key, value]) => (
                      <div key={key} style={{ display: "contents" }}>
                        <dt>{EVIDENCE_LABEL[key] ?? key}</dt>
                        <dd>
                          <EvidenceValue value={value} />
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </section>

              {event.dataplane_verdict !== "not_attempted" && (
                <section className="card">
                  <h2>Confirmation par le plan de données</h2>
                  <p className="prose">
                    BGP est le plan de contrôle : une route annoncée ne dit rien du trafic réel.
                    Cette vérification recoupe l'événement avec une mesure indépendante — IODA,
                    RIPE Atlas et, si configuré, Cloudflare Radar.
                  </p>
                  <DataplaneVerdictBadge verdict={event.dataplane_verdict} />
                  {Object.keys(event.dataplane_evidence).length > 0 && (
                    <dl className="kv" style={{ marginTop: "0.6rem" }}>
                      {Object.entries(event.dataplane_evidence).map(([key, value]) => (
                        <div key={key} style={{ display: "contents" }}>
                          <dt>{DATAPLANE_LABEL[key] ?? key}</dt>
                          <dd>
                            <EvidenceValue value={value} />
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  <p className="card-note">
                    {event.dataplane_verdict === "confirmed" &&
                      "Au moins une source indépendante corrobore une perturbation réelle sur cette fenêtre."}
                    {event.dataplane_verdict === "contradicted" &&
                      "Les sources consultées ne montrent aucune perturbation : ce changement de routage n'a probablement pas eu d'impact perceptible."}
                    {event.dataplane_verdict === "inconclusive" &&
                      "Aucune source n'a pu être interrogée utilement (absence de code pays, service injoignable, ou clé Cloudflare Radar non configurée) — ni confirmation ni contradiction."}
                  </p>
                </section>
              )}

              {incident && (
                <section className="card">
                  <h2>Incident corrélé</h2>
                  <p className="prose">{incident.summary}</p>
                  <div className="row">
                    <SeverityBadge severity={incident.severity} />
                    <ScoreBar score={incident.score} />
                    {incident.detectors.map((d) => (
                      <span key={d} className="tag">
                        {detectorLabel(d)}
                      </span>
                    ))}
                  </div>
                  {related_events.length > 0 && (
                    <div className="table-wrap" style={{ marginTop: "0.7rem" }}>
                      <table>
                        <thead>
                          <tr>
                            <th>Détecteur</th>
                            <th>Sévérité</th>
                            <th>Score</th>
                            <th>Observé</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {related_events.map((e) => (
                            <tr key={e.event_id}>
                              <td>{detectorLabel(e.detector)}</td>
                              <td>
                                <SeverityBadge severity={e.severity} />
                              </td>
                              <td>
                                <ScoreBar score={e.score} />
                              </td>
                              <td className="mono">{dt(e.first_seen)}</td>
                              <td>
                                <Link to={`/events/${e.event_id}`}>détail</Link>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <p className="card-note">
                    Plusieurs détecteurs indépendants pointant le même préfixe dans la même fenêtre
                    renforcent le diagnostic : c'est ce qui distingue un incident d'un signal isolé.
                  </p>
                </section>
              )}

              {churnPoints.length > 0 && (
                <section className="card">
                  <h2>Activité du préfixe</h2>
                  <TimeChart
                    points={churnPoints}
                    height={220}
                    markers={markers}
                    stacked
                    series={[
                      { key: "announcements", label: "Annonces", color: PALETTE.ink, kind: "bar" },
                      { key: "withdrawals", label: "Retraits", color: PALETTE.amber, kind: "bar" },
                    ]}
                    note="Volume de messages BGP par fenêtre horaire, tous collecteurs confondus. Les repères verticaux bornent l'événement."
                  />
                </section>
              )}

              {visibilityPoints.length > 0 && (
                <section className="card">
                  <h2>Visibilité du préfixe</h2>
                  <TimeChart
                    points={visibilityPoints}
                    height={220}
                    markers={markers}
                    yDomain={[0, 1]}
                    valueFormat={(v) => `${Math.round(v * 100)}%`}
                    series={[
                      { key: "visibility_ratio", label: "Globale", color: PALETTE.ink, kind: "area" },
                      { key: "visibility_local", label: "Collecteurs africains", color: PALETTE.teal },
                      {
                        key: "visibility_external",
                        label: "Vue extérieure",
                        color: PALETTE.amber,
                        dashed: true,
                      },
                    ]}
                    note="Part des couples (collecteur, peer) voyant le préfixe à chaque instantané RIB."
                  />
                </section>
              )}
            </>
          );
        }}
      </AsyncBlock>
    </div>
  );
}
