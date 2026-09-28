import type { PresencePeriod } from "../lib/types";

/** Tableau de périodes de présence, au format des pages d'historique de
 *  radar.qrator.net : #, première vue, dernière vue (« Active » tant que la
 *  période est en cours), et — pour une relation entre deux AS — le type
 *  sous sa forme brute (p2c, c2p, p2p…), jamais traduit. Les dates sont au
 *  jour près : les données curées sont partitionnées par jour. */
export function PeriodsTable({
  periods,
  withType = false,
  empty = "Aucune période observée sur cette fenêtre.",
}: {
  periods: PresencePeriod[];
  withType?: boolean;
  empty?: string;
}) {
  if (periods.length === 0) return <p className="muted">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Première vue (UTC)</th>
            <th>Dernière vue (UTC)</th>
            {withType && <th>Type</th>}
          </tr>
        </thead>
        <tbody>
          {periods.map((p, i) => (
            <tr key={`${p.first_seen}-${i}`}>
              <td className="num mono">{i + 1}</td>
              <td className="mono">{p.first_seen}</td>
              <td className="mono">{p.active ? "Active" : p.last_seen}</td>
              {withType && <td className="mono">{p.type}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
