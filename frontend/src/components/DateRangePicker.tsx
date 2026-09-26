/** Sélecteur de plage de dates, pour les graphes et tableaux à fenêtre
 *  ajustable (point 6). Bornes non contrôlées : le champ de date natif du
 *  navigateur refuse de toute façon les valeurs hors de `min`/`max`, pas
 *  besoin de le revalider ici. `from`/`to` vides = fenêtre par défaut de
 *  l'API (toute la période disponible). */
export function DateRangePicker({
  from,
  to,
  min,
  max,
  onChange,
}: {
  from: string;
  to: string;
  min?: string;
  max?: string;
  onChange: (from: string, to: string) => void;
}) {
  return (
    <div className="filters">
      <div className="field">
        <label htmlFor="dr-from">Du</label>
        <input
          id="dr-from"
          type="date"
          value={from}
          min={min}
          max={to || max}
          onChange={(e) => onChange(e.target.value, to)}
        />
      </div>
      <div className="field">
        <label htmlFor="dr-to">Au</label>
        <input
          id="dr-to"
          type="date"
          value={to}
          min={from || min}
          max={max}
          onChange={(e) => onChange(from, e.target.value)}
        />
      </div>
      {(from || to) && (
        <div className="field">
          <label>&nbsp;</label>
          <button type="button" onClick={() => onChange("", "")}>
            Toute la période
          </button>
        </div>
      )}
    </div>
  );
}
