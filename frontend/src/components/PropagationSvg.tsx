import { useMemo } from "react";
import { Link } from "react-router-dom";
import { relationLabel } from "../lib/format";

export interface PropagationNode {
  asn: number;
  as_name: string | null;
  country_iso2: string | null;
  /** Absents du rejeu : une info-bulle par nœud n'aurait pas de sens quand le
   *  chemin dépend de l'instant affiché. */
  paths?: number[][];
  hidden_paths?: number;
}
export interface PropagationEdge {
  source: number;
  target: number;
  relation: "providers" | "customers" | "peerings" | "unspecified";
}

/** État d'un élément à l'instant affiché (rejeu) : "active" = présent aux
 *  deux instants, "appearing" = vient d'apparaître, "disappearing" = vient
 *  de disparaître, "inactive" = absent (grisé, gardé pour que la disposition
 *  ne bouge pas). Sans rejeu, tout est "active". */
export type Status = "active" | "appearing" | "disappearing" | "inactive";

export const RELATION_COLOR: Record<string, string> = {
  providers: "#b45309", // amber-ish : vers le haut de la hiérarchie
  customers: "#0f766e", // teal : vers le bas
  peerings: "#4338ca", // indigo : pas de hiérarchie
  unspecified: "#94a3b8", // gris : relation inconnue
};
const APPEARING = "#15803d";
const DISAPPEARING = "#b91c1c";

const LAYER_WIDTH = 190;
const NODE_HEIGHT = 46;
const ROW_HEIGHT = 64; // > NODE_HEIGHT : laisse de l'air aux arêtes entre deux nœuds
const NODE_WIDTH = 152;
const MARGIN = 30;

export function GraphSvg({
  nodes,
  edges,
  nodeStatus,
  edgeStatus,
}: {
  nodes: PropagationNode[];
  edges: PropagationEdge[];
  nodeStatus?: (index: number) => Status;
  edgeStatus?: (index: number) => Status;
}) {
  const layout = useMemo(() => computeLayout(nodes, edges), [nodes, edges]);
  const width = (layout.maxDepth + 1) * LAYER_WIDTH + MARGIN * 2 - (LAYER_WIDTH - NODE_WIDTH);
  const height = layout.maxLayerSize * ROW_HEIGHT + MARGIN * 2;

  return (
    <div className="table-wrap">
      <svg
        viewBox={`0 0 ${width} ${Math.max(height, NODE_HEIGHT + MARGIN * 2)}`}
        width="100%"
        style={{ minWidth: `${Math.min(width, 900)}px`, height: "auto" }}
        role="img"
        aria-label="Graphe de propagation du préfixe"
      >
        {edges.map((e, i) => {
          const a = layout.positions[e.source];
          const b = layout.positions[e.target];
          if (!a || !b) return null;
          const status = edgeStatus?.(i) ?? "active";
          const x1 = a.x + NODE_WIDTH;
          const y1 = a.y + NODE_HEIGHT / 2;
          const x2 = b.x;
          const y2 = b.y + NODE_HEIGHT / 2;
          const mx = (x1 + x2) / 2;
          return (
            <path
              key={i}
              d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
              fill="none"
              stroke={
                status === "appearing"
                  ? APPEARING
                  : status === "disappearing"
                    ? DISAPPEARING
                    : RELATION_COLOR[e.relation]
              }
              strokeWidth={status === "appearing" || status === "disappearing" ? 2.4 : 1.3}
              strokeDasharray={status === "disappearing" ? "5 4" : undefined}
              opacity={status === "inactive" ? 0.08 : status === "active" ? 0.55 : 0.95}
            />
          );
        })}
        {nodes.map((n, i) => {
          const pos = layout.positions[n.asn];
          if (!pos) return null;
          const status = nodeStatus?.(i) ?? "active";
          const label = n.as_name ? shorten(n.as_name) : "";
          const title = [
            `AS${n.asn}${n.as_name ? ` — ${n.as_name}` : ""}`,
            n.country_iso2 ? `Pays : ${n.country_iso2}` : null,
            ...(n.paths ?? []).map((p) => p.map((a) => `AS${a}`).join(" → ")),
            n.hidden_paths ? `+ ${n.hidden_paths} autre(s) chemin(s)` : null,
          ]
            .filter(Boolean)
            .join("\n");
          const stroke =
            status === "appearing" ? APPEARING : status === "disappearing" ? DISAPPEARING : "var(--rule)";
          return (
            <g
              key={n.asn}
              transform={`translate(${pos.x}, ${pos.y})`}
              opacity={status === "inactive" ? 0.25 : 1}
            >
              <title>{title}</title>
              <Link to={`/asns/${n.asn}`}>
                <rect
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={6}
                  fill="var(--paper-raised)"
                  stroke={stroke}
                  strokeWidth={status === "appearing" || status === "disappearing" ? 2.4 : 1}
                  strokeDasharray={status === "disappearing" ? "5 4" : undefined}
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
        {nodeStatus && (
          <>
            <span>
              <i style={{ background: APPEARING }} />
              Vient d'apparaître
            </span>
            <span>
              <i style={{ background: DISAPPEARING }} />
              Vient de disparaître
            </span>
          </>
        )}
      </div>
    </div>
  );
}

export function shorten(name: string): string {
  return name.length > 20 ? `${name.slice(0, 19)}…` : name;
}

export function computeLayout(nodes: PropagationNode[], edges: PropagationEdge[]) {
  const incoming = new Set(edges.map((e) => e.target));
  const outgoing = new Map<number, number[]>();
  const neighborsOf = new Map<number, number[]>();
  for (const e of edges) {
    if (!outgoing.has(e.source)) outgoing.set(e.source, []);
    outgoing.get(e.source)!.push(e.target);
    if (!neighborsOf.has(e.source)) neighborsOf.set(e.source, []);
    if (!neighborsOf.has(e.target)) neighborsOf.set(e.target, []);
    neighborsOf.get(e.source)!.push(e.target);
    neighborsOf.get(e.target)!.push(e.source);
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

  const maxDepth = Math.max(0, ...depth.values());
  const order = new Map<number, number[]>();
  for (const n of nodes) {
    const d = depth.get(n.asn)!;
    if (!order.has(d)) order.set(d, []);
    order.get(d)!.push(n.asn);
  }
  for (const asns of order.values()) asns.sort((a, b) => a - b);

  // Quelques passes barycentriques (Sugiyama simplifié) : chaque couche est
  // réordonnée selon la position moyenne de ses voisins déjà placés dans la
  // couche adjacente, en alternant le sens de balayage. Sans ça, l'ordre
  // arbitraire (numérique) multiplie les croisements d'arêtes — c'est ce qui
  // rendait le graphe touffu.
  for (let pass = 0; pass < 4; pass++) {
    const forward = pass % 2 === 0;
    const layers = Array.from({ length: maxDepth }, (_, i) => (forward ? i + 1 : maxDepth - i));
    for (const d of layers) {
      const refDepth = forward ? d - 1 : d + 1;
      const refOrder = order.get(refDepth);
      const layer = order.get(d);
      if (!refOrder || !layer) continue;
      const refPos = new Map(refOrder.map((asn, i) => [asn, i]));
      const currentPos = new Map(layer.map((asn, i) => [asn, i]));
      const scored = layer.map((asn) => {
        const refNeighbors = (neighborsOf.get(asn) ?? []).filter((n) => refPos.has(n));
        const avg = refNeighbors.length
          ? refNeighbors.reduce((sum, n) => sum + refPos.get(n)!, 0) / refNeighbors.length
          : currentPos.get(asn)!; // pas de voisin de référence : garder sa place
        return { asn, avg };
      });
      scored.sort((a, b) => a.avg - b.avg);
      order.set(
        d,
        scored.map((s) => s.asn)
      );
    }
  }

  const positions: Record<number, { x: number; y: number }> = {};
  let maxLayerSize = 1;
  for (const [d, asns] of order) {
    maxLayerSize = Math.max(maxLayerSize, asns.length);
    asns.forEach((asn, i) => {
      positions[asn] = { x: MARGIN + d * LAYER_WIDTH, y: MARGIN + i * ROW_HEIGHT };
    });
  }

  return { positions, maxDepth, maxLayerSize };
}
