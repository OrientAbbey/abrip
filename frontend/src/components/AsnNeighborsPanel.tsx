import { useState } from "react";
import { useApi } from "../lib/useApi";
import type { NeighborHistory, NeighborItem, NeighborsResponse, NeighborTimeseries } from "../lib/types";
import { AsyncBlock } from "./StateBlock";
import { AsLink } from "./Badges";
import { DateRangePicker } from "./DateRangePicker";
import { Modal } from "./Modal";
import { PeriodsTable } from "./PeriodsTable";
import { PALETTE, TimeChart } from "./TimeChart";
import { Tabs } from "./Tabs";
import { changeLabel, countryLabel, relationLabel } from "../lib/format";

const RELATION_TABS = [
  { value: "all", label: "Tout" },
  { value: "providers", label: "Fournisseurs" },
  { value: "customers", label: "Clients" },
  { value: "peerings", label: "Peerings" },
  { value: "unspecified", label: "Non déterminé" },
];

const CHANGE_TABS = [
  { value: "all", label: "Tout" },
  { value: "new", label: "New", title: "Relations apparues pendant la fenêtre sélectionnée" },
  { value: "left", label: "Left", title: "Relations disparues pendant la fenêtre sélectionnée" },
  {
    value: "unstable",
    label: "Unstable",
    title: "Relations apparues puis disparues plusieurs fois pendant la fenêtre sélectionnée",
  },
];

type ModalState = { member: number; neighbor: number; neighborName: string | null } | null;

/** Onglet Voisins BGP : réutilisé tel quel pour une fiche ASN (`basePath`
 *  `/asns/{asn}`) et pour une fiche pays (`/countries/{iso2}`).
 *
 *  Les onglets de relation (Tout/Fournisseurs/Clients/Peerings/Non
 *  déterminé) sont globaux à la section : ils gouvernent à la fois la
 *  courbe et le tableau. Les onglets New/Left/Unstable ne concernent que le
 *  tableau, comme sur l'onglet Préfixes.
 *
 *  `showMember` ajoute une colonne "Membre" (quel AS du pays observe ce
 *  voisin) — sans objet pour un seul AS. `originAsn` (mode ASN uniquement)
 *  sert à ouvrir l'historique de la relation, qui est toujours adressé par
 *  paire d'AS. */
export function AsnNeighborsPanel({
  basePath,
  showMember = false,
  originAsn,
  originName,
}: {
  basePath: string;
  showMember?: boolean;
  originAsn?: number;
  originName?: string | null;
}) {
  const [relation, setRelation] = useState("all");
  const [tab, setTab] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [modal, setModal] = useState<ModalState>(null);
  const range = { from: from || undefined, to: to || undefined };

  const timeseries = useApi<NeighborTimeseries>(`${basePath}/neighbors/timeseries`, {
    relation,
    ...range,
  });
  const neighbors = useApi<NeighborsResponse>(`${basePath}/neighbors`, { relation, tab, ...range });

  return (
    <section className="card">
      <h2>Voisins BGP</h2>
      <DateRangePicker from={from} to={to} onChange={(f, t) => (setFrom(f), setTo(t))} />

      <Tabs options={RELATION_TABS} value={relation} onChange={setRelation} />
      <AsyncBlock state={timeseries} rows={3}>
        {(series) =>
          series.points.length === 0 ? (
            <p className="muted">Aucun voisin observé sur cette fenêtre.</p>
          ) : (
            <TimeChart
              points={series.points.map((p) => ({ ts: p.day, values: { neighbors: p.neighbors } }))}
              height={200}
              series={[
                {
                  key: "neighbors",
                  label: `Voisins — ${relation === "all" ? "toutes relations" : relationLabel(relation)}`,
                  color: PALETTE.ink,
                  kind: "area",
                },
              ]}
            />
          )
        }
      </AsyncBlock>

      <div style={{ marginTop: "1.1rem" }}>
        <Tabs options={CHANGE_TABS} value={tab} onChange={setTab} />
        <AsyncBlock state={neighbors} rows={3}>
          {(body) =>
            body.items.length === 0 ? (
              <p className="muted">Aucun voisin dans cette catégorie sur cette fenêtre.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {showMember && <th>Membre</th>}
                      <th>Actif</th>
                      <th>AS</th>
                      <th>Pays</th>
                      <th>Type</th>
                      <th>IPv4</th>
                      <th>IPv6</th>
                      <th>Changement</th>
                      <th>Historique</th>
                    </tr>
                  </thead>
                  <tbody>
                    {body.items.map((item: NeighborItem, i: number) => {
                      const member = item.member_asn ?? originAsn;
                      return (
                        <tr key={`${item.member_asn ?? ""}-${item.asn}-${i}`}>
                          {showMember && (
                            <td>{item.member_asn ? <AsLink asn={item.member_asn} /> : "—"}</td>
                          )}
                          <td>{item.active ? "Oui" : "Non"}</td>
                          <td>
                            <AsLink asn={item.asn} name={item.as_name} />
                          </td>
                          <td>{countryLabel(item.country_iso2)}</td>
                          <td>{relationLabel(item.relation)}</td>
                          <td>{item.has_v4 ? "Oui" : "Non"}</td>
                          <td>{item.has_v6 ? "Oui" : "Non"}</td>
                          <td>{changeLabel(item.change)}</td>
                          <td>
                            {member !== undefined ? (
                              <button
                                type="button"
                                onClick={() =>
                                  setModal({ member, neighbor: item.asn, neighborName: item.as_name })
                                }
                              >
                                Voir
                              </button>
                            ) : (
                              "—"
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )
          }
        </AsyncBlock>
      </div>
      <p className="card-note">
        Un voisin est l'AS immédiatement adjacent dans un chemin observé — pas de complétion vers
        des AS non vus sur un chemin réel. « Non déterminé » signifie une relation absente du
        référentiel CAIDA, pas nécessairement inexistante.
      </p>

      {modal && (
        <NeighborHistoryModal
          member={modal.member}
          memberName={modal.member === originAsn ? (originName ?? null) : null}
          neighbor={modal.neighbor}
          neighborName={modal.neighborName}
          from={from}
          to={to}
          onClose={() => setModal(null)}
        />
      )}
    </section>
  );
}

function NeighborHistoryModal({
  member,
  memberName,
  neighbor,
  neighborName,
  from,
  to,
  onClose,
}: {
  member: number;
  memberName: string | null;
  neighbor: number;
  neighborName: string | null;
  from: string;
  to: string;
  onClose: () => void;
}) {
  const state = useApi<NeighborHistory>(`/asns/${member}/neighbors/${neighbor}/history`, {
    from: from || undefined,
    to: to || undefined,
  });

  return (
    <Modal title="Historique de la relation entre deux AS" onClose={onClose}>
      <p>
        Historique du lien entre <AsLink asn={member} name={memberName} /> et{" "}
        <AsLink asn={neighbor} name={neighborName} />.
      </p>
      <AsyncBlock state={state} rows={2}>
        {(body) => (
          <>
            <h3>Historique IPv4</h3>
            <PeriodsTable periods={body.ipv4} withType empty="Aucune période IPv4 sur cette fenêtre." />
            <h3 style={{ marginTop: "1rem" }}>Historique IPv6</h3>
            <PeriodsTable periods={body.ipv6} withType empty="Aucune période IPv6 sur cette fenêtre." />
          </>
        )}
      </AsyncBlock>
    </Modal>
  );
}
