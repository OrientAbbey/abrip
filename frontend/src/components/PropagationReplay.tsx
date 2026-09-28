import { useEffect, useMemo, useState } from "react";
import { useApi } from "../lib/useApi";
import { AsyncBlock } from "./StateBlock";
import { GraphSvg } from "./PropagationSvg";
import type { PropagationEdge, PropagationNode, Status } from "./PropagationSvg";

interface ReplayFrame {
  ts: string;
  announcements: number;
  withdrawals: number;
  path_count: number;
  nodes: number[]; // ASN actifs à cet instant
  edges: number[]; // indices dans Replay.edges
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
  frames: ReplayFrame[];
}

const STEPS = [1, 5, 15, 30, 60, 180];
const SPEEDS = [0.5, 1, 2, 4];
const BASE_INTERVAL_MS = 700;

const fmt = (ts: string) => `${ts.slice(0, 10)} ${ts.slice(11, 16)} UTC`;

/** Rejeu de la propagation : la fenêtre est découpée côté serveur en
 *  tranches, chacune portant l'état du graphe à sa fin. La disposition est
 *  calculée une fois sur l'union de toutes les tranches (les nœuds ne
 *  bougent pas pendant la lecture) ; ce qui est absent à l'instant affiché
 *  est grisé, ce qui vient d'apparaître ou de disparaître est signalé. */
export function PropagationReplay({
  prefix,
  asn,
  targets,
}: {
  prefix: string;
  asn: string;
  targets: string;
}) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [step, setStep] = useState("15");

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
          <input id="rp-from" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rp-to">Au (UTC)</label>
          <input id="rp-to" type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rp-step">Pas</label>
          <select id="rp-step" value={step} onChange={(e) => setStep(e.target.value)}>
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
            <button type="button" onClick={() => (setFrom(""), setTo(""))}>
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
            <ReplayPlayer
              key={`${body.start}|${body.end}|${body.step_minutes}|${asn}|${targets}`}
              body={body}
              requestedStep={Number(step)}
            />
          )
        }
      </AsyncBlock>
    </div>
  );
}

function ReplayPlayer({ body, requestedStep }: { body: Replay; requestedStep: number }) {
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

  const play = () => {
    if (index >= last) setIndex(0);
    setPlaying((p) => !p);
  };

  return (
    <div>
      <div className="row" style={{ margin: "0.5rem 0" }}>
        <button type="button" onClick={() => (setPlaying(false), setIndex(0))}>
          Début
        </button>
        <button type="button" onClick={() => (setPlaying(false), setIndex((i) => Math.max(0, i - 1)))}>
          Précédent
        </button>
        <button type="button" onClick={play}>
          {playing ? "Pause" : "Lecture"}
        </button>
        <button type="button" onClick={() => (setPlaying(false), setIndex((i) => Math.min(last, i + 1)))}>
          Suivant
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
        onChange={(e) => (setPlaying(false), setIndex(Number(e.target.value)))}
      />
      <ActivityStrip
        frames={body.frames}
        index={index}
        onSelect={(i) => (setPlaying(false), setIndex(i))}
      />

      <div className="legend">
        <span>
          <i style={{ background: "var(--ink-400)" }} />
          Annonces par tranche
        </span>
        <span>
          <i style={{ background: "#b91c1c" }} />
          Retraits par tranche
        </span>
      </div>

      <p className="mono" style={{ margin: "0.4rem 0" }}>
        {fmt(frame.ts)} · {frame.path_count} chemin(s) actif(s) · dans la tranche :{" "}
        {frame.announcements} annonce(s), {frame.withdrawals} retrait(s)
      </p>

      <GraphSvg
        nodes={body.nodes}
        edges={body.edges}
        nodeStatus={nodeStatus}
        edgeStatus={edgeStatus}
      />
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
 *  à la tranche cliquée. Le curseur `range` au-dessus reste la voie
 *  accessible au clavier. */
function ActivityStrip({
  frames,
  index,
  onSelect,
}: {
  frames: ReplayFrame[];
  index: number;
  onSelect: (i: number) => void;
}) {
  const max = Math.max(1, ...frames.map((f) => f.announcements + f.withdrawals));
  const slot = 6;
  const height = 40;
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
        const a = (f.announcements / max) * (height - 4);
        const w = (f.withdrawals / max) * (height - 4);
        return (
          <g key={i}>
            <rect x={i * slot + 1} y={height - a} width={slot - 2} height={a} fill="var(--ink-400)" />
            <rect x={i * slot + 1} y={height - a - w} width={slot - 2} height={w} fill="#b91c1c" />
          </g>
        );
      })}
      <rect x={index * slot} y={0} width={slot} height={height} fill="var(--teal)" opacity={0.25} />
    </svg>
  );
}
