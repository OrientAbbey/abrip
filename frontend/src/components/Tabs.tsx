/** Barre d'onglets simple — un filtre en cours parmi un petit ensemble fixe
 *  (All/New/Left/Unstable, All/IPv4/IPv6, providers/customers/…). Pas de
 *  routage propre : le parent garde l'onglet actif dans son état ou dans
 *  l'URL, ce composant se contente de l'afficher et de le faire changer. */
export interface TabOption {
  value: string;
  label: string;
  /** Texte affiché au survol — utile pour les libellés qui ont besoin d'une
   *  définition (ex. "New"/"Left"/"Unstable", voir la page ASN). */
  title?: string;
}

export function Tabs({
  options,
  value,
  onChange,
}: {
  options: TabOption[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="tab"
          className="tab"
          aria-pressed={opt.value === value}
          title={opt.title}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
