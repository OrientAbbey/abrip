import type { ReactNode } from "react";
import { GLOSSARY, type GlossaryKey } from "../lib/glossary";

/** Terme technique avec sa définition en infobulle (souligné en pointillé).
 *  Sans `children`, affiche le libellé complet du glossaire. */
export function Term({ k, children }: { k: GlossaryKey; children?: ReactNode }) {
  const entry = GLOSSARY[k];
  return (
    <abbr className="term" title={entry.hint}>
      {children ?? entry.label}
    </abbr>
  );
}

/** Glossaire en clair : les mêmes définitions que les infobulles, lisibles
 *  sans survol (écrans tactiles, impression). */
export function Glossary({ keys }: { keys: GlossaryKey[] }) {
  return (
    <dl className="glossary">
      {keys.map((k) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{GLOSSARY[k].label}</dt>
          <dd>{GLOSSARY[k].hint}</dd>
        </div>
      ))}
    </dl>
  );
}
