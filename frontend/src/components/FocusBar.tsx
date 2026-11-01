import { Link } from "react-router-dom";
import { GROUP_ASN } from "../lib/graphFold";
import { nodeTitle } from "./PropagationSvg";
import type { PropagationNode } from "./PropagationSvg";

/** Rappel de l'AS épinglé, avec le chemin vers sa fiche (le clic sur un nœud
 *  épingle au lieu de naviguer : la navigation passe par ici). */
export function FocusBar({
  focus,
  nodes,
  onFocus,
}: {
  focus: number | null;
  nodes: PropagationNode[];
  onFocus: (asn: number | null) => void;
}) {
  const node = focus === null ? undefined : nodes.find((n) => n.asn === focus);
  if (!node) return null;
  const group = node.asn === GROUP_ASN;
  return (
    <div role="status" style={{ margin: "0.3rem 0" }}>
      <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap", justifyContent: "flex-start" }}>
        <strong className="mono">{group ? node.as_name : `AS${node.asn}`}</strong>
        {!group && node.as_name && <span className="muted">{node.as_name}</span>}
        {!group && <Link to={`/asns/${node.asn}`}>Ouvrir la fiche de l'AS</Link>}
        <button type="button" onClick={() => onFocus(null)}>
          Libérer
        </button>
      </div>
      {/* Même contenu que l'infobulle du survol : au toucher, il n'y a pas de survol. */}
      <details>
        <summary className="muted">Détails</summary>
        <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: "0.3rem 0", fontSize: "0.78rem" }}>
          {nodeTitle(node)}
        </pre>
      </details>
    </div>
  );
}
