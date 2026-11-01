import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { detectorLabel } from "../lib/format";
import type { EventOut, Page } from "../lib/types";
import { SeverityBadge } from "./Badges";
import { AsyncBlock } from "./StateBlock";
import { FocusBar } from "./FocusBar";
import { foldReplay } from "../lib/graphFold";
import { GraphSvg } from "./PropagationSvg";
import type { PropagationEdge, PropagationNode, Status } from "./PropagationSvg";

interface ReplayFrame {
  ts: string;
  announcements: number;
  withdrawals: number;
  path_count: number;
  nodes: number[]; // ASN actifs à cet instant
  edges: number[]; // indices dans Replay.edges
  path_ids?: number[]; // indices dans Replay.paths
}
interface Replay {
  prefix: string;
  start: string | null;
  end: string | null;
  step_minutes: number;
  warmup_hours: number;
  clamped: boolean;
  nodes: PropagationNode[];
  edges: PropagationEdge[];
  /** Chemins distincts de la fenêtre ; absent (null) au-delà d'une borne de taille. */
  paths: number[][] | null;
  frames: ReplayFrame[];
}

const STEPS = [1, 5, 15, 30, 60, 180];
const SPEEDS = [0.5, 1, 2, 4];
const BASE_INTERVAL_MS = 700;
const GREEN = "#15803d";
const RED = "#b91c1c";
const SEVERITY_COLOR: Record<string, string> = { critical: RED, watch: "#b45309", info: "#64748b" };

const fmt = (ts: string) => `${ts.slice(0, 10)} ${ts.slice(11, 16)} UTC`;

/** Rejeu de la propagation : la fenêtre est découpée côté serveur en
 *  tranches, chacune portant l'état du graphe à sa fin. La disposition est
 *  calculée une fois sur l'union de toutes les tranches (les nœuds ne
 *  bougent pas pendant la lecture) ; ce qui est absent à l'instant affiché
 *  est grisé, ce qui vient d'apparaître ou de disparaître est signalé.
 *  La tranche (du, au, pas) est pilotée par le parent : elle vit dans l'URL. */
export function PropagationReplay({
  prefix,
  asn,
  targets,
  from,
  to,
  step,
  fold,
  onWindow,
  focus,
  onFocus,
}: {
  prefix: string;
  asn: string;
  targets: string;
  from: string;
  to: string;
  step: string;
  fold: boolean;
  onWindow: (patch: Record<string, string>) => void;
  focus: number | null;
  onFocus: (asn: number | null) => void;
}) {
  const state = useApi<Replay>(`/prefixes/${encodeURIComponent(prefix)}/propagation/replay`, {
    asn: asn || undefined,
    targets: targets || undefined,
    from: from ? `${from}:00Z` : undefined,
    to: to ? `${to}:00Z` : undefined,
    step,
  });

  return (
    <div>
      <div className="filters">
        <div className="field">
          <label htmlFor="rp-from">Du (UTC)</label>
          <input
            id="rp-from"
            type="datetime-local"
            value={from}
            onChange={(e) => onWindow({ from: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="rp-to">Au (UTC)</label>
          <input
            id="rp-to"
            type="datetime-local"
            value={to}
            onChange={(e) => onWindow({ to: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="rp-step">Pas</label>
          <select id="rp-step" value={step} onChange={(e) => onWindow({ step: e.target.value })}>
            {STEPS.map((s) => (
              <option key={s} value={s}>
                {s < 60 ? `${s} min` : `${s / 60} h`}
              </option>
            ))}
          </select>
        </div>
        {(from || to) && (
          <div className="field">
            <label>&nbsp;</label>
            <button type="button" onClick={() => onWindow({ from: "", to: "" })}>
              Toute la période
            </button>
          </div>
        )}
      </div>
      <AsyncBlock state={state} rows={4}>
        {(body) =>
          body.frames.length === 0 ? (
            <p className="muted">Aucun événement pour ce préfixe sur cette fenêtre.</p>
          ) : body.nodes.length === 0 ? (
            <p className="muted">Aucun chemin actif sur cette fenêtre.</p>
          ) : (
            <FoldedPlayer
              key={`${body.start}|${body.end}|${body.step_minutes}|${asn}|${targets}|${fold}`}
              body={body}
              fold={fold}
              requestedStep={Number(step)}
              prefix={prefix}
              focus={focus}
              onFocus={onFocus}
            />
          )
        }
      </AsyncBlock>
    </div>
  );
}

/** Applique le repli hors Afrique (une fois par jeu de données, pas à chaque tranche). */
function FoldedPlayer({
  body,
  fold,
  ...rest
}: {
  body: Replay;
  fold: boolean;
  requestedStep: number;
  prefix: string;
  focus: number | null;
  onFocus: (asn: number | null) => void;
}) {
  const shown = useMemo(() => (fold ? foldReplay(body) : body), [body, fold]);
  return <ReplayPlayer body={shown} {...rest} />;
}

const asLabel = (nodes: PropagationNode[], asn: number) => {
  const name = nodes.find((n) => n.asn === asn)?.as_name;
  return name ? `AS${asn} (${name})` : `AS${asn}`;
};

function ReplayPlayer({
  body,
  requestedStep,
  prefix,
  focus,
  onFocus,
}: {
  body: Replay;
  requestedStep: number;
  prefix: string;
  focus: number | null;
  onFocus: (asn: number | null) => void;
}) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const last = body.frames.length - 1;

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(
      () => setIndex((i) => Math.min(i + 1, last)),
      BASE_INTERVAL_MS / speed,
    );
    return () => window.clearInterval(id);
  }, [playing, speed, last]);

  useEffect(() => {
    if (playing && index >= last) setPlaying(false);
  }, [index, playing, last]);

  const frame = body.frames[index];
  const previous = body.frames[Math.max(0, index - 1)];
  const sets = useMemo(
    () => ({
      nodes: new Set(frame.nodes),
      prevNodes: new Set(previous.nodes),
      edges: new Set(frame.edges),
      prevEdges: new Set(previous.edges),
    }),
    [frame, previous],
  );

  const status = (now: boolean, before: boolean): Status =>
    now && before ? "active" : now ? "appearing" : before ? "disappearing" : "inactive";
  const nodeStatus = (i: number) => {
    const asnOfNode = body.nodes[i].asn;
    return status(sets.nodes.has(asnOfNode), sets.prevNodes.has(asnOfNode));
  };
  const edgeStatus = (i: number) => status(sets.edges.has(i), sets.prevEdges.has(i));

  // Liens présents à toutes les tranches : le « décor » du rejeu, tracé en retrait.
  const stableEdges = useMemo(() => {
    const always = new Set(body.frames[0].edges);
    for (const f of body.frames) {
      const here = new Set(f.edges);
      for (const e of [...always]) if (!here.has(e)) always.delete(e);
    }
    return always;
  }, [body.frames]);

  // Tranches où la topologie change par rapport à la précédente : de quoi
  // sauter d'un changement à l'autre sans parcourir les tranches calmes.
  const changeFrames = useMemo(
    () =>
      body.frames.reduce<number[]>((acc, f, i) => {
        if (i > 0 && f.edges.join(",") !== body.frames[i - 1].edges.join(",")) acc.push(i);
        return acc;
      }, []),
    [body.frames],
  );
  const previousChange = [...changeFrames].reverse().find((i) => i < index);
  const nextChange = changeFrames.find((i) => i > index);

  // Écart avec la première tranche : ce qui a bougé depuis le début.
  // Chemins actifs à la tranche affichée : mise en évidence exacte d'un AS épinglé.
  const activePaths = useMemo(
    () => (body.paths && frame.path_ids ? frame.path_ids.map((i) => body.paths![i]) : undefined),
    [body.paths, frame],
  );

  const diff = useMemo(() => {
    const first = new Set(body.frames[0].edges);
    const now = new Set(frame.edges);
    return {
      added: frame.edges.filter((e) => !first.has(e)).map((e) => body.edges[e]),
      removed: body.frames[0].edges.filter((e) => !now.has(e)).map((e) => body.edges[e]),
    };
  }, [body, frame]);

  // Événements détectés sur ce préfixe pendant la fenêtre : repères sur la frise.
  const events = useApi<Page<EventOut>>("/events", {
    prefix,
    from: body.start ?? undefined,
    to: body.end ?? undefined,
    sort: "oldest",
    limit: 50,
  });
  const markers = useMemo(
    () =>
      (events.data?.items ?? []).map((ev) => {
        const t = Date.parse(ev.first_seen.endsWith("Z") ? ev.first_seen : `${ev.first_seen}Z`);
        const found = body.frames.findIndex((f) => Date.parse(f.ts) >= t);
        return { event: ev, index: found === -1 ? last : found };
      }),
    [events.data, body.frames, last],
  );

  const go = (i: number) => (setPlaying(false), setIndex(Math.min(last, Math.max(0, i))));
  const play = () => {
    if (index >= last) setIndex(0);
    setPlaying((p) => !p);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const tag = (e.target as HTMLElement).tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "BUTTON" || tag === "TEXTAREA") return;
    if (e.key === " ") (e.preventDefault(), play());
    else if (e.key === "ArrowRight") (e.preventDefault(), go(index + 1));
    else if (e.key === "ArrowLeft") (e.preventDefault(), go(index - 1));
    else if (e.key === "Home") (e.preventDefault(), go(0));
    else if (e.key === "End") (e.preventDefault(), go(last));
  };

  const list = (edges: PropagationEdge[]) =>
    edges
      .slice(0, 6)
      .map((e) => `${asLabel(body.nodes, e.source)} → ${asLabel(body.nodes, e.target)}`)
      .join(" ; ") + (edges.length > 6 ? ` ; + ${edges.length - 6} autre(s)` : "");

  return (
    <div
      tabIndex={0}
      role="group"
      aria-label="Lecteur de rejeu (Espace : lecture, flèches : tranche précédente ou suivante)"
      onKeyDown={onKeyDown}
      style={{ outline: "none" }}
    >
      <div className="row" style={{ margin: "0.5rem 0", flexWrap: "wrap", gap: "0.4rem" }}>
        <button type="button" onClick={() => go(0)}>
          Début
        </button>
        <button type="button" onClick={() => go(index - 1)}>
          Précédent
        </button>
        <button type="button" onClick={play}>
          {playing ? "Pause" : "Lecture"}
        </button>
        <button type="button" onClick={() => go(index + 1)}>
          Suivant
        </button>
        <button
          type="button"
          disabled={previousChange === undefined}
          title="Aller à la tranche précédente où la topologie change"
          onClick={() => previousChange !== undefined && go(previousChange)}
        >
          ◂ Changement
        </button>
        <button
          type="button"
          disabled={nextChange === undefined}
          title="Aller à la tranche suivante où la topologie change"
          onClick={() => nextChange !== undefined && go(nextChange)}
        >
          Changement ▸
        </button>
        <label htmlFor="rp-speed" className="muted">
          Vitesse
        </label>
        <select id="rp-speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              ×{s}
            </option>
          ))}
        </select>
      </div>

      <input
        type="range"
        min={0}
        max={last}
        value={index}
        aria-label="Instant affiché"
        style={{ width: "100%" }}
        onChange={(e) => go(Number(e.target.value))}
      />
      <ActivityStrip
        frames={body.frames}
        index={index}
        onSelect={go}
        markers={markers.map((m) => ({
          index: m.index,
          severity: m.event.severity,
          label: `${detectorLabel(m.event.detector)} — ${fmt(m.event.first_seen)}`,
        }))}
      />

      <div className="legend">
        <span>
          <i style={{ background: "var(--ink-400)" }} />
          Annonces par tranche
        </span>
        <span>
          <i style={{ background: RED }} />
          Retraits par tranche
        </span>
        {markers.length > 0 && <span className="muted">▼ événement détecté (clic : y aller)</span>}
      </div>

      <p className="mono" style={{ margin: "0.4rem 0" }}>
        {fmt(frame.ts)} · {frame.path_count} chemin(s) actif(s) · dans la tranche :{" "}
        {frame.announcements} annonce(s), {frame.withdrawals} retrait(s)
      </p>

      <FocusBar focus={focus} nodes={body.nodes} onFocus={onFocus} />
      <GraphSvg
        nodes={body.nodes}
        edges={body.edges}
        nodeStatus={nodeStatus}
        edgeStatus={edgeStatus}
        edgeStable={(i) => stableEdges.has(i)}
        focus={focus}
        onFocus={onFocus}
        paths={activePaths}
      />

      <p className="card-note" aria-live="polite">
        Depuis le début de la fenêtre :{" "}
        {diff.added.length === 0 && diff.removed.length === 0 ? (
          <span>aucun changement de liens.</span>
        ) : (
          <>
            {diff.added.length > 0 && (
              <span style={{ color: GREEN }}>
                +{diff.added.length} lien(s) : {list(diff.added)}.{" "}
              </span>
            )}
            {diff.removed.length > 0 && (
              <span style={{ color: RED }}>
                −{diff.removed.length} lien(s) : {list(diff.removed)}.
              </span>
            )}
          </>
        )}
      </p>

      {markers.length > 0 && (
        <div className="card-note">
          <strong>Événements détectés sur la fenêtre</strong>
          <ul style={{ margin: "0.3rem 0 0", paddingLeft: "1.1rem" }}>
            {markers.map(({ event, index: at }) => (
              <li key={event.event_id}>
                <button type="button" className="link-button" onClick={() => go(at)}>
                  {fmt(event.first_seen)}
                </button>{" "}
                {detectorLabel(event.detector)} <SeverityBadge severity={event.severity} />{" "}
                <Link to={`/events/${event.event_id}`}>détail</Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="card-note">
        {body.frames.length} tranches, pas de {body.step_minutes} min
        {body.step_minutes !== requestedStep && " (élargi pour rester sous 200 tranches)"} ; état
        amorcé {body.warmup_hours} h avant le début — un pair silencieux depuis plus longtemps est
        absent au départ.
        {body.clamped && " Fenêtre limitée aux 7 derniers jours."} Les compteurs comptent les
        événements du préfixe, toutes origines confondues.
      </p>
    </div>
  );
}

/** Annonces et retraits par tranche, avec le curseur courant ; un clic saute
 *  à la tranche cliquée. Les repères ▼ marquent les événements détectés. Le
 *  curseur `range` au-dessus reste la voie accessible au clavier. */
function ActivityStrip({
  frames,
  index,
  onSelect,
  markers,
}: {
  frames: ReplayFrame[];
  index: number;
  onSelect: (i: number) => void;
  markers: Array<{ index: number; severity: string; label: string }>;
}) {
  const max = Math.max(1, ...frames.map((f) => f.announcements + f.withdrawals));
  const slot = 6;
  const band = markers.length > 0 ? 12 : 0; // bande réservée aux repères
  const bars = 40;
  const height = bars + band;
  return (
    <svg
      viewBox={`0 0 ${frames.length * slot} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label="Annonces et retraits par tranche"
      style={{ cursor: "pointer", display: "block" }}
      onClick={(e) => {
        const box = e.currentTarget.getBoundingClientRect();
        const i = Math.floor(((e.clientX - box.left) / box.width) * frames.length);
        onSelect(Math.min(frames.length - 1, Math.max(0, i)));
      }}
    >
      {frames.map((f, i) => {
        const a = (f.announcements / max) * (bars - 4);
        const w = (f.withdrawals / max) * (bars - 4);
        return (
          <g key={i}>
            <rect x={i * slot + 1} y={height - a} width={slot - 2} height={a} fill="var(--ink-400)" />
            <rect x={i * slot + 1} y={height - a - w} width={slot - 2} height={w} fill={RED} />
          </g>
        );
      })}
      {markers.map((m, k) => (
        <g
          key={k}
          data-marker={m.index}
          className="graph-node"
          role="button"
          tabIndex={0}
          aria-label={`Aller à l'événement : ${m.label}`}
          onClick={(e) => (e.stopPropagation(), onSelect(m.index))}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              e.stopPropagation();
              onSelect(m.index);
            }
          }}
          style={{ cursor: "pointer" }}
        >
          <title>{m.label}</title>
          <polygon
            points={`${m.index * slot + slot / 2 - 1.3},0 ${m.index * slot + slot / 2 + 1.3},0 ${m.index * slot + slot / 2},${band - 1}`}
            fill={SEVERITY_COLOR[m.severity] ?? "#64748b"}
          />
        </g>
      ))}
      <rect
        x={index * slot}
        y={band}
        width={slot}
        height={bars}
        fill="var(--teal)"
        opacity={0.25}
      />
    </svg>
  );
}
