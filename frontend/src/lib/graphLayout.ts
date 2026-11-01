import type { PropagationEdge, PropagationNode } from "../components/PropagationSvg";

/** Dimensions d'un nœud et espacements, en unités du viewBox du SVG. */
export const NODE_WIDTH = 152;
export const NODE_HEIGHT = 46;
export const LAYER_WIDTH = 190;
export const ROW_HEIGHT = 64; // > NODE_HEIGHT : laisse de l'air aux arêtes entre deux nœuds
export const MARGIN = 30;

/** Disposition « étroite » (téléphone) : nœuds plus petits, couches empilées. */
export const NARROW_NODE_WIDTH = 112;
export const NARROW_GAP = 10;
export const NARROW_LAYER_GAP = 44; // entre deux couches : de la place pour les liens
const NARROW_MARGIN = 12;

export interface Layout {
  positions: Record<number, { x: number; y: number }>;
  nodeWidth: number;
  width: number;
  height: number;
  maxDepth: number;
  vertical: boolean;
  /** Profondeur (colonne ou bande) de chaque AS. */
  depth: Record<number, number>;
  /** Croisements entre couches voisines après optimisation : mesure de lisibilité. */
  crossings: number;
}

export interface LayoutOptions {
  /** Largeur disponible (px) : sous 640, la disposition passe en couches empilées. */
  availableWidth?: number;
  /** Forcer l'orientation (tests). */
  vertical?: boolean;
  /** Nombre de balayages d'optimisation (0 : ordre numérique, sans optimisation). */
  sweeps?: number;
}

/** Une vraie origine : ouvre un de ses propres chemins, ou porte un statut RPKI
 *  (le serveur ne le donne qu'aux origines), même si elle apparaît aussi comme
 *  pair collecteur sur le chemin d'une autre origine (cas d'un détournement). */
export const isOrigin = (n: PropagationNode, hasIncoming: boolean): boolean =>
  !hasIncoming || n.rpki != null || (n.paths ?? []).some((p) => p[0] === n.asn);

/** Croisements entre deux couches consécutives, pour un ordre donné. Les arêtes
 *  sont prises sans sens : deux liens se croisent si leurs extrémités sont dans
 *  des ordres opposés des deux côtés. */
function crossingsBetween(
  edges: Array<[number, number]>,
  upper: Map<number, number>,
  lower: Map<number, number>,
): number {
  const pairs: Array<[number, number]> = [];
  for (const [a, b] of edges) {
    if (upper.has(a) && lower.has(b)) pairs.push([upper.get(a)!, lower.get(b)!]);
    else if (upper.has(b) && lower.has(a)) pairs.push([upper.get(b)!, lower.get(a)!]);
  }
  let count = 0;
  for (let i = 0; i < pairs.length; i++) {
    for (let j = i + 1; j < pairs.length; j++) {
      const da = pairs[i][0] - pairs[j][0];
      const db = pairs[i][1] - pairs[j][1];
      if (da * db < 0) count++;
    }
  }
  return count;
}

function totalCrossings(
  order: Map<number, number[]>,
  maxDepth: number,
  edges: Array<[number, number]>,
): number {
  const position = (d: number) => new Map((order.get(d) ?? []).map((asn, i) => [asn, i]));
  let sum = 0;
  for (let d = 0; d < maxDepth; d++) sum += crossingsBetween(edges, position(d), position(d + 1));
  return sum;
}

const median = (values: number[]): number => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

export function computeLayout(
  nodes: PropagationNode[],
  edges: PropagationEdge[],
  options: LayoutOptions = {},
): Layout {
  const sweeps = options.sweeps ?? 24;
  const vertical = options.vertical ?? (options.availableWidth ?? Infinity) < 640;

  const incoming = new Set(edges.map((e) => e.target));
  const outgoing = new Map<number, number[]>();
  const neighborsOf = new Map<number, number[]>();
  const link = (map: Map<number, number[]>, key: number, value: number) => {
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(value);
  };
  for (const e of edges) {
    link(outgoing, e.source, e.target);
    link(neighborsOf, e.source, e.target);
    link(neighborsOf, e.target, e.source);
  }

  // Profondeur : BFS depuis les origines ; un AS jamais atteint (ne devrait pas
  // arriver sur un graphe issu de chemins réels) va en première colonne plutôt
  // que de disparaître silencieusement.
  const depth = new Map<number, number>();
  const queue: number[] = [];
  for (const n of nodes) {
    if (isOrigin(n, incoming.has(n.asn))) {
      depth.set(n.asn, 0);
      queue.push(n.asn);
    }
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
  for (const n of nodes) if (!depth.has(n.asn)) depth.set(n.asn, 0);

  const maxDepth = Math.max(0, ...depth.values());
  const order = new Map<number, number[]>();
  for (let d = 0; d <= maxDepth; d++) order.set(d, []);
  for (const n of nodes) order.get(depth.get(n.asn)!)!.push(n.asn);
  for (const asns of order.values()) asns.sort((a, b) => a - b);

  // Réduction des croisements : balayages par la médiane des voisins de la
  // couche de référence (la médiane résiste mieux que la moyenne aux voisins
  // éloignés), en alternant le sens, puis échanges de voisins immédiats. On garde
  // le meilleur ordre rencontré, mesuré en croisements réels.
  const pairs: Array<[number, number]> = edges.map((e) => [e.source, e.target]);
  const snapshot = () => new Map([...order].map(([d, asns]) => [d, [...asns]]));
  let best = snapshot();
  let bestScore = totalCrossings(order, maxDepth, pairs);
  for (let pass = 0; pass < sweeps && bestScore > 0; pass++) {
    const forward = pass % 2 === 0;
    for (let i = 0; i < maxDepth; i++) {
      const d = forward ? i + 1 : maxDepth - 1 - i;
      const refDepth = forward ? d - 1 : d + 1;
      const layer = order.get(d)!;
      const refPos = new Map((order.get(refDepth) ?? []).map((asn, k) => [asn, k]));
      const own = new Map(layer.map((asn, k) => [asn, k]));
      const scored = layer.map((asn) => {
        const refs = (neighborsOf.get(asn) ?? []).filter((n) => refPos.has(n));
        return { asn, key: refs.length ? median(refs.map((n) => refPos.get(n)!)) : own.get(asn)! };
      });
      scored.sort((a, b) => a.key - b.key || own.get(a.asn)! - own.get(b.asn)!);
      order.set(d, scored.map((s) => s.asn));
    }
    // Échanges locaux : permuter deux voisins immédiats si cela réduit les
    // croisements avec la couche du dessus et celle du dessous.
    for (let d = 0; d <= maxDepth; d++) {
      const layer = order.get(d)!;
      const local = () => {
        const pos = (k: number) => new Map((order.get(k) ?? []).map((asn, i) => [asn, i]));
        return (
          (d > 0 ? crossingsBetween(pairs, pos(d - 1), pos(d)) : 0) +
          (d < maxDepth ? crossingsBetween(pairs, pos(d), pos(d + 1)) : 0)
        );
      };
      let improved = true;
      for (let round = 0; improved && round < 6; round++) {
        improved = false;
        for (let k = 0; k + 1 < layer.length; k++) {
          const before = local();
          [layer[k], layer[k + 1]] = [layer[k + 1], layer[k]];
          if (local() < before) improved = true;
          else [layer[k], layer[k + 1]] = [layer[k + 1], layer[k]];
        }
      }
    }
    const score = totalCrossings(order, maxDepth, pairs);
    if (score < bestScore) {
      bestScore = score;
      best = snapshot();
    }
  }
  for (const [d, asns] of best) order.set(d, asns);

  // Géométrie.
  const positions: Record<number, { x: number; y: number }> = {};
  if (!vertical) {
    let maxLayerSize = 1;
    for (const [d, asns] of order) {
      maxLayerSize = Math.max(maxLayerSize, asns.length);
      asns.forEach((asn, i) => {
        positions[asn] = { x: MARGIN + d * LAYER_WIDTH, y: MARGIN + i * ROW_HEIGHT };
      });
    }
    return {
      positions,
      nodeWidth: NODE_WIDTH,
      width: (maxDepth + 1) * LAYER_WIDTH + MARGIN * 2 - (LAYER_WIDTH - NODE_WIDTH),
      height: Math.max(maxLayerSize * ROW_HEIGHT + MARGIN * 2, NODE_HEIGHT + MARGIN * 2),
      maxDepth,
      vertical,
      depth: Object.fromEntries(depth),
      crossings: bestScore,
    };
  }

  // Couches empilées, chacune sur autant de rangées que nécessaire : la largeur
  // du SVG est celle de l'écran, pas celle du graphe.
  const available = options.availableWidth ?? 390;
  const perRow = Math.max(
    1,
    Math.floor((available - NARROW_MARGIN * 2 + NARROW_GAP) / (NARROW_NODE_WIDTH + NARROW_GAP)),
  );
  let y = NARROW_MARGIN;
  let widest = 1;
  for (let d = 0; d <= maxDepth; d++) {
    const asns = order.get(d) ?? [];
    asns.forEach((asn, i) => {
      positions[asn] = {
        x: NARROW_MARGIN + (i % perRow) * (NARROW_NODE_WIDTH + NARROW_GAP),
        y: y + Math.floor(i / perRow) * (NODE_HEIGHT + NARROW_GAP),
      };
    });
    widest = Math.max(widest, Math.min(asns.length, perRow));
    y += Math.max(1, Math.ceil(asns.length / perRow)) * (NODE_HEIGHT + NARROW_GAP) - NARROW_GAP + NARROW_LAYER_GAP;
  }
  return {
    positions,
    nodeWidth: NARROW_NODE_WIDTH,
    width: NARROW_MARGIN * 2 + widest * NARROW_NODE_WIDTH + (widest - 1) * NARROW_GAP,
    height: y - NARROW_LAYER_GAP + NARROW_MARGIN,
    maxDepth,
    vertical,
    depth: Object.fromEntries(depth),
    crossings: bestScore,
  };
}

/** Tracé d'un lien. Les liens « retour » (vers une couche déjà passée ou la même :
 *  un AS à la fois origine et pair d'une autre origine) contournent les nœuds au
 *  lieu de les traverser. */
export function edgePath(layout: Layout, source: number, target: number): string | null {
  const a = layout.positions[source];
  const b = layout.positions[target];
  if (!a || !b) return null;
  const w = layout.nodeWidth;
  const ds = layout.depth[source] ?? 0;
  const dt = layout.depth[target] ?? 0;
  if (!layout.vertical) {
    const y1 = a.y + NODE_HEIGHT / 2;
    const y2 = b.y + NODE_HEIGHT / 2;
    if (dt > ds) {
      const x1 = a.x + w;
      const mx = (x1 + b.x) / 2;
      return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${b.x} ${y2}`;
    }
    const x1 = a.x + w;
    if (dt === ds) {
      // Même couche (deux AS en peering, par exemple) : un arc compact sur le côté
      // droit de la colonne, d'autant plus ouvert que les nœuds sont éloignés.
      const out = Math.min(64, 20 + Math.abs(y2 - y1) * 0.3);
      return `M ${x1} ${y1} C ${x1 + out} ${y1}, ${x1 + out} ${y2}, ${x1} ${y2}`;
    }
    // Retour vers une couche déjà passée : sortir par la droite, revenir par la
    // gauche, en passant sous les deux nœuds.
    const bow = Math.max(y1, y2) + NODE_HEIGHT / 2 + 14;
    return `M ${x1} ${y1} C ${x1 + 46} ${bow}, ${b.x - 46} ${bow}, ${b.x} ${y2}`;
  }
  const x1 = a.x + w / 2;
  const x2 = b.x + w / 2;
  if (dt > ds) {
    const y1 = a.y + NODE_HEIGHT;
    const my = (y1 + b.y) / 2;
    return `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${b.y}`;
  }
  // Retour en mode étroit : arc latéral qui contourne les nœuds par la droite.
  const edge = layout.width - 4;
  const y1 = a.y + NODE_HEIGHT / 2;
  const y2 = b.y + NODE_HEIGHT / 2;
  return `M ${a.x + w} ${y1} C ${edge} ${y1}, ${edge} ${y2}, ${b.x + w} ${y2}`;
}
