/** Onglets accessibles (rôle tablist), avec infobulle et compteur optionnels
 *  par onglet. Utilisé au-dessus des graphes et des tableaux des explorateurs :
 *  l'onglet actif filtre à la fois ce qu'ils montrent, sans état caché.
 */

export interface TabOption<T extends string> {
  value: T;
  label: string;
  /** Texte de l'infobulle (attribut `title`). */
  title?: string;
  count?: number;
}

export function Tabs<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: Array<TabOption<T>>;
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={option.value === value}
          className={option.value === value ? "tab active" : "tab"}
          title={option.title}
          onClick={() => onChange(option.value)}
        >
          {option.label}
          {option.count !== undefined && <span className="tab-count">{option.count}</span>}
        </button>
      ))}
    </div>
  );
}
