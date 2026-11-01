/** Voisins BGP d'un AS, séparés en providers / customers / peerings / unspecified.
 *
 *  L'onglet choisi filtre le graphe (quelles courbes) ET le tableau (quelles
 *  lignes). La liste complète est chargée une fois, puis filtrée côté client :
 *  les voisins d'un AS se comptent en dizaines ou centaines, et le changement
 *  d'onglet reste instantané avec des compteurs toujours exacts.
 */

import { useMemo, useState } from "react";
import { useApi } from "../lib/useApi";
import { rangeParams, type DateRange } from "./DateRangeSelector";
import type {
  NeighbourHistory,
  NeighbourRow,
  NeighbourType,
  NeighboursResponse,
  PrefixStatus,
  Series,
} from "../lib/types";
import { AsyncBlock, EmptyState } from "./StateBlock";
import { AsnLabel, AsnLink } from "./AsnLink";
import { Modal } from "./Modal";
import { DayStrip, PeriodsTable } from "./PeriodsTable";
import { Tabs, type TabOption } from "./Tabs";
import { PALETTE, TimeChart, type ChartSeries } from "./TimeChart";
import { countryLabel } from "../lib/format";

type Tab = NeighbourType | "all";

const TYPE_LABEL: Record<NeighbourType, string> = {
  provider: "fournisseur", customer: "client", peer: "peering", unspecified: "non déterminé",
};

const SERIES: Record<NeighbourType, ChartSeries> = {
  provider: { key: "provider", label: "Fournisseurs", color: PALETTE.ink },
  customer: { key: "customer", label: "Clients", color: PALETTE.teal },
  peer: { key: "peer", label: "Peerings", color: PALETTE.amber },
  unspecified: { key: "unspecified", label: "Non déterminé", color: PALETTE.slate },
};

const TITLES: Record<Tab, string> = {
  all: "Tous les voisins BGP observés",
  provider: "Voisins dont cet AS achète du transit (relation CAIDA : fournisseur)",
  customer: "Voisins qui achètent du transit à cet AS (relation CAIDA : client)",
  peer: "Voisins en peering settlement-free avec cet AS",
  unspecified: "Voisins observés dans les chemins sans relation connue dans CAIDA",
};

/** Périodes de la relation entre l'AS de la page et un voisin, par famille d'adresses. */
function RelationModal({
  asn, neighbour, dates, onClose,
}: {
  asn: string; neighbour: number; dates: Record<string, string>; onClose: () => void;
}) {
  const state = useApi<NeighbourHistory>(`/asns/${asn}/neighbours/${neighbour}/history`, dates);
  return (
    <Modal title="Historique de la relation" onClose={onClose}>
      <dl className="kv" style={{ marginBottom: "0.8rem" }}>
        <dt>AS</dt>
        <dd><AsnLabel asn={Number(asn)} /></dd>
        <dt>Voisin</dt>
        <dd><AsnLabel asn={neighbour} /></dd>
        <dt>Type</dt>
        <dd>{state.data ? TYPE_LABEL[state.data.type] : "…"}</dd>
      </dl>
      <AsyncBlock state={state} rows={3}>
        {(data) => (
          <>
            {(["ipv4", "ipv6"] as const).map((family) => (
              <section key={family} style={{ marginBottom: "0.9rem" }}>
                <h3>{family === "ipv4" ? "IPv4" : "IPv6"}</h3>
                <PeriodsTable
                  runs={data[family]}
                  empty={`Jamais observés côte à côte en ${family === "ipv4" ? "IPv4" : "IPv6"} sur la période.`}
                />
                {data[family].length > 0 && (
                  <p style={{ marginTop: "0.4rem" }}>
                    <DayStrip
                      label={family === "ipv4" ? "IPv4" : "IPv6"}
                      days={data.daily.map((d) => ({ day: d.day, present: d[family] }))}
                    />
                  </p>
                )}
              </section>
            ))}
          </>
        )}
      </AsyncBlock>
      <p className="card-note">
        Deux AS sont voisins quand ils se suivent sur un chemin annoncé ; le type vient des relations
        CAIDA (inférées, donc datées de la dernière synchronisation et non de chaque jour). Une période
        est une suite de jours de collecte consécutifs ; un jour sans donnée ne la coupe pas.
      </p>
    </Modal>
  );
}

function History({ row, days }: { row: NeighbourRow; days: string[] }) {
  const active = new Set(row.history);
  return (
    <span
      className="history"
      role="img"
      aria-label={`Actif ${row.history.length} jour(s) sur ${days.length}`}
      title={`Actif ${row.history.length} jour(s) sur ${days.length}`}
    >
      {days.map((d) => (
        <i key={d} className={active.has(d) ? "on" : ""} title={d} />
      ))}
    </span>
  );
}

type StatusTab = PrefixStatus | "all";

const STATUS_LABEL: Record<PrefixStatus, string> = {
  stable: "stable", new: "new", left: "left", unstable: "unstable",
};

const STATUS_TITLES: Record<Exclude<StatusTab, "all">, string> = {
  new: "Voisins qui n'existaient pas au début de la période sélectionnée et qui existent à sa fin",
  left: "Voisins qui existaient au début de la période sélectionnée, mais ont cessé d'exister avant sa fin",
  unstable: "Voisins apparus puis disparus plusieurs fois pendant la période sélectionnée",
  stable: "Voisins présents chaque jour de la période sélectionnée",
};

/** Page d'un AS (`asn`) ou d'un pays (`country`) ; sur un pays, une colonne indique l'AS
 *  membre dont la ligne décrit le voisin. */
export function NeighbourExplorer({
  asn, country, range,
}: {
  asn?: string;
  country?: string;
  range: DateRange;
}) {
  const base = asn ? `/asns/${asn}` : `/countries/${country}`;
  const [tab, setTab] = useState<Tab>("all");
  const [status, setStatus] = useState<StatusTab>("all");
  const [open, setOpen] = useState<{ member: string; neighbour: number } | null>(null);
  const dates = rangeParams(range);
  const series = useApi<Series>(`${base}/neighbours/timeseries`, dates);
  const table = useApi<NeighboursResponse>(`${base}/neighbours`, dates);

  const options: Array<TabOption<Tab>> = useMemo(() => {
    const counts = table.data?.counts;
    const total = table.data?.items.length;
    return [
      { value: "all", label: "Tous", title: TITLES.all, count: total },
      { value: "provider", label: "Fournisseurs", title: TITLES.provider, count: counts?.provider },
      { value: "customer", label: "Clients", title: TITLES.customer, count: counts?.customer },
      { value: "peer", label: "Peerings", title: TITLES.peer, count: counts?.peer },
      { value: "unspecified", label: "Non déterminé", title: TITLES.unspecified, count: counts?.unspecified },
    ];
  }, [table.data]);

  // Les décomptes des onglets d'évolution suivent le type choisi : « New (2) » doit dire
  // combien de lignes l'onglet affichera, pas combien il y en a en tout.
  const statusOptions: Array<TabOption<StatusTab>> = useMemo(() => {
    const items = (table.data?.items ?? []).filter((r) => tab === "all" || r.type === tab);
    const count = (s: PrefixStatus) => items.filter((r) => r.status === s).length;
    return [
      { value: "all", label: "Tous", count: items.length },
      { value: "new", label: "New", title: STATUS_TITLES.new, count: count("new") },
      { value: "left", label: "Left", title: STATUS_TITLES.left, count: count("left") },
      { value: "unstable", label: "Unstable", title: STATUS_TITLES.unstable, count: count("unstable") },
    ];
  }, [table.data, tab]);

  const visibleSeries: ChartSeries[] =
    tab === "all" ? Object.values(SERIES) : [SERIES[tab]];

  return (
    <section className="card">
      <h2>Voisins BGP</h2>
      <Tabs options={options} value={tab} onChange={setTab} label="Type de voisin" />

      <AsyncBlock state={series} rows={3}>
        {(data) => (
          <TimeChart
            points={data.points}
            height={210}
            step
            daily
            valueFormat={(v) => String(Math.round(v))}
            series={visibleSeries}
            note="Nombre de voisins distincts observés chaque jour dans les chemins d'AS, par type de relation."
          />
        )}
      </AsyncBlock>

      <AsyncBlock state={table} rows={4}>
        {(data) => {
          const rows = data.items.filter(
            (r) => (tab === "all" || r.type === tab) && (status === "all" || r.status === status),
          );
          if (rows.length === 0) {
            return (
              <>
                <Tabs options={statusOptions} value={status} onChange={setStatus} label="Évolution des voisins" />
                <EmptyState title="Aucun voisin de ce type sur la période">
                  <p>Élargissez la période, ou changez d'onglet.</p>
                </EmptyState>
              </>
            );
          }
          return (
            <>
            <Tabs options={statusOptions} value={status} onChange={setStatus} label="Évolution des voisins" />
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Actif</th>
                    {!asn && <th>AS du pays</th>}
                    <th>{asn ? "AS" : "Voisin"}</th>
                    <th>Pays</th>
                    <th>Type</th>
                    <th>Statut</th>
                    <th>IPv4</th>
                    <th>IPv6</th>
                    <th>Historique</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={`${row.member_asn ?? ""}|${row.asn}`}>
                      <td>
                        <span className={row.active_now ? "dot on" : "dot off"} aria-hidden="true" />
                        {row.active_now ? "oui" : "non"}
                      </td>
                      {!asn && (
                        <td className="mono"><AsnLink asn={row.member_asn ?? 0} className="" /></td>
                      )}
                      <td className="mono"><AsnLink asn={row.asn} className="" /></td>
                      <td>{countryLabel(row.country_iso2)}</td>
                      <td>{TYPE_LABEL[row.type]}</td>
                      <td>
                        {row.status && row.status !== "stable" ? (
                          <span className={`badge status-${row.status}`}>{STATUS_LABEL[row.status]}</span>
                        ) : (
                          <span className="muted">{STATUS_LABEL.stable}</span>
                        )}
                      </td>
                      <td>{row.ipv4 ? "✓" : "—"}</td>
                      <td>{row.ipv6 ? "✓" : "—"}</td>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          aria-label={`Historique détaillé de la relation avec AS${row.asn}`}
                          title="Périodes de la relation, en IPv4 et en IPv6"
                          onClick={() => setOpen({ member: String(row.member_asn ?? asn), neighbour: row.asn })}
                        >
                          <History row={row} days={data.days} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            </>
          );
        }}
      </AsyncBlock>
      <p className="card-note">
        Un voisin est un AS adjacent à celui-ci dans un chemin observé. Son type vient des relations
        CAIDA, qui sont inférées : « non déterminé » signifie qu'aucune relation n'est connue, pas qu'il
        n'y en a pas. Chaque carré de la frise est un jour ; plein = voisin observé ce jour-là. Un clic
        sur la frise ouvre le détail : périodes de la relation, en IPv4 et en IPv6.
      </p>
      {open !== null && (
        <RelationModal
          asn={open.member}
          neighbour={open.neighbour}
          dates={dates}
          onClose={() => setOpen(null)}
        />
      )}
    </section>
  );
}
