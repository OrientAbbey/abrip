import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useApi, useTitle } from "../lib/useApi";
import { useAsnName } from "../lib/useAsnNames";
import { defaultRange, useDataBounds } from "../lib/useDataBounds";
import type { Series } from "../lib/types";
import { AsnLink } from "../components/AsnLink";
import { DateRangeSelector, rangeParams, type DateRange } from "../components/DateRangeSelector";
import { NeighbourExplorer } from "../components/NeighbourExplorer";
import { PrefixExplorer } from "../components/PrefixExplorer";
import { AsyncBlock } from "../components/StateBlock";
import { Tabs, type TabOption } from "../components/Tabs";
import { Term } from "../components/Term";
import { SeverityBadge } from "../components/Badges";
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

type View = "prefixes" | "neighbours" | "transit" | "activity" | "events";
const VIEWS: View[] = ["prefixes", "neighbours", "transit", "activity", "events"];

/** Sections de la page, une à la fois : la page d'un AS réunit cinq blocs denses, qui la
 *  rendaient longue. La période analysée, au-dessus, reste commune à tous. */
const viewOptions = (events: number): Array<TabOption<View>> => [
  { value: "prefixes", label: "Préfixes", title: "Préfixes annoncés par cet AS, avec leur évolution" },
  { value: "neighbours", label: "Voisins BGP", title: "Fournisseurs, clients et pairs observés" },
  { value: "transit", label: "Transit", title: "Dépendance aux fournisseurs et concentration (HHI)" },
  { value: "activity", label: "Activité", title: "Annonces et retraits dans le temps" },
  { value: "events", label: "Événements", title: "Événements détectés impliquant cet AS", count: events },
];

export default function AsnDetail() {
  const { asn = "" } = useParams();
  useTitle(`AS${asn}`);
  const detail = useApi<AsnDetailData>(`/asns/${encodeURIComponent(asn)}`);
  const bounds = useDataBounds();
  const [range, setRange] = useState<DateRange>({ from: "", to: "" });
  // La section vit dans l'adresse (?section=voisins) : un lien partagé ou un rechargement
  // retombe sur la même section.
  const [params, setParams] = useSearchParams();
  const requested = params.get("section") as View | null;
  const view: View = VIEWS.includes(requested as View) ? (requested as View) : "prefixes";
  const setView = (next: View) =>
    setParams(
      (previous) => {
        const query = new URLSearchParams(previous);
        if (next === "prefixes") query.delete("section");
        else query.set("section", next);
        return query;
      },
      { replace: true },
    );
  const effectiveRange = range.from ? range : defaultRange(bounds);
  const churn = useApi<Series>("/metrics/churn", { asn, ...rangeParams(effectiveRange) });
  const upstream = useApi<Series>("/metrics/upstreams", { asn, ...rangeParams(effectiveRange) });
  const asnName = useAsnName(asn);

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
          return (
            <>
              <div className="page-head">
                <h1 className="mono">
                  AS{data.asn}
                  {asnName && <span className="muted" style={{ fontFamily: "var(--font-sans)" }}> · {asnName}</span>}
                </h1>
                <div className="row" style={{ marginTop: "0.4rem" }}>
                  <span className="tag">{countryLabel(country)}</span>
                  {rir && <span className="tag">{String(rir).toUpperCase()}</span>}
                  {allocation && <span className="tag mono">alloué {allocation}</span>}
                  <span className="tag">{num(data.prefixes.length)} préfixes observés</span>
                </div>
              </div>

              <section className="card">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <h2>Période analysée</h2>
                  <DateRangeSelector bounds={bounds} value={effectiveRange} onChange={setRange} />
                </div>
                <p className="card-note">
                  S'applique à tous les graphiques et tableaux de cette page. Faire glisser la
                  poignée sous la courbe des préfixes restreint la période.
                </p>
              </section>

              <Tabs options={viewOptions(data.events.length)} value={view} onChange={setView} label="Sections de la page" />

              {view === "prefixes" && (
                <>
                  <section className="card">
                    <h2>Préfixes annoncés</h2>
                    {data.prefixes.length === 0 ? (
                      <p className="muted">Aucun préfixe observé pour cet AS.</p>
                    ) : (
                      <>
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
                              {data.prefixes.slice(0, 25).map((prefix) => (
                                <tr key={prefix.prefix}>
                                  <td className="mono">
                                    <Link to={`/prefixes/${encodeURIComponent(prefix.prefix)}`}>
                                      {prefix.prefix}
                                    </Link>
                                  </td>
                                  <td className="num mono">{num(prefix.updates)}</td>
                                  <td className="num mono">{num(prefix.peers)}</td>
                                  <td className="mono">{day(prefix.last_seen)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        {data.prefixes.length > 25 && (
                          <p className="card-note">
                            25 premiers préfixes sur {num(data.prefixes.length)} ; l'explorateur
                            ci-dessous donne la liste complète.
                          </p>
                        )}
                      </>
                    )}
                  </section>
                  <PrefixExplorer asn={asn} range={effectiveRange} onRangeChange={setRange} />
                </>
              )}

              {view === "neighbours" && <NeighbourExplorer asn={asn} range={effectiveRange} />}

              {view === "transit" && (
                <>
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
                            <th className="num"><Term k="upstreams">Fournisseurs</Term></th>
                            <th className="num"><Term k="hhi">HHI</Term></th>
                            <th className="num"><Term k="windows" /></th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.upstreams.map((u, i) => (
                            <tr key={i}>
                              <td className="mono">
                                {u.primary_upstream ? (
                                  <AsnLink asn={u.primary_upstream} />
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

              <section className="card">
                <h2><Term k="hhi" /></h2>
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
                </>
              )}

              {view === "activity" && (
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

              )}

              {view === "events" && (
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
              )}
            </>
          );
        }}
      </AsyncBlock>
    </div>
  );
}
