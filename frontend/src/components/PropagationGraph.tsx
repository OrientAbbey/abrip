import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { AsyncBlock } from "./StateBlock";
import { relationLabel } from "../lib/format";

interface PropagationNode {
  asn: number;
  as_name: string | null;
  country_iso2: string | null;
  paths: number[][];
  hidden_paths: number;
}
interface PropagationEdge {
  source: number;
  target: number;
  relation: "providers" | "customers" | "peerings" | "unspecified";
}
interface Propagation {
  prefix: string;
  asn: number | null;
  nodes: PropagationNode[];
  edges: PropagationEdge[];
}

const RELATION_COLOR: Record<string, string> = {
  providers: "#b45309", // amber-ish : vers le haut de la hiérarchie
  customers: "#0f766e", // teal : vers le bas
  peerings: "#4338ca", // indigo : pas de hiérarchie
  unspecified: "#94a3b8", // gris : relation inconnue
};

const LAYER_WIDTH = 190;
const NODE_HEIGHT = 46;
const NODE_WIDTH = 152;
const MARGIN = 30;

/** Graphe de propagation d'un préfixe (ADR 0004) : chaque AS distinct vu sur
 *  un chemin observé, disposé en colonnes par distance à l'origine (BFS sur
 *  les arêtes), les arêtes colorées par relation. Réduit, pas étendu :
 *  aucun AS non observé n'est ajouté pour compléter la topologie. */
export function PropagationGraph({
  prefix,
  origins,
}: {
  prefix: string;
  origins: Array<{ origin_asn: number; as_name: string | null }>;
}) {
  const [asn, setAsn] = useState<string>(origins.length === 1 ? String(origins[0].origin_asn) : "");
  const [targetsInput, setTargetsInput] = useState("");

  const targets = targetsInput
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
    .join(",");

  const data = useApi<Propagation>(`/prefixes/${encodeURIComponent(prefix)}/propagation`, {
    asn: asn || undefined,
    targets: targets || undefined,
  });

  return (
    <section className="card">
      <h2>Graphe de propagation</h2>
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
      <AsyncBlock state={data} rows={4}>
        {(body) =>
          body.nodes.length === 0 ? (
            <p className="muted">Aucun chemin observé sur cette fenêtre.</p>
          ) : (
            <GraphSvg body={body} />
          )
        }
      </AsyncBlock>
      <p className="card-note">
        Graphe réduit : seuls les AS effectivement vus sur un chemin observé apparaissent, sans
        complétion vers des voisins connus mais non observés pour ce préfixe.
      </p>
    </section>
  );
}

function GraphSvg({ body }: { body: Propagation }) {
  const layout = useMemo(() => computeLayout(body.nodes, body.edges), [body]);
  const width = (layout.maxDepth + 1) * LAYER_WIDTH + MARGIN * 2 - (LAYER_WIDTH - NODE_WIDTH);
  const height = layout.maxLayerSize * NODE_HEIGHT + MARGIN * 2;

  return (
    <div className="table-wrap">
      <svg
        viewBox={`0 0 ${width} ${Math.max(height, NODE_HEIGHT + MARGIN * 2)}`}
        width="100%"
        style={{ minWidth: `${Math.min(width, 900)}px`, height: "auto" }}
        role="img"
        aria-label="Graphe de propagation du préfixe"
      >
        {body.edges.map((e, i) => {
          const a = layout.positions[e.source];
          const b = layout.positions[e.target];
          if (!a || !b) return null;
          return (
            <line
              key={i}
              x1={a.x + NODE_WIDTH}
              y1={a.y + NODE_HEIGHT / 2}
              x2={b.x}
              y2={b.y + NODE_HEIGHT / 2}
              stroke={RELATION_COLOR[e.relation]}
              strokeWidth={1.5}
              opacity={0.75}
            />
          );
        })}
        {body.nodes.map((n) => {
          const pos = layout.positions[n.asn];
          if (!pos) return null;
          const label = n.as_name ? shorten(n.as_name) : "";
          const title = [
            `AS${n.asn}${n.as_name ? ` — ${n.as_name}` : ""}`,
            n.country_iso2 ? `Pays : ${n.country_iso2}` : null,
            ...n.paths.map((p) => p.map((a) => `AS${a}`).join(" → ")),
            n.hidden_paths > 0 ? `+ ${n.hidden_paths} autre(s) chemin(s)` : null,
          ]
            .filter(Boolean)
            .join("\n");
          return (
            <g key={n.asn} transform={`translate(${pos.x}, ${pos.y})`}>
              <title>{title}</title>
              <Link to={`/asns/${n.asn}`}>
                <rect
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={6}
                  fill="var(--paper-raised)"
                  stroke="var(--rule)"
                />
                <text x={8} y={19} fontFamily="var(--font-mono)" fontSize={12} fill="var(--ink-900)">
                  AS{n.asn}
                </text>
                {label && (
                  <text x={8} y={35} fontSize={11} fill="var(--ink-400)">
                    {label}
                  </text>
                )}
              </Link>
            </g>
          );
        })}
      </svg>
      <div className="legend" style={{ marginTop: "0.5rem" }}>
        {Object.entries(RELATION_COLOR).map(([key, color]) => (
          <span key={key}>
            <i style={{ background: color }} />
            {relationLabel(key)}
          </span>
        ))}
      </div>
    </div>
  );
}

function shorten(name: string): string {
  return name.length > 20 ? `${name.slice(0, 19)}…` : name;
}

function computeLayout(nodes: PropagationNode[], edges: PropagationEdge[]) {
  const incoming = new Set(edges.map((e) => e.target));
  const outgoing = new Map<number, number[]>();
  for (const e of edges) {
    if (!outgoing.has(e.source)) outgoing.set(e.source, []);
    outgoing.get(e.source)!.push(e.target);
  }

  // BFS depuis les racines (AS sans arête entrante = origines) ; un AS sans
  // arête du tout (chemin à un seul maillon) est sa propre racine.
  const depth = new Map<number, number>();
  const roots = nodes.map((n) => n.asn).filter((asn) => !incoming.has(asn));
  const queue: number[] = [];
  for (const r of roots) {
    depth.set(r, 0);
    queue.push(r);
  }
  while (queue.length > 0) {
    const current = queue.shift()!;
    const d = depth.get(current)!;
    for (const next of outgoing.get(current) ?? []) {
      if (!depth.has(next) || depth.get(next)! > d + 1) {
        depth.set(next, d + 1);
        queue.push(next);
      }
    }
  }
  // Filet de sécurité : un nœud jamais atteint (ne devrait pas arriver sur
  // un graphe connexe issu de chemins réels) va en première colonne plutôt
  // que de disparaître silencieusement.
  for (const n of nodes) if (!depth.has(n.asn)) depth.set(n.asn, 0);

  const byLayer = new Map<number, number[]>();
  for (const n of nodes) {
    const d = depth.get(n.asn)!;
    if (!byLayer.has(d)) byLayer.set(d, []);
    byLayer.get(d)!.push(n.asn);
  }

  const positions: Record<number, { x: number; y: number }> = {};
  let maxLayerSize = 1;
  for (const [d, asns] of byLayer) {
    asns.sort((a, b) => a - b);
    maxLayerSize = Math.max(maxLayerSize, asns.length);
    asns.forEach((asn, i) => {
      positions[asn] = { x: MARGIN + d * LAYER_WIDTH, y: MARGIN + i * NODE_HEIGHT };
    });
  }

  return { positions, maxDepth: Math.max(0, ...depth.values()), maxLayerSize };
}
