/** Onglets accessibles (rôle tablist), avec infobulle et compteur optionnels
 *  par onglet. Utilisé au-dessus des graphes et des tableaux des explorateurs :
 *  l'onglet actif filtre à la fois ce qu'ils montrent, sans état caché.
 *
 *  Navigation clavier conforme au motif ARIA « tabs » : un seul onglet est
 *  dans l'ordre de tabulation (tabindex mobile), les flèches changent d'onglet,
 *  Début/Fin vont au premier/dernier. Le panneau associé est rendu par le
 *  parent, qui garde la valeur active dans son état ou dans l'URL.
 */

import { useRef, type KeyboardEvent } from "react";

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
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);

  const focusAt = (index: number) => {
    if (options.length === 0) return;
    const next = (index + options.length) % options.length;
    const option = options[next];
    buttons.current[next]?.focus();
    onChange(option.value);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === "ArrowRight") {
      event.preventDefault();
      focusAt(index + 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      focusAt(index - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusAt(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusAt(options.length - 1);
    }
  };

  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {options.map((option, index) => (
        <button
          key={option.value}
          ref={(element) => {
            buttons.current[index] = element;
          }}
          type="button"
          role="tab"
          aria-selected={option.value === value}
          tabIndex={option.value === value ? 0 : -1}
          className={option.value === value ? "tab active" : "tab"}
          title={option.title}
          onClick={() => onChange(option.value)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {option.label}
          {option.count !== undefined && <span className="tab-count">{option.count}</span>}
        </button>
      ))}
    </div>
  );
}
