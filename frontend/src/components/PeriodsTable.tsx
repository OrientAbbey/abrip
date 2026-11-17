/** Périodes de présence et frise quotidienne : l'historique détaillé d'un préfixe
 *  ou d'une relation. Le tableau dit « quand », la frise dit « quels jours »,
 *  trous compris. */

import type { PeriodRun } from "../lib/types";
import { num } from "../lib/format";

export function PeriodsTable({
  runs,
  withObservations = false,
  relationType,
  empty,
}: {
  runs: PeriodRun[];
  withObservations?: boolean;
  /** Code CAIDA brut (p2c, c2p, p2p, unknown) pour un historique de relation. */
  relationType?: string;
  empty: string;
}) {
  if (runs.length === 0) return <p className="muted">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Première vue</th>
            <th>Dernière vue</th>
            <th className="num">Jours</th>
            {withObservations && <th className="num">Annonces</th>}
            {relationType && <th>Type</th>}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.first_seen}>
              <td className="mono">{run.first_seen}</td>
              <td className="mono">
                {run.active ? <span className="badge reassuring">Active</span> : run.last_seen}
              </td>
              <td className="num mono">{num(run.days)}</td>
              {withObservations && <td className="num mono">{num(run.observations ?? 0)}</td>}
              {relationType && <td className="mono">{relationType}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Un carré par jour de collecte ; plein = présent ce jour-là. */
export function DayStrip({
  days,
  label,
}: {
  days: Array<{ day: string; present: boolean }>;
  label: string;
}) {
  const present = days.filter((d) => d.present).length;
  const summary = `${label} : présent ${present} jour(s) sur ${days.length}`;
  return (
    <span className="history" role="img" aria-label={summary} title={summary}>
      {days.map((d) => (
        <i key={d.day} className={d.present ? "on" : ""} title={`${d.day} — ${d.present ? "présent" : "absent"}`} />
      ))}
    </span>
  );
}
