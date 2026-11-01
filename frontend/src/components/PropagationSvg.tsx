import { useEffect, useMemo, useRef, useState } from "react";
import { GROUP_ASN, highlight } from "../lib/graphFold";
import { NODE_HEIGHT, computeLayout, edgePath } from "../lib/graphLayout";
import { relationLabel } from "../lib/format";

export interface PropagationNode {
  asn: number;
  /** Nom court (étiquette du nœud). */
  as_name: string | null;
  /** Nom complet de l'organisation (infobulle). */
  org_name?: string | null;
  country_iso2: string | null;
  /** Absents du rejeu : une info-bulle par nœud n'aurait pas de sens quand le
   *  chemin dépend de l'instant affiché. */
  paths?: number[][];
  hidden_paths?: number;
  /** Messages BGP cumulés des chemins qui traversent ce nœud (mode instantané). */
  observations?: number;
  /** Nœud de regroupement (« + n AS hors Afrique ») : les AS qu'il remplace. */
  members?: Array<{ asn: number; as_name: string | null; country_iso2: string | null }>;
  /** Statut RPKI de l'AS comme origine du préfixe (absent pour un AS de transit). */
  rpki?: "valid" | "invalid" | "not-found" | "unknown" | null;
}
export interface PropagationEdge {
  source: number;
  target: number;
  relation: "providers" | "customers" | "peerings" | "unspecified";
  /** Messages BGP cumulés sur ce lien (mode instantané) : fixe l'épaisseur. */
  observations?: number;
  /** Observations des chemins qui violent le modèle valley-free sur ce lien (fuite probable). */
  violation_observations?: number;
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
const LEAK = "#be185d"; // magenta : distinct du vert/rouge du rejeu
const APPEARING = "#15803d";
const DISAPPEARING = "#b91c1c";

const RPKI_COLOR: Record<string, string> = { valid: "#15803d", invalid: "#b91c1c", "not-found": "#64748b" };
const RPKI_LABEL: Record<string, string> = {
  valid: "valide",
  invalid: "invalide (aucun ROA ne l'autorise)",
  "not-found": "aucun ROA ne couvre le préfixe",
};


export function GraphSvg({
  nodes,
  edges,
  nodeStatus,
  edgeStatus,
  edgeStable,
  focus = null,
  onFocus,
  paths,
}: {
  nodes: PropagationNode[];
  edges: PropagationEdge[];
  nodeStatus?: (index: number) => Status;
  edgeStatus?: (index: number) => Status;
  /** Lien présent pendant tout le rejeu : tracé en pointillé discret, comme les
   *  chemins « statiques » de BGPlay, pour que ce qui bouge ressorte. */
  edgeStable?: (index: number) => boolean;
  /** AS épinglé (clic) ; le survol met aussi en évidence, sans épingler. */
  focus?: number | null;
  onFocus?: (asn: number | null) => void;
  /** Chemins complets (mode instantané) : mettent en évidence ceux qui traversent l'AS visé. */
  paths?: number[][];
}) {
  // Largeur disponible, arrondie à 40 px pour ne pas recalculer la disposition à
  // chaque pixel d'un redimensionnement ; sous 640 px, couches empilées (téléphone).
  const wrap = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState(1000);
  useEffect(() => {
    const el = wrap.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => setAvailable(Math.max(240, Math.round(el.clientWidth / 40) * 40));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const layout = useMemo(
    () => computeLayout(nodes, edges, { availableWidth: available }),
    [nodes, edges, available],
  );
  const { width, height, nodeWidth, vertical } = layout;
  const [hover, setHover] = useState<{ text: string; x: number; y: number; asn: number } | null>(
    null,
  );
  const maxObs = useMemo(() => Math.max(0, ...edges.map((e) => e.observations ?? 0)), [edges]);

  // Mise en évidence : l'AS survolé, à défaut l'AS épinglé.
  const focusAsn = hover?.asn ?? focus;
  const lit = useMemo(
    () => (focusAsn === null || focusAsn === undefined ? null : highlight(focusAsn, edges, paths)),
    [focusAsn, edges, paths],
  );

  return (
    <div className="table-wrap" ref={wrap}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        style={{ minWidth: vertical ? undefined : `${Math.min(width, 900)}px`, height: "auto" }}
        role="group"
        aria-label="Graphe de propagation du préfixe"
      >
        {edges.map((e, i) => {
          const d = edgePath(layout, e.source, e.target);
          if (!d) return null;
          const status = edgeStatus?.(i) ?? "active";
          const stable = status === "active" && (edgeStable?.(i) ?? false);
          const changed = status === "appearing" || status === "disappearing";
          // Épaisseur : racine du poids relatif, pour que les liens rares restent visibles.
          const weight =
            e.observations !== undefined && maxObs > 0
              ? 1 + 3.2 * Math.sqrt(e.observations / maxObs)
              : 1.3;
          const base = status === "inactive" ? 0.08 : status === "active" ? 0.55 : 0.95;
          const dim = lit && !lit.edges.has(i);
          const leak = (e.violation_observations ?? 0) > 0;
          return (
            <path
              key={i}
              data-leak={leak ? "1" : undefined}
              d={d}
              fill="none"
              stroke={
                status === "appearing"
                  ? APPEARING
                  : status === "disappearing"
                    ? DISAPPEARING
                    : leak
                  ? LEAK
                  : RELATION_COLOR[e.relation]
              }
              strokeWidth={changed ? 2.4 : lit && lit.edges.has(i) ? weight + 0.8 : weight}
              strokeDasharray={
                status === "disappearing"
                  ? "5 4"
                  : leak && status === "active"
                    ? "9 3 2 3"
                    : stable && !lit
                      ? "2 4"
                      : undefined
              }
              opacity={
                dim ? 0.05 : leak ? Math.max(base, 0.9) : stable && !lit ? base * 0.7 : lit ? Math.max(base, 0.85) : base
              }
            >
              {leak && (
                <title>
                  {`Violation valley-free : AS${e.source} → AS${e.target} (${e.violation_observations} observation(s)). Fuite de route probable.`}
                </title>
              )}
            </path>
          );
        })}
        {nodes.map((n, i) => {
          const pos = layout.positions[n.asn];
          if (!pos) return null;
          const status = nodeStatus?.(i) ?? "active";
          const isGroup = n.asn === GROUP_ASN;
          const label = n.as_name ? shorten(n.as_name, vertical ? 14 : 20) : "";
          const title = nodeTitle(n);
          const stroke =
            status === "appearing"
              ? APPEARING
              : status === "disappearing"
                ? DISAPPEARING
                : focus === n.asn
                  ? "var(--teal)"
                  : "var(--rule)";
          const dim = lit && !lit.nodes.has(n.asn);
          const toggle = () => onFocus?.(focus === n.asn ? null : n.asn);
          return (
            <g
              key={n.asn}
              transform={`translate(${pos.x}, ${pos.y})`}
              opacity={dim ? 0.15 : status === "inactive" ? 0.25 : 1}
              aria-label={title}
              role={onFocus ? "button" : undefined}
              aria-pressed={onFocus ? focus === n.asn : undefined}
              tabIndex={onFocus ? 0 : undefined}
              className={onFocus ? "graph-node" : undefined}
              style={{ cursor: onFocus ? "pointer" : undefined }}
              onMouseMove={(e) => setHover({ text: title, x: e.clientX, y: e.clientY, asn: n.asn })}
              onMouseLeave={() => setHover(null)}
              onClick={toggle}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggle();
                }
              }}
            >
              <rect
                width={nodeWidth}
                height={NODE_HEIGHT}
                rx={6}
                fill="var(--paper-raised)"
                stroke={stroke}
                strokeWidth={
                  status === "appearing" || status === "disappearing" || focus === n.asn ? 2.4 : 1
                }
                strokeDasharray={status === "disappearing" || isGroup ? "5 4" : undefined}
              />
              <text x={8} y={19} fontFamily="var(--font-mono)" fontSize={12} fill="var(--ink-900)">
                {isGroup ? "…" : `AS${n.asn}`}
              </text>
              {label && (
                <text x={8} y={35} fontSize={11} fill="var(--ink-400)">
                  {label}
                </text>
              )}
              {/* Ligne du haut, à droite : statut RPKI de l'origine puis observations.
                  Une seule ligne de texte : la ligne du nom, dessous, reste libre. */}
              {!isGroup && ((n.rpki && n.rpki !== "unknown") || (n.observations !== undefined && !vertical)) && (
                <text
                  x={nodeWidth - 8}
                  y={19}
                  textAnchor="end"
                  fontFamily="var(--font-mono)"
                  fontSize={10}
                  fill="var(--ink-400)"
                >
                  {n.rpki && n.rpki !== "unknown" && (
                    <tspan fill={RPKI_COLOR[n.rpki]} fontWeight={700}>
                      {n.rpki === "valid" ? "ROA✓" : n.rpki === "invalid" ? "ROA✗" : "sans ROA"}
                    </tspan>
                  )}
                  {n.observations !== undefined && !vertical && (
                    <tspan dx={n.rpki && n.rpki !== "unknown" ? 6 : 0}>×{n.observations}</tspan>
                  )}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {hover && (
        <div
          role="tooltip"
          className="graph-tooltip"
          style={{
            position: "fixed",
            left: Math.min(hover.x + 14, window.innerWidth - 340),
            top: hover.y + 14,
            maxWidth: 320,
            maxHeight: "60vh",
            overflow: "hidden",
            whiteSpace: "pre-line",
            pointerEvents: "none",
            zIndex: 30,
            padding: "0.5rem 0.7rem",
            fontSize: "0.78rem",
            lineHeight: 1.4,
            color: "var(--ink-900)",
            background: "var(--paper-raised)",
            border: "1px solid var(--rule)",
            borderRadius: "var(--radius)",
            boxShadow: "0 4px 14px rgba(0,0,0,0.18)",
          }}
        >
          {hover.text}
        </div>
      )}
      <div className="legend" style={{ marginTop: "0.5rem" }}>
        {Object.entries(RELATION_COLOR).map(([key, color]) => (
          <span key={key}>
            <i style={{ background: color }} />
            {relationLabel(key)}
          </span>
        ))}
        {edges.some((e) => (e.violation_observations ?? 0) > 0) && (
          <span>
            <i style={{ background: LEAK }} />
            Violation valley-free (fuite probable)
          </span>
        )}
        {maxObs > 0 && <span className="muted">Épaisseur du lien = observations</span>}
        {edgeStable && <span className="muted">Pointillé discret = présent pendant tout le rejeu</span>}
        {onFocus && <span className="muted">Clic sur un AS : isoler ses chemins</span>}
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

export function shorten(name: string, max = 20): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

/** Texte d'un nœud (infobulle au survol, détail dans la barre de focus au toucher). */
export function nodeTitle(n: PropagationNode): string {
  const isGroup = n.asn === GROUP_ASN;
  return isGroup
    ? [
        `${n.as_name} (regroupés)`,
        ...(n.members ?? [])
          .slice(0, 14)
          .map(
            (m) =>
              `AS${m.asn}${m.as_name ? ` ${m.as_name}` : ""}${m.country_iso2 ? ` (${m.country_iso2})` : ""}`,
          ),
        (n.members?.length ?? 0) > 14 ? `+ ${(n.members?.length ?? 0) - 14} autre(s)` : null,
      ]
        .filter(Boolean)
        .join("\n")
    : [
        `AS${n.asn}${n.org_name || n.as_name ? ` — ${n.org_name ?? n.as_name}` : ""}`,
        n.country_iso2 ? `Pays : ${n.country_iso2}` : null,
        n.observations !== undefined ? `Observations : ${n.observations}` : null,
        n.rpki && n.rpki !== "unknown" ? `RPKI (origine) : ${RPKI_LABEL[n.rpki]}` : null,
        ...(n.paths ?? []).map((p) => p.map((a) => `AS${a}`).join(" → ")),
        n.hidden_paths ? `+ ${n.hidden_paths} autre(s) chemin(s)` : null,
      ]
        .filter(Boolean)
        .join("\n");
}
