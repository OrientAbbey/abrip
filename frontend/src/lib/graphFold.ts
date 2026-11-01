import type { PropagationEdge, PropagationNode } from "../components/PropagationSvg";
import { isOrigin as isOriginNode } from "./graphLayout";

/** Pays d'Afrique (ISO 3166-1 alpha-2), Sahara occidental compris. */
export const AFRICA_ISO2 = new Set(
  (
    "DZ AO BJ BW BF BI CM CV CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW " +
    "ML MR MU MA MZ NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG TN UG ZM ZW EH"
  ).split(" "),
);

/** Identifiant du nœud qui représente les AS repliés (jamais un vrai ASN). */
export const GROUP_ASN = -1;

export interface Folded {
  nodes: PropagationNode[];
  edges: PropagationEdge[];
  /** Les chemins fournis, avec les AS repliés remplacés par le groupe. */
  paths: number[][];
  /** Nombre d'AS regroupés ; 0 si rien n'a été replié. */
  folded: number;
  /** Indice d'arête d'origine -> indice dans `edges` (-1 : lien interne au groupe, supprimé). */
  edgeMap: number[];
  /** ASN d'origine -> ASN affiché (celui du groupe pour un AS replié). */
  map: (asn: number) => number;
}

/** Regroupe en un seul nœud « + n AS hors Afrique » les AS dont le pays est
 *  connu et situé hors d'Afrique, sauf les origines (un détournement par un AS
 *  étranger doit rester visible). Un AS sans pays connu n'est jamais replié :
 *  on ne cache pas ce qu'on ne sait pas classer. Les arêtes vers le groupe sont
 *  fusionnées, leurs observations additionnées. */
export function foldForeign(
  nodes: PropagationNode[],
  edges: PropagationEdge[],
  paths: number[][] = [],
): Folded {
  const incoming = new Set(edges.map((e) => e.target));
  const foldable = nodes.filter(
    (n) =>
      n.country_iso2 && !AFRICA_ISO2.has(n.country_iso2) && !isOriginNode(n, incoming.has(n.asn)),
  );
  if (foldable.length < 2) {
    return { nodes, edges, paths, folded: 0, edgeMap: edges.map((_, i) => i), map: (a) => a };
  }

  const members = new Set(foldable.map((n) => n.asn));
  const group: PropagationNode = {
    asn: GROUP_ASN,
    as_name: `+${foldable.length} AS hors Afrique`,
    org_name: null,
    country_iso2: null,
    members: foldable.map((n) => ({ asn: n.asn, as_name: n.as_name, country_iso2: n.country_iso2 })),
    observations: foldable.reduce((sum, n) => sum + (n.observations ?? 0), 0) || undefined,
  };
  const map = (asn: number) => (members.has(asn) ? GROUP_ASN : asn);

  const merged = new Map<string, PropagationEdge>();
  const slot = new Map<string, number>();
  const edgeMap: number[] = [];
  for (const e of edges) {
    const source = map(e.source);
    const target = map(e.target);
    if (source === target) {
      edgeMap.push(-1);
      continue;
    }
    const key = `${source}>${target}`;
    const known = merged.get(key);
    if (!known) {
      slot.set(key, merged.size);
      merged.set(key, { ...e, source, target });
      edgeMap.push(merged.size - 1);
    } else {
      edgeMap.push(slot.get(key)!);
      if (known.relation !== e.relation) known.relation = "unspecified";
      if (e.observations !== undefined) known.observations = (known.observations ?? 0) + e.observations;
      known.violation_observations = (known.violation_observations ?? 0) + (e.violation_observations ?? 0);
    }
  }
  const foldedPaths = paths.map((path) =>
    path.map(map).filter((asn, i, all) => i === 0 || asn !== all[i - 1]),
  );
  return {
    nodes: [...nodes.filter((n) => !members.has(n.asn)), group],
    edges: [...merged.values()],
    paths: foldedPaths,
    folded: foldable.length,
    edgeMap,
    map,
  };
}

/** Ce qu'il faut mettre en évidence quand on s'intéresse à un AS.
 *  Avec la liste des chemins (mode instantané) : exactement les liens et les AS
 *  des chemins qui traversent l'AS. Sans elle (rejeu) : ses liens directs et
 *  ses voisins. Ne pas se contenter de « tout ce qui est atteignable » : dans un
 *  graphe dense, tout l'est, et rien ne serait estompé. */
export function highlight(asn: number, edges: PropagationEdge[], paths?: number[][]) {
  const nodes = new Set<number>([asn]);
  const pairs = new Set<string>();
  if (paths) {
    for (const path of paths) {
      if (!path.includes(asn)) continue;
      path.forEach((a, i) => {
        nodes.add(a);
        if (i > 0) pairs.add(`${path[i - 1]}>${a}`);
      });
    }
  } else {
    for (const e of edges) {
      if (e.source === asn || e.target === asn) {
        nodes.add(e.source);
        nodes.add(e.target);
        pairs.add(`${e.source}>${e.target}`);
      }
    }
  }
  const edgeIdx = new Set<number>();
  edges.forEach((e, i) => {
    if (pairs.has(`${e.source}>${e.target}`)) edgeIdx.add(i);
  });
  return { nodes, edges: edgeIdx };
}

interface ReplayShape {
  nodes: PropagationNode[];
  edges: PropagationEdge[];
  paths: number[][] | null;
  frames: Array<{ nodes: number[]; edges: number[]; path_ids?: number[] }>;
}

/** Même repli sur un rejeu : nœuds, liens, chemins et, tranche par tranche, les
 *  éléments actifs. Un groupe est actif dès qu'un de ses membres l'est. */
export function foldReplay<T extends ReplayShape>(body: T): T & { folded: number } {
  const folded = foldForeign(body.nodes, body.edges, body.paths ?? []);
  if (folded.folded === 0) return { ...body, folded: 0 };
  const unique = (values: number[]) => [...new Set(values)].sort((a, b) => a - b);
  return {
    ...body,
    nodes: folded.nodes,
    edges: folded.edges,
    paths: body.paths ? folded.paths : null,
    frames: body.frames.map((f) => ({
      ...f,
      nodes: unique(f.nodes.map(folded.map)),
      edges: unique(f.edges.map((i) => folded.edgeMap[i]).filter((i) => i >= 0)),
    })),
    folded: folded.folded,
  };
}
