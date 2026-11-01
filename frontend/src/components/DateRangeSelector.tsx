/** Sélecteur de plage de dates, commun à tous les graphiques temporels.
 *
 * L'API accepte déjà `from`/`to` sur ses routes de métriques : ce qui
 * manquait n'était pas la flexibilité côté serveur, mais un contrôle côté
 * interface pour en profiter, aussi bien sur les données de démonstration
 * (7 jours) qu'en conditions réelles (potentiellement des mois d'historique).
 */

import { useEffect, useState } from "react";

export interface DateRange {
  from: string; // AAAA-MM-JJ
  to: string;
}

const PRESETS: Array<{ label: string; days: number | null }> = [
  { label: "7 j", days: 7 },
  { label: "30 j", days: 30 },
  { label: "Tout", days: null },
];

function toInputDate(value: string): string {
  return value.slice(0, 10);
}

export function DateRangeSelector({
  bounds,
  value,
  onChange,
}: {
  /** Bornes disponibles (ex. tirées de `/api/health`) ; sans elles, les
   *  champs restent ouverts mais aucun préréglage n'est proposé. */
  bounds?: { min: string; max: string } | null;
  value: DateRange;
  onChange: (range: DateRange) => void;
}) {
  const [draft, setDraft] = useState(value);

  useEffect(() => setDraft(value), [value.from, value.to]);

  const apply = (range: DateRange) => {
    setDraft(range);
    onChange(range);
  };

  const applyPreset = (days: number | null) => {
    if (!bounds) return;
    const max = toInputDate(bounds.max);
    if (days === null) {
      apply({ from: toInputDate(bounds.min), to: max });
      return;
    }
    const end = new Date(`${max}T00:00:00Z`);
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - (days - 1));
    const min = toInputDate(bounds.min);
    const from = start.toISOString().slice(0, 10);
    apply({ from: from < min ? min : from, to: max });
  };

  return (
    <div className="filters" role="group" aria-label="Plage de dates">
      <div className="field">
        <label htmlFor="date-from">Du</label>
        <input
          id="date-from"
          type="date"
          value={draft.from}
          min={bounds ? toInputDate(bounds.min) : undefined}
          max={draft.to}
          onChange={(e) => apply({ ...draft, from: e.target.value })}
        />
      </div>
      <div className="field">
        <label htmlFor="date-to">Au</label>
        <input
          id="date-to"
          type="date"
          value={draft.to}
          min={draft.from}
          max={bounds ? toInputDate(bounds.max) : undefined}
          onChange={(e) => apply({ ...draft, to: e.target.value })}
        />
      </div>
      {bounds && (
        <div className="row" style={{ gap: "0.3rem" }}>
          {PRESETS.map((p) => (
            <button key={p.label} onClick={() => applyPreset(p.days)} type="button">
              {p.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Bornes AAAA-MM-JJ / AAAA-MM-JJ prêtes pour l'API, en fin de journée pour `to`. */
export function toApiRange(range: DateRange): { from: string; to: string } {
  return { from: `${range.from}T00:00:00`, to: `${range.to}T23:59:59` };
}

/** Comme `toApiRange`, mais rend un objet vide tant que la plage n'est pas
 * encore résolue (avant le chargement des bornes) — évite d'envoyer une date
 * malformée le temps d'un aller-retour réseau. */
export function rangeParams(range: DateRange): Record<string, string> {
  return range.from ? toApiRange(range) : {};
}
