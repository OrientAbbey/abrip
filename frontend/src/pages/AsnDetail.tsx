import { Link, useParams } from "react-router-dom";
import { useApi, useTitle } from "../lib/useApi";
import type { Series } from "../lib/types";
import { AsyncBlock } from "../components/StateBlock";
import { AsLink, SeverityBadge } from "../components/Badges";
import { AsnPrefixesPanel } from "../components/AsnPrefixesPanel";
import { AsnNeighborsPanel } from "../components/AsnNeighborsPanel";
import { PALETTE, TimeChart } from "../components/TimeChart";
import { countryLabel, day, dec, detectorLabel, dt, num } from "../lib/format";

interface AsnDetailData {
  asn: number;
  identity: Record<string, unknown>;
  prefixes: Array<{
    prefix: string;
    updates: number;
    first_seen: string;
    last_seen: string;
    peers: number;
  }>;
  upstreams: Array<{
    primary_upstream: number | null;
    primary_upstream_name: string | null;
    hhi_transit: number | null;
    upstream_count: number | null;
    windows: number;
  }>;
  events: Array<{
    event_id: string;
    detector: string;
    severity: string;
    score: number;
    prefix: string | null;
    first_seen: string;
    explanation: string;
  }>;
}

export default function AsnDetail() {
  const { asn = "" } = useParams();
  useTitle(`AS${asn}`);
  const detail = useApi<AsnDetailData>(`/asns/${encodeURIComponent(asn)}`);
  const churn = useApi<Series>("/metrics/churn", { asn });
  const upstream = useApi<Series>("/metrics/upstreams", { asn });

  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }}>
        <Link to="/asns">← Retour aux systèmes autonomes</Link>
      </p>

      <AsyncBlock state={detail} rows={5}>
        {(data) => {
          const country = (data.identity.country_iso2 as string | undefined) ?? null;
          const rir = (data.identity.rir as string | undefined) ?? null;
          const allocation = data.identity.allocation_date as string | undefined;
          const asName = (data.identity.as_name as string | undefined) ?? null;
          return (
            <>
              <div className="page-head">
                <h1 className="mono">
                  AS{data.asn}
                  {asName && <span className="muted"> ({asName})</span>}
                </h1>
                <div className="row" style={{ marginTop: "0.4rem" }}>
                  <span className="tag">{countryLabel(country)}</span>
                  {rir && <span className="tag">{String(rir).toUpperCase()}</span>}
                  {allocation && <span className="tag mono">alloué {allocation}</span>}
                  <span className="tag">{num(data.prefixes.length)} préfixes observés</span>
                </div>
              </div>

              <div className="grid cols-2">
                <section className="card">
                  <h2>Préfixes annoncés</h2>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Préfixe</th>
                          <th className="num">Annonces</th>
                          <th className="num">Peers</th>
                          <th>Dernière vue</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.prefixes.slice(0, 25).map((p) => (
                          <tr key={p.prefix}>
                            <td className="mono">
                              <Link to={`/prefixes/${encodeURIComponent(p.prefix)}`}>{p.prefix}</Link>
                            </td>
                            <td className="num mono">{num(p.updates)}</td>
                            <td className="num mono">{num(p.peers)}</td>
                            <td className="mono">{day(p.last_seen)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>

                <section className="card">
                  <h2>Dépendance au transit</h2>
                  {data.upstreams.length === 0 ? (
                    <p className="muted">Aucune relation de transit observée sur la fenêtre.</p>
                  ) : (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Fournisseur principal</th>
                            <th className="num">Fournisseurs</th>
                            <th className="num">HHI</th>
                            <th className="num">Fenêtres</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.upstreams.map((u, i) => (
                            <tr key={i}>
                              <td>
                                {u.primary_upstream ? (
                                  <AsLink asn={u.primary_upstream} name={u.primary_upstream_name} />
                                ) : (
                                  "—"
                                )}
                              </td>
                              <td className="num mono">{num(u.upstream_count)}</td>
                              <td className="num mono">{dec(u.hhi_transit)}</td>
                              <td className="num mono">{num(u.windows)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <p className="card-note">
                    Les fournisseurs sont déduits des chemins d'AS observés, pas d'un contrat : un
                    voisin qui n'apparaît sur aucun chemin collecté reste invisible ici.
                  </p>
                </section>
              </div>

              <AsnPrefixesPanel asn={data.asn} />
              <AsnNeighborsPanel asn={data.asn} />

              <section className="card">
                <h2>Activité dans le temps</h2>
                <AsyncBlock state={churn} rows={3}>
                  {(series) => (
                    <TimeChart
                      points={series.points}
                      height={200}
                      stacked
                      series={[
                        { key: "announcements", label: "Annonces", color: PALETTE.ink, kind: "bar" },
                        { key: "withdrawals", label: "Retraits", color: PALETTE.amber, kind: "bar" },
                      ]}
                    />
                  )}
                </AsyncBlock>
              </section>

              <section className="card">
                <h2>Concentration du transit</h2>
                <AsyncBlock state={upstream} rows={3}>
                  {(series) => (
                    <TimeChart
                      points={series.points}
                      height={190}
                      yDomain={[0, 1]}
                      valueFormat={(v) => dec(v, 2)}
                      series={[
                        { key: "hhi_transit", label: "HHI du transit", color: PALETTE.crimson, kind: "area" },
                      ]}
                      note="Un HHI proche de 1 signale un point de défaillance unique : tout le trafic entrant transite par un seul fournisseur."
                    />
                  )}
                </AsyncBlock>
              </section>

              <section className="card">
                <h2>Événements associés</h2>
                {data.events.length === 0 ? (
                  <p className="muted">Aucun événement détecté impliquant cet AS.</p>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Détecteur</th>
                          <th>Préfixe</th>
                          <th>Sévérité</th>
                          <th>Observé</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.events.map((e) => (
                          <tr key={e.event_id}>
                            <td>{detectorLabel(e.detector)}</td>
                            <td className="mono">{e.prefix ?? "—"}</td>
                            <td>
                              <SeverityBadge severity={e.severity} />
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
              </section>
            </>
          );
        }}
      </AsyncBlock>
    </div>
  );
}
