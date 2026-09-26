import { useState } from "react";
import { useApi } from "../lib/useApi";
import type {
  PrefixChangeItem,
  PrefixChanges,
  PrefixTimeseries,
  RoaHistoryItem,
  RouteObjectHistoryItem,
} from "../lib/types";
import { AsyncBlock } from "./StateBlock";
import { DateRangePicker } from "./DateRangePicker";
import { Modal } from "./Modal";
import { PALETTE, TimeChart } from "./TimeChart";
import { Tabs } from "./Tabs";
import { changeLabel, day } from "../lib/format";

const FAMILY_TABS = [
  { value: "all", label: "Tout" },
  { value: "4", label: "IPv4" },
  { value: "6", label: "IPv6" },
];

const CHANGE_TABS = [
  { value: "all", label: "Tout" },
  { value: "new", label: "New", title: "Apparues pendant la fenêtre sélectionnée" },
  { value: "left", label: "Left", title: "Disparues pendant la fenêtre sélectionnée" },
  {
    value: "unstable",
    label: "Unstable",
    title: "Apparues puis disparues plusieurs fois pendant la fenêtre sélectionnée",
  },
];

type ModalState = { kind: "roa" | "route-object"; prefix: string } | null;

export function AsnPrefixesPanel({ asn }: { asn: number }) {
  const [family, setFamily] = useState("all");
  const [tab, setTab] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [modal, setModal] = useState<ModalState>(null);

  const range = { from: from || undefined, to: to || undefined };
  const timeseries = useApi<PrefixTimeseries>(`/asns/${asn}/prefixes/timeseries`, {
    family,
    ...range,
  });
  const changes = useApi<PrefixChanges>(`/asns/${asn}/prefixes/changes`, { tab, ...range });

  return (
    <section className="card">
      <h2>Préfixes</h2>
      <DateRangePicker from={from} to={to} onChange={(f, t) => (setFrom(f), setTo(t))} />

      <Tabs options={FAMILY_TABS} value={family} onChange={setFamily} />
      <AsyncBlock state={timeseries} rows={3}>
        {(series) =>
          series.points.length === 0 ? (
            <p className="muted">Aucun préfixe sur cette fenêtre.</p>
          ) : (
            <TimeChart
              points={series.points.map((p) => ({ ts: p.day, values: { prefixes: p.prefixes } }))}
              height={200}
              series={[{ key: "prefixes", label: "Préfixes annoncés", color: PALETTE.ink }]}
            />
          )
        }
      </AsyncBlock>

      <div style={{ marginTop: "1.1rem" }}>
        <Tabs options={CHANGE_TABS} value={tab} onChange={setTab} />
        <AsyncBlock state={changes} rows={3}>
          {(body) =>
            body.items.length === 0 ? (
              <p className="muted">Aucun préfixe dans cette catégorie sur cette fenêtre.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Actif</th>
                      <th>Préfixe</th>
                      <th>RPKI ROA</th>
                      <th>Route Object</th>
                      <th>Changement</th>
                      <th>Première/dernière vue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {body.items.map((item: PrefixChangeItem) => (
                      <tr key={item.prefix}>
                        <td>{item.active ? "Oui" : "Non"}</td>
                        <td className="mono">{item.prefix}</td>
                        <td>
                          {item.has_roa ? (
                            <button type="button" onClick={() => setModal({ kind: "roa", prefix: item.prefix })}>
                              Voir
                            </button>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>
                          {item.has_route_object ? (
                            <button
                              type="button"
                              onClick={() => setModal({ kind: "route-object", prefix: item.prefix })}
                            >
                              Voir
                            </button>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>{changeLabel(item.change)}</td>
                        <td className="mono">
                          {day(item.first_seen)} → {day(item.last_seen)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          }
        </AsyncBlock>
      </div>

      {modal && (
        <HistoryModal
          kind={modal.kind}
          prefix={modal.prefix}
          asn={asn}
          from={from}
          to={to}
          onClose={() => setModal(null)}
        />
      )}
    </section>
  );
}

function HistoryModal({
  kind,
  prefix,
  asn,
  from,
  to,
  onClose,
}: {
  kind: "roa" | "route-object";
  prefix: string;
  asn: number;
  from: string;
  to: string;
  onClose: () => void;
}) {
  const path = `/prefixes/${encodeURIComponent(prefix)}/${kind}-history`;
  const state = useApi<{ items: (RoaHistoryItem | RouteObjectHistoryItem)[] }>(path, {
    from: from || undefined,
    to: to || undefined,
  });
  const title = kind === "roa" ? "Historique RPKI ROA" : "Historique Route Object (IRR)";

  return (
    <Modal title={title} onClose={onClose}>
      <div className="kv" style={{ marginBottom: "0.8rem" }}>
        <dt>Préfixe</dt>
        <dd className="mono">{prefix}</dd>
        <dt>AS spécifié</dt>
        <dd className="mono">AS{asn}</dd>
      </div>
      <AsyncBlock state={state} rows={2}>
        {(body) =>
          body.items.length === 0 ? (
            <p className="muted">Aucun historique disponible pour ce préfixe.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Origine</th>
                    {kind === "roa" ? (
                      <>
                        <th>Trust Anchor</th>
                        <th className="num">Longueur max</th>
                      </>
                    ) : (
                      <th>Source</th>
                    )}
                    <th>Vue (UTC)</th>
                    <th>Changement</th>
                    <th>Correspond à l'origine actuelle</th>
                  </tr>
                </thead>
                <tbody>
                  {body.items.map((row, i) => (
                    <tr key={i}>
                      <td className="mono">AS{row.asn}</td>
                      {kind === "roa" ? (
                        <>
                          <td>{(row as RoaHistoryItem).ta}</td>
                          <td className="num mono">/{(row as RoaHistoryItem).max_len}</td>
                        </>
                      ) : (
                        <td>{(row as RouteObjectHistoryItem).source}</td>
                      )}
                      <td className="mono">
                        {day(row.first_seen)} → {day(row.last_seen)}
                      </td>
                      <td>{changeLabel(row.change)}</td>
                      <td>{row.match ? "Oui" : "Non"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </AsyncBlock>
    </Modal>
  );
}
