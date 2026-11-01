/** Préfixes originés par un AS : courbe du nombre total, onglets IPv4/IPv6,
 *  tableau New / Left / Unstable, et modales d'historique ROA / objet route.
 *
 *  La plage de dates appartient à la page : la poignée de sélection du graphe
 *  la modifie via `onRangeChange`, ce qui recalcule le tableau juste en dessous
 *  (et tous les autres graphes de la page) — un événement du graphe pilote donc
 *  bien le tableau.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { rangeParams, type DateRange } from "./DateRangeSelector";
import type {
  HistoryResponse,
  Page,
  PrefixAnnouncementHistory,
  PrefixRow,
  PrefixStatus,
  Series,
} from "../lib/types";
import { AsyncBlock, EmptyState } from "./StateBlock";
import { Modal } from "./Modal";
import { AsnLabel, AsnLink } from "./AsnLink";
import { Tabs, type TabOption } from "./Tabs";
import { PALETTE, TimeChart } from "./TimeChart";
import { num } from "../lib/format";
import { DayStrip, PeriodsTable } from "./PeriodsTable";

type IpTab = "all" | "4" | "6";

const IP_TABS: Array<TabOption<IpTab>> = [
  { value: "all", label: "Tous" },
  { value: "4", label: "IPv4" },
  { value: "6", label: "IPv6" },
];

const STATUS_TABS: Array<TabOption<PrefixStatus | "all">> = [
  { value: "all", label: "Tous" },
  {
    value: "new",
    label: "New",
    title: "Préfixes qui n'existaient pas au début de la période sélectionnée et qui existent à sa fin",
  },
  {
    value: "left",
    label: "Left",
    title: "Préfixes qui existaient au début de la période sélectionnée, mais ont cessé d'exister avant sa fin",
  },
  {
    value: "unstable",
    label: "Unstable",
    title: "Préfixes apparus puis disparus plusieurs fois pendant la période sélectionnée",
  },
];

const STATUS_LABEL: Record<PrefixStatus, string> = {
  stable: "stable", new: "new", left: "left", unstable: "unstable",
};

const RPKI_LABEL: Record<PrefixRow["rpki_status"], string> = {
  valid: "valide", invalid: "invalide", "not-found": "aucun ROA",
};
const IRR_LABEL: Record<PrefixRow["irr_status"], string> = {
  irr_consistent: "présent", irr_inconsistent: "incohérent", irr_absent: "aucun",
};

const PAGE_SIZE = 25;
const isoDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);

type ModalState = { kind: "roa" | "route" | "periods"; prefix: string; asn: string } | null;

/** Périodes pendant lesquelles cet AS a annoncé le préfixe, trous compris. */
function PeriodsModal({
  asn, prefix, dates, onClose,
}: {
  asn: string; prefix: string; dates: Record<string, string>; onClose: () => void;
}) {
  const state = useApi<PrefixAnnouncementHistory>(`/asns/${asn}/prefixes/${prefix}/history`, dates);
  return (
    <Modal title="Historique d'annonce du préfixe" onClose={onClose}>
      <dl className="kv" style={{ marginBottom: "0.8rem" }}>
        <dt>Préfixe</dt>
        <dd className="mono">{prefix}</dd>
        <dt>AS d'origine</dt>
        <dd><AsnLabel asn={Number(asn)} /></dd>
      </dl>
      <AsyncBlock state={state} rows={3}>
        {(data) => (
          <>
            <PeriodsTable
              runs={data.items}
              withObservations
              empty="Cet AS n'a pas annoncé ce préfixe sur la période."
            />
            {data.daily.length > 0 && (
              <p style={{ marginTop: "0.8rem" }}>
                <DayStrip
                  label="Annonces"
                  days={data.daily.map((d) => ({ day: d.day, present: d.observations > 0 }))}
                />{" "}
                <span className="muted">{data.start} → {data.end}</span>
              </p>
            )}
          </>
        )}
      </AsyncBlock>
      <p className="card-note">
        Une période est une suite de jours de collecte consécutifs où l'AS annonce le préfixe ; un
        trou entre deux périodes est une interruption (retrait ou absence d'annonce). Un jour sans
        aucune donnée collectée ne coupe pas une période. « Annonces » compte les messages BGP.
      </p>
    </Modal>
  );
}

function HistoryModal({ asn, modal, onClose }: { asn: string; modal: NonNullable<ModalState>; onClose: () => void }) {
  const slug = modal.kind === "roa" ? "roa-history" : "route-history";
  const state = useApi<HistoryResponse>(`/asns/${asn}/prefixes/${modal.prefix}/${slug}`);
  const isRoa = modal.kind === "roa";

  return (
    <Modal title={isRoa ? "Historique RPKI ROA" : "Historique des objets route"} onClose={onClose}>
      <dl className="kv" style={{ marginBottom: "0.8rem" }}>
        <dt>Préfixe</dt>
        <dd className="mono">{modal.prefix}</dd>
        <dt>AS spécifié</dt>
        <dd><AsnLabel asn={Number(asn)} /></dd>
      </dl>
      <AsyncBlock state={state} rows={3}>
        {(data) =>
          data.rows.length === 0 ? (
            <EmptyState title={isRoa ? "Aucun ROA publié pour ce préfixe" : "Aucun objet route pour ce préfixe"}>
              <p>
                {isRoa
                  ? "L'absence de ROA ne prouve rien : c'est le cas de la majorité des préfixes de la zone AFRINIC."
                  : "Aucun registre interrogé ne déclare d'objet route pour ce préfixe."}
              </p>
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Préfixe</th>
                    <th>Origine</th>
                    {isRoa ? <th>Trust Anchor</th> : <th>Source</th>}
                    {isRoa && <th className="num">Longueur max.</th>}
                    <th>Première observation (UTC)</th>
                    <th>Dernière observation (UTC)</th>
                    <th>Concordance</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row, i) => (
                    <tr key={i}>
                      <td className="mono">{row.prefix}</td>
                      <td><AsnLabel asn={row.origin} /></td>
                      {isRoa ? <td>{row.trust_anchor}</td> : <td>{row.source}</td>}
                      {isRoa && <td className="num mono">/{row.max_length}</td>}
                      <td className="mono">{row.first_seen ?? "—"}</td>
                      <td className="mono">{row.last_seen ?? "—"}</td>
                      <td>
                        <span className={row.match ? "badge reassuring" : "badge critical"}>
                          {row.match ? "concorde" : "discorde"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </AsyncBlock>
      <p className="card-note">
        « Concordance » compare l'origine enregistrée à l'AS spécifié ci-dessus. Les dates sont celles des
        instantanés de synchronisation : une ligne « — » signifie qu'aucun historique daté n'a
        encore été collecté.
      </p>
    </Modal>
  );
}

/** Page d'un AS (`asn`) ou page d'un pays (`country`) : même explorateur ; sur un pays,
 *  chaque ligne porte l'AS membre qui annonce le préfixe. */
export function PrefixExplorer({
  asn, country, range, onRangeChange,
}: {
  asn?: string;
  country?: string;
  range: DateRange;
  onRangeChange: (range: DateRange) => void;
}) {
  const base = asn ? `/asns/${asn}` : `/countries/${country}`;
  const owner = (row: PrefixRow) => String(row.origin_asn ?? asn);
  const [ipTab, setIpTab] = useState<IpTab>("all");
  const [status, setStatus] = useState<PrefixStatus | "all">("all");
  const [offset, setOffset] = useState(0);
  const [modal, setModal] = useState<ModalState>(null);

  const dates = rangeParams(range);
  const series = useApi<Series>(`${base}/prefixes/timeseries`, { ip_version: ipTab, ...dates });
  const table = useApi<Page<PrefixRow>>(`${base}/prefixes`, {
    ip_version: ipTab, status: status === "all" ? undefined : status,
    ...dates, limit: PAGE_SIZE, offset,
  });

  const changeIp = (v: IpTab) => { setIpTab(v); setOffset(0); };
  const changeStatus = (v: PrefixStatus | "all") => { setStatus(v); setOffset(0); };

  return (
    <section className="card">
      <h2>Préfixes</h2>
      <Tabs options={IP_TABS} value={ipTab} onChange={changeIp} label="Famille d'adresses" />
      <AsyncBlock state={series} rows={3}>
        {(data) => (
          <TimeChart
            points={data.points}
            height={230}
            brush
            step
            daily
            onBrush={(from, to) => {
              setOffset(0);
              onRangeChange({ from: isoDay(from), to: isoDay(to) });
            }}
            valueFormat={(v) => String(Math.round(v))}
            series={[{ key: "prefixes", label: "Préfixes originés", color: PALETTE.ink, kind: "area" }]}
            note={`Nombre de préfixes distincts annoncés ${asn ? "par cet AS" : "par les AS du pays"} chaque jour. Faire glisser la poignée sous la courbe restreint la période — le tableau ci-dessous suit.`}
          />
        )}
      </AsyncBlock>

      <Tabs options={STATUS_TABS} value={status} onChange={changeStatus} label="Évolution des préfixes" />
      <AsyncBlock state={table} rows={4}>
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState title="Aucun préfixe pour cette sélection">
              <p>Élargissez la période, ou changez d'onglet.</p>
            </EmptyState>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Actif</th>
                      {!asn && <th>AS</th>}
                      <th>Préfixe</th>
                      <th>Statut</th>
                      <th>Vu du — au</th>
                      <th>RPKI ROA</th>
                      <th>Route Object</th>
                      <th>Historique</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((row) => (
                      <tr key={`${row.origin_asn ?? ""}|${row.prefix}`}>
                        <td>
                          <span className={row.active ? "dot on" : "dot off"} aria-hidden="true" />
                          {row.active ? "oui" : "non"}
                        </td>
                        {!asn && (
                          <td className="mono">
                            <AsnLink asn={row.origin_asn ?? 0} className="" />
                          </td>
                        )}
                        <td className="mono">
                          <Link to={`/prefixes/${encodeURIComponent(row.prefix)}`}>{row.prefix}</Link>{" "}
                          <span className="tag">IPv{row.ip_version}</span>
                        </td>
                        <td>
                          {row.status === "stable" ? (
                            <span className="muted">{STATUS_LABEL.stable}</span>
                          ) : (
                            <span className={`badge status-${row.status}`}>{STATUS_LABEL[row.status]}</span>
                          )}
                        </td>
                        <td className="mono">
                          {row.first_seen.slice(0, 10)} — {row.last_seen.slice(0, 10)}
                        </td>
                        <td>
                          <button type="button" className="link-button" onClick={() => setModal({ kind: "roa", prefix: row.prefix, asn: owner(row) })}>
                            {RPKI_LABEL[row.rpki_status]}
                          </button>
                        </td>
                        <td>
                          <button type="button" className="link-button" onClick={() => setModal({ kind: "route", prefix: row.prefix, asn: owner(row) })}>
                            {IRR_LABEL[row.irr_status]}
                          </button>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="link-button"
                            aria-label={`Historique d'annonce de ${row.prefix}`}
                            onClick={() => setModal({ kind: "periods", prefix: row.prefix, asn: owner(row) })}
                          >
                            Périodes
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="row" style={{ justifyContent: "space-between", marginTop: "0.8rem" }}>
                <span className="muted">
                  {num(page.offset + 1)}–{num(Math.min(page.offset + page.limit, page.total))} sur {num(page.total)}
                </span>
                <span className="row">
                  <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Précédent</button>
                  <button disabled={offset + PAGE_SIZE >= page.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Suivant</button>
                </span>
              </div>
            </>
          )
        }
      </AsyncBlock>
      {modal?.kind === "periods" && (
        <PeriodsModal asn={modal.asn} prefix={modal.prefix} dates={dates} onClose={() => setModal(null)} />
      )}
      {modal && modal.kind !== "periods" && (
        <HistoryModal asn={modal.asn} modal={modal} onClose={() => setModal(null)} />
      )}
    </section>
  );
}
