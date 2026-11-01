import { NeighbourExplorer } from "../components/NeighbourExplorer";
import { PrefixExplorer } from "../components/PrefixExplorer";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi, useTitle } from "../lib/useApi";
import { defaultRange, useDataBounds } from "../lib/useDataBounds";
import type { AsnSummary, CountryRelation, CountryRelationships, Page, Series } from "../lib/types";
import { AsnLink } from "../components/AsnLink";
import { DateRangeSelector, rangeParams, type DateRange } from "../components/DateRangeSelector";
import { AsyncBlock, EmptyState } from "../components/StateBlock";
import { Tabs, type TabOption } from "../components/Tabs";
import { Term } from "../components/Term";
import { PALETTE, TimeChart } from "../components/TimeChart";
import { countryLabel, dec, num } from "../lib/format";

type Tab = "asns" | "providers" | "customers" | "peers";

const TITLES: Record<Tab, string> = {
  asns: "Systèmes autonomes alloués à ce pays et observés",
  providers: "AS étrangers au pays qui lui vendent du transit (relation CAIDA : fournisseur)",
  customers: "AS étrangers au pays qui lui achètent du transit (relation CAIDA : client)",
  peers: "AS étrangers au pays en peering settlement-free avec l'un de ses AS",
};

function RelationTable({ rows }: { rows: CountryRelation[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState title="Aucune relation de ce type connue">
        <p>
          Les relations viennent de CAIDA et sont inférées : leur absence ne prouve pas
          qu'aucun lien n'existe.
        </p>
      </EmptyState>
    );
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>AS</th>
            <th>Pays</th>
            <th className="num">AS du pays reliés</th>
            <th>Lesquels</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.asn}>
              <td className="mono"><AsnLink asn={row.asn} className="" /></td>
              <td>{countryLabel(row.country_iso2)}</td>
              <td className="num mono">{num(row.local_asns.length)}</td>
              <td className="mono">
                {row.local_asns.slice(0, 4).map((asn) => (
                  <span key={asn} style={{ marginRight: "0.6rem" }}>
                    <Link to={`/asns/${asn}`}>AS{asn}</Link>
                  </span>
                ))}
                {row.local_asns.length > 4 && <span className="muted">+{row.local_asns.length - 4}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CountryDetail() {
  const { iso2 = "" } = useParams();
  const code = iso2.toUpperCase();
  useTitle(countryLabel(code));

  const bounds = useDataBounds();
  const [range, setRange] = useState<DateRange>({ from: "", to: "" });
  const effectiveRange = range.from ? range : defaultRange(bounds);
  const [tab, setTab] = useState<Tab>("asns");

  const relations = useApi<CountryRelationships>(`/countries/${code}/relationships`);
  const trend = useApi<Series>("/metrics/countries", { country: code, ...rangeParams(effectiveRange) });
  const asns = useApi<Page<AsnSummary>>("/asns", { country: code, limit: 200 });

  const options: Array<TabOption<Tab>> = [
    { value: "asns", label: "AS", title: TITLES.asns, count: relations.data?.asns.length },
    { value: "providers", label: "Fournisseurs", title: TITLES.providers, count: relations.data?.providers.length },
    { value: "customers", label: "Clients", title: TITLES.customers, count: relations.data?.customers.length },
    { value: "peers", label: "Peerings", title: TITLES.peers, count: relations.data?.peers.length },
  ];

  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }}>
        <Link to="/countries">← Retour aux pays</Link>
      </p>

      <div className="page-head">
        <h1>
          {countryLabel(code)} <span className="muted mono" style={{ fontSize: "1.1rem" }}>{code}</span>
        </h1>
        <p>
          Systèmes autonomes du pays, et AS extérieurs qui lui fournissent du transit, en
          achètent, ou font du peering avec lui.
        </p>
      </div>

      <section className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Tendance</h2>
          <DateRangeSelector bounds={bounds} value={effectiveRange} onChange={setRange} />
        </div>
        <AsyncBlock state={trend} rows={3}>
          {(data) => (
            <TimeChart
              points={data.points}
              height={230}
              yDomain={[0, 1]}
              valueFormat={(v) => dec(v, 2)}
              series={[
                { key: "transit_dependency_ratio", label: "Dépendance au transit étranger", color: PALETTE.crimson },
                { key: "hhi_transit", label: "Concentration du transit (HHI)", color: PALETTE.amber },
                { key: "visibility", label: "Visibilité moyenne", color: PALETTE.teal },
              ]}
            />
          )}
        </AsyncBlock>
        <p className="card-note">
          <Term k="dependency" />, <Term k="hhi" /> et <Term k="visibility" /> : survolez un terme
          pour sa définition.
        </p>
      </section>

      <section className="card">
        <h2>Systèmes autonomes et relations</h2>
        <Tabs options={options} value={tab} onChange={setTab} label="Type de relation" />

        {tab === "asns" ? (
          <AsyncBlock state={asns} rows={4}>
            {(page) =>
              page.items.length === 0 ? (
                <EmptyState title="Aucun AS observé pour ce pays" />
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>AS</th>
                        <th className="num">Préfixes</th>
                        <th className="num"><Term k="upstreams" /></th>
                        <th>Transit principal</th>
                        <th className="num"><Term k="hhi" /></th>
                        <th className="num">Événements</th>
                      </tr>
                    </thead>
                    <tbody>
                      {page.items.map((a) => (
                        <tr key={a.asn}>
                          <td className="mono"><AsnLink asn={a.asn} className="" /></td>
                          <td className="num mono">{num(a.prefixes)}</td>
                          <td className="num mono">{num(a.upstream_count)}</td>
                          <td className="mono">
                            {a.primary_upstream ? <AsnLink asn={a.primary_upstream} className="" /> : "—"}
                          </td>
                          <td className="num mono">{dec(a.hhi_transit)}</td>
                          <td className="num mono">{num(a.open_events)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </AsyncBlock>
        ) : (
          <AsyncBlock state={relations} rows={4}>
            {(data) => <RelationTable rows={data[tab]} />}
          </AsyncBlock>
        )}
        <p className="card-note">
          Un fournisseur ou un pair est classé du point de vue du pays : il est relié à au moins un
          de ses AS et n'en fait pas partie. Les relations sont celles de CAIDA, inférées des chemins
          observés.
        </p>
      </section>

      <PrefixExplorer country={code} range={effectiveRange} onRangeChange={setRange} />
      <NeighbourExplorer country={code} range={effectiveRange} />
    </div>
  );
}
