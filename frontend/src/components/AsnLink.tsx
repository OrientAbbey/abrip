import { Link } from "react-router-dom";
import { useAsnName } from "../lib/useAsnNames";

/** Lien vers la fiche d'un AS, avec son nom accolé quand il est connu.
 *
 * Rendu unique pour tout le projet : afficher le nom à un seul endroit
 * garantit que le format ("AS174 · COGENT-174") reste cohérent partout, et
 * qu'une seule modification suffit à le faire évoluer.
 */
export function AsnLink({ asn, className = "mono" }: { asn: number; className?: string }) {
  const name = useAsnName(asn);
  return (
    <Link to={`/asns/${asn}`} className={className}>
      AS{asn}
      {name && <span className="muted"> · {name}</span>}
    </Link>
  );
}

/** Version non cliquable, pour les contextes où un lien n'a pas de sens
 * (légende, texte explicatif). */
export function AsnLabel({ asn, className = "mono" }: { asn: number; className?: string }) {
  const name = useAsnName(asn);
  return (
    <span className={className}>
      AS{asn}
      {name && <span className="muted"> · {name}</span>}
    </span>
  );
}
