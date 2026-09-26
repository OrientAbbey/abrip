import { useState } from "react";
import { useApi } from "../lib/useApi";
import type { NeighborItem, NeighborsResponse } from "../lib/types";
import { AsyncBlock } from "./StateBlock";
import { AsLink } from "./Badges";
import { DateRangePicker } from "./DateRangePicker";
import { Tabs } from "./Tabs";
import { countryLabel, day, num, relationLabel } from "../lib/format";

const RELATION_TABS = [
  { value: "all", label: "Tout" },
  { value: "providers", label: "Fournisseurs" },
  { value: "customers", label: "Clients" },
  { value: "peerings", label: "Peerings" },
  { value: "unspecified", label: "Non déterminé" },
];

const BUCKETS = ["providers", "customers", "peerings", "unspecified"] as const;

export function AsnNeighborsPanel({ asn }: { asn: number }) {
  const [relation, setRelation] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const range = { from: from || undefined, to: to || undefined };

  // Le décompte par relation vient de la fenêtre "all" (jamais refiltrée),
  // pour que les barres restent une vue d'ensemble stable pendant qu'on
  // bascule d'un onglet à l'autre dans le tableau en dessous.
  const overview = useApi<NeighborsResponse>(`/asns/${asn}/neighbors`, range);
  const filtered = useApi<NeighborsResponse>(`/asns/${asn}/neighbors`, { relation, ...range });

  return (
    <section className="card">
      <h2>Voisins BGP</h2>
      <DateRangePicker from={from} to={to} onChange={(f, t) => (setFrom(f), setTo(t))} />

      <AsyncBlock state={overview} rows={2}>
        {(body) => {
          const counts = Object.fromEntries(BUCKETS.map((b) => [b, 0])) as Record<string, number>;
          for (const item of body.items) counts[item.relation] += 1;
          const max = Math.max(1, ...BUCKETS.map((b) => counts[b]));
          return (
            <div className="bars">
              {BUCKETS.map((b) => (
                <div className="bar-row" key={b}>
                  <span>{relationLabel(b)}</span>
                  <span className="bar-track">
                    <span className="bar-fill" style={{ width: `${(counts[b] / max) * 100}%` }} />
                  </span>
                  <span className="mono num">{num(counts[b])}</span>
                </div>
              ))}
            </div>
          );
        }}
      </AsyncBlock>

      <div style={{ marginTop: "1.1rem" }}>
        <Tabs options={RELATION_TABS} value={relation} onChange={setRelation} />
        <AsyncBlock state={filtered} rows={3}>
          {(body) =>
            body.items.length === 0 ? (
              <p className="muted">Aucun voisin dans cette catégorie sur cette fenêtre.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Actif</th>
                      <th>AS</th>
                      <th>Pays</th>
                      <th>Type</th>
                      <th>IPv4</th>
                      <th>IPv6</th>
                      <th>Historique</th>
                    </tr>
                  </thead>
                  <tbody>
                    {body.items.map((item: NeighborItem) => (
                      <tr key={item.asn}>
                        <td>{item.active ? "Oui" : "Non"}</td>
                        <td>
                          <AsLink asn={item.asn} name={item.as_name} />
                        </td>
                        <td>{countryLabel(item.country_iso2)}</td>
                        <td>{relationLabel(item.relation)}</td>
                        <td>{item.has_v4 ? `Oui (${num(item.v4_prefixes)})` : "Non"}</td>
                        <td>{item.has_v6 ? `Oui (${num(item.v6_prefixes)})` : "Non"}</td>
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
      <p className="card-note">
        Un voisin est l'AS immédiatement adjacent dans un chemin observé — pas de complétion vers
        des AS non vus sur un chemin réel. « Non déterminé » signifie une relation absente du
        référentiel CAIDA, pas nécessairement inexistante.
      </p>
    </section>
  );
}
