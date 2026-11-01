/** Périodes de présence et frise quotidienne : l'historique détaillé d'un préfixe
 *  ou d'une relation. Le tableau dit « quand », la frise dit « quels jours »,
 *  trous compris. */

import type { PeriodRun } from "../lib/types";
import { num } from "../lib/format";

export function PeriodsTable({
  runs,
  withObservations = false,
  empty,
}: {
  runs: PeriodRun[];
  withObservations?: boolean;
  empty: string;
}) {
  if (runs.length === 0) return <p className="muted">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Début</th>
            <th>Fin</th>
            <th className="num">Jours</th>
            {withObservations && <th className="num">Annonces</th>}
            <th>État</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.first_seen}>
              <td className="mono">{run.first_seen}</td>
              <td className="mono">{run.last_seen}</td>
              <td className="num mono">{num(run.days)}</td>
              {withObservations && <td className="num mono">{num(run.observations ?? 0)}</td>}
              <td>
                {run.active ? (
                  <span className="badge reassuring">en cours</span>
                ) : (
                  <span className="muted">terminée</span>
                )}
              </td>
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
