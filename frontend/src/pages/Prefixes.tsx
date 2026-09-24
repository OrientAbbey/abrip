import { Link, useParams, useSearchParams } from "react-router-dom";
import { useApi, useTitle } from "../lib/useApi";
import type { Page, PrefixSummary, Series } from "../lib/types";
import { AsyncBlock, EmptyState } from "../components/StateBlock";
import { SeverityBadge, AsLink } from "../components/Badges";
import { PALETTE, TimeChart } from "../components/TimeChart";
import { countryLabel, detectorLabel, dt, num, pct } from "../lib/format";

const PAGE_SIZE = 25;

export function PrefixList() {
  useTitle("Préfixes");
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const prefixes = useApi<Page<PrefixSummary>>("/prefixes", {
    q: q || undefined,
    limit: PAGE_SIZE,
    offset,
  });

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    setParams(next);
  };

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Préfixes</h1>
        <p>
          Les blocs d'adresses observés sur la fenêtre chargée, avec leur visibilité et le nombre
          d'origines distinctes. Plusieurs origines pour un même préfixe méritent toujours un coup
          d'œil, même quand c'est légitime.
        </p>
      </div>

      <section className="card">
        <div className="filters">
          <div className="field">
            <label htmlFor="f-q">Préfixe</label>
            <input
              id="f-q"
              value={q}
              placeholder="197.155."
              onChange={(e) => update("q", e.target.value)}
              style={{ minWidth: "14rem" }}
            />
          </div>
        </div>
      </section>

      <AsyncBlock state={prefixes} rows={6}>
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState title="Aucun préfixe ne correspond">
              <p>Essayez un motif plus court, par exemple les deux premiers octets.</p>
            </EmptyState>
          ) : (
            <section className="card">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Préfixe</th>
                      <th>Origine</th>
                      <th>Pays</th>
                      <th className="num">Visibilité</th>
                      <th className="num">Origines</th>
                      <th className="num">Mises à jour</th>
                      <th className="num">Événements</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((p) => (
                      <tr key={p.prefix}>
                        <td className="mono">
                          <Link to={`/prefixes/${encodeURIComponent(p.prefix)}`}>{p.prefix}</Link>
                        </td>
                        <td>
                          {p.origin_asn ? <AsLink asn={p.origin_asn} name={p.origin_as_name} /> : "—"}
                        </td>
                        <td>{countryLabel(p.country_iso2)}</td>
                        <td className="num mono">{pct(p.visibility_ratio)}</td>
                        <td className="num mono">{num(p.distinct_origins)}</td>
                        <td className="num mono">{num(p.updates)}</td>
                        <td className="num mono">{num(p.open_events)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="row" style={{ justifyContent: "space-between", marginTop: "0.8rem" }}>
                <span className="muted">
                  {num(page.offset + 1)}–{num(Math.min(page.offset + page.limit, page.total))} sur{" "}
                  {num(page.total)}
                </span>
                <span className="row">
                  <button
                    disabled={page.offset === 0}
                    onClick={() => update("offset", String(Math.max(0, page.offset - PAGE_SIZE)))}
                  >
                    Précédent
                  </button>
                  <button
                    disabled={page.offset + page.limit >= page.total}
                    onClick={() => update("offset", String(page.offset + PAGE_SIZE))}
                  >
                    Suivant
                  </button>
                </span>
              </div>
            </section>
          )
        }
      </AsyncBlock>
    </div>
  );
}

interface PrefixDetailData {
  prefix: string;
  origins: Array<{
    origin_asn: number;
    as_name: string | null;
    announcements: number;
    first_seen: string;
    last_seen: string;
    peers: number;
  }>;
  top_paths: Array<{ as_path: string | null; observations: number; peers: number }>;
  visibility: Array<{
    snapshot_ts: string;
    visibility_ratio: number | null;
    peers_seeing: number | null;
    peers_total: number | null;
    collectors_seeing: number | null;
  }>;
  roa: Array<{ prefix: string; asn: number; max_len: number; ta: string }>;
  events: Array<{
    event_id: string;
    detector: string;
    severity: string;
    score: number;
    confidence: string;
    first_seen: string;
    explanation: string;
  }>;
}

export function PrefixDetail() {
  const { "*": splat } = useParams();
  const prefix = splat ?? "";
  useTitle(prefix || "Préfixe");
  const detail = useApi<PrefixDetailData>(prefix ? `/prefixes/${prefix}` : null);
  const churn = useApi<Series>("/metrics/churn", { prefix });

  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }}>
        <Link to="/prefixes">← Retour aux préfixes</Link>
      </p>

      <AsyncBlock state={detail} rows={5}>
        {(data) => {
          const visPoints = data.visibility.map((v) => ({
            ts: v.snapshot_ts,
            values: { visibility_ratio: v.visibility_ratio, peers_seeing: v.peers_seeing },
          }));
          return (
            <>
              <div className="page-head">
                <h1 className="mono">{data.prefix}</h1>
                <div className="row" style={{ marginTop: "0.4rem" }}>
                  <span className="tag">{num(data.origins.length)} origine(s)</span>
                  <span className="tag">{num(data.events.length)} événement(s)</span>
                  {data.roa.length > 0 ? (
                    <span className="tag">{num(data.roa.length)} ROA publié(s)</span>
                  ) : (
                    <span className="tag">aucun ROA exact</span>
                  )}
                </div>
              </div>

              <div className="grid cols-2">
                <section className="card">
                  <h2>Origines observées</h2>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>AS</th>
                          <th className="num">Annonces</th>
                          <th className="num">Peers</th>
                          <th>Première</th>
                          <th>Dernière</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.origins.map((o) => (
                          <tr key={o.origin_asn}>
                            <td>
                              <AsLink asn={o.origin_asn} name={o.as_name} />
                            </td>
                            <td className="num mono">{num(o.announcements)}</td>
                            <td className="num mono">{num(o.peers)}</td>
                            <td className="mono">{dt(o.first_seen)}</td>
                            <td className="mono">{dt(o.last_seen)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {data.origins.length > 1 && (
                    <p className="card-note">
                      Deux origines pour un même préfixe peuvent venir d'un multi-homing légitime ou
                      d'un détournement. Les dates d'apparition et le nombre de peers concordants
                      aident à trancher.
                    </p>
                  )}
                </section>

                <section className="card">
                  <h2>Autorisations RPKI</h2>
                  {data.roa.length === 0 ? (
                    <p className="muted">
                      Aucun ROA ne couvre exactement ce préfixe. C'est le cas majoritaire dans la
                      zone AFRINIC : l'absence de ROA ne prouve rien, ni dans un sens ni dans
                      l'autre.
                    </p>
                  ) : (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Préfixe autorisé</th>
                            <th>AS autorisé</th>
                            <th className="num">Longueur max.</th>
                            <th>Ancre</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.roa.map((r, i) => (
                            <tr key={i}>
                              <td className="mono">{r.prefix}</td>
                              <td className="mono">AS{r.asn}</td>
                              <td className="num mono">/{r.max_len}</td>
                              <td>{r.ta}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>

              <section className="card">
                <h2>Visibilité</h2>
                {visPoints.length === 0 ? (
                  <p className="muted">Pas d'instantané RIB couvrant ce préfixe.</p>
                ) : (
                  <TimeChart
                    points={visPoints}
                    height={200}
                    yDomain={[0, 1]}
                    valueFormat={(v) => `${Math.round(v * 100)}%`}
                    series={[
                      { key: "visibility_ratio", label: "Visibilité", color: PALETTE.ink, kind: "area" },
                    ]}
                    note="Part des couples (collecteur, peer) ayant le préfixe dans leur table au moment de l'instantané."
                  />
                )}
              </section>

              <section className="card">
                <h2>Activité</h2>
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

              <div className="grid cols-2">
                <section className="card">
                  <h2>Chemins d'AS les plus vus</h2>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Chemin</th>
                          <th className="num">Observations</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.top_paths.map((p, i) => (
                          <tr key={i}>
                            <td className="mono">{p.as_path ?? "—"}</td>
                            <td className="num mono">{num(p.observations)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="card-note">
                    Chemins dédupliqués du prepending : un AS répété consécutivement n'est compté
                    qu'une fois.
                  </p>
                </section>

                <section className="card">
                  <h2>Événements</h2>
                  {data.events.length === 0 ? (
                    <p className="muted">Aucun événement détecté sur ce préfixe.</p>
                  ) : (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Détecteur</th>
                            <th>Sévérité</th>
                            <th>Observé</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.events.map((e) => (
                            <tr key={e.event_id}>
                              <td>{detectorLabel(e.detector)}</td>
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
              </div>
            </>
          );
        }}
      </AsyncBlock>
    </div>
  );
}
