import { useState } from "react";
import { useApi } from "../lib/useApi";
import { AsyncBlock } from "./StateBlock";
import { Tabs } from "./Tabs";
import { GraphSvg } from "./PropagationSvg";
import type { PropagationEdge, PropagationNode } from "./PropagationSvg";
import { PropagationReplay } from "./PropagationReplay";

interface Propagation {
  prefix: string;
  asn: number | null;
  nodes: PropagationNode[];
  edges: PropagationEdge[];
}

const MODES = [
  { value: "snapshot", label: "Instantané", title: "Tous les chemins vus sur la fenêtre, agrégés" },
  { value: "replay", label: "Rejouer", title: "Dérouler la propagation dans le temps" },
];

/** Graphe de propagation d'un préfixe (ADR 0004) : chaque AS distinct vu sur
 *  un chemin observé, disposé en colonnes par distance à l'origine (BFS sur
 *  les arêtes), les arêtes colorées par relation. Réduit, pas étendu :
 *  aucun AS non observé n'est ajouté pour compléter la topologie.
 *
 *  Deux modes qui partagent leurs filtres (origine, cibles) : l'instantané
 *  agrège toute la fenêtre ; le rejeu la déroule tranche par tranche. */
export function PropagationGraph({
  prefix,
  origins,
}: {
  prefix: string;
  origins: Array<{ origin_asn: number; as_name: string | null }>;
}) {
  const [mode, setMode] = useState("snapshot");
  const [asn, setAsn] = useState<string>(origins.length === 1 ? String(origins[0].origin_asn) : "");
  const [targetsInput, setTargetsInput] = useState("");

  const targets = targetsInput
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
    .join(",");

  const data = useApi<Propagation>(
    mode === "snapshot" ? `/prefixes/${encodeURIComponent(prefix)}/propagation` : null,
    { asn: asn || undefined, targets: targets || undefined },
  );

  return (
    <section className="card">
      <h2>Graphe de propagation</h2>
      <Tabs options={MODES} value={mode} onChange={setMode} />
      <div className="filters">
        {origins.length > 1 && (
          <div className="field">
            <label htmlFor="prop-asn">Origine</label>
            <select id="prop-asn" value={asn} onChange={(e) => setAsn(e.target.value)}>
              <option value="">Toutes</option>
              {origins.map((o) => (
                <option key={o.origin_asn} value={o.origin_asn}>
                  AS{o.origin_asn}
                  {o.as_name ? ` (${o.as_name})` : ""}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="prop-targets">Cibles (ASN séparés par des virgules)</label>
          <input
            id="prop-targets"
            type="text"
            placeholder="ex. 174,3356,6939"
            value={targetsInput}
            onChange={(e) => setTargetsInput(e.target.value)}
          />
        </div>
      </div>

      {mode === "snapshot" ? (
        <AsyncBlock state={data} rows={4}>
          {(body) =>
            body.nodes.length === 0 ? (
              <p className="muted">Aucun chemin observé sur cette fenêtre.</p>
            ) : (
              <GraphSvg nodes={body.nodes} edges={body.edges} />
            )
          }
        </AsyncBlock>
      ) : (
        <PropagationReplay prefix={prefix} asn={asn} targets={targets} />
      )}

      <p className="card-note">
        Graphe réduit : seuls les AS effectivement vus sur un chemin observé apparaissent, sans
        complétion vers des voisins connus mais non observés pour ce préfixe.
      </p>
    </section>
  );
}
