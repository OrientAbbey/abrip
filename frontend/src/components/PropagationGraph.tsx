import { useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { AsyncBlock } from "./StateBlock";
import { Tabs } from "./Tabs";
import { useAsnName } from "../lib/useAsnNames";
import { downloadCsv, downloadPng, downloadSvg } from "../lib/exportGraph";
import { foldForeign } from "../lib/graphFold";
import { FocusBar } from "./FocusBar";
import { rangeParams, type DateRange } from "./DateRangeSelector";
import { GraphSvg } from "./PropagationSvg";
import type { PropagationEdge, PropagationNode } from "./PropagationSvg";
import { PropagationReplay } from "./PropagationReplay";

interface Propagation {
  prefix: string;
  asn: number | null;
  nodes: PropagationNode[];
  edges: PropagationEdge[];
  paths: Array<{ path: number[]; observations: number; valley_violation?: boolean }>;
  paths_total: number;
  paths_hidden: number;
  max_observations: number;
  moas: boolean;
}

type Mode = "snapshot" | "replay";

const MODES: Array<{ value: Mode; label: string; title: string }> = [
  { value: "snapshot", label: "Instantané", title: "Tous les chemins vus sur la fenêtre, agrégés" },
  { value: "replay", label: "Rejouer", title: "Dérouler la propagation dans le temps" },
];

/** Seuils de bruit proposés : nombre minimal de messages BGP par chemin. */
const MIN_OBSERVATIONS = [1, 5, 10, 25, 50, 100];

/** Graphe de propagation d'un préfixe (ADR 0004) : chaque AS distinct vu sur
 *  un chemin observé, disposé en colonnes par distance à l'origine (BFS sur
 *  les arêtes), les arêtes colorées par relation. Réduit, pas étendu :
 *  aucun AS non observé n'est ajouté pour compléter la topologie.
 *
 *  Deux modes qui partagent leurs filtres (origine, cibles) : l'instantané
 *  agrège toute la fenêtre ; le rejeu la déroule tranche par tranche.
 *  L'état de la vue (mode, filtres, AS épinglé, tranche du rejeu) vit dans
 *  l'URL (paramètres `g_*`) : copier l'adresse suffit à partager la vue, et la
 *  fiche d'un événement y renvoie directement. */
export function PropagationGraph({
  prefix,
  origins,
  range,
}: {
  prefix: string;
  origins: Array<{ origin_asn: number }>;
  /** Plage de la page (mode instantané) ; le rejeu a sa propre tranche horaire. */
  range?: DateRange;
}) {
  const [params, setParams] = useSearchParams();
  const get = (key: string, fallback = "") => params.get(`g_${key}`) ?? fallback;
  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(`g_${key}`, value);
      else next.delete(`g_${key}`);
    }
    setParams(next, { replace: true });
  };

  const mode: Mode = get("mode") === "replay" ? "replay" : "snapshot";
  // Une seule origine : inutile de la demander, elle est présélectionnée.
  const asn = get("asn") || (origins.length === 1 ? String(origins[0].origin_asn) : "");
  const targetsInput = get("targets");
  const targets = targetsInput
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
    .join(",");
  const minObs = Number(get("min", "1")) || 1;
  const fold = get("fold") === "1";
  const focus = get("focus") ? Number(get("focus")) : null;

  const box = useRef<HTMLDivElement>(null);
  const [notice, setNotice] = useState("");
  const say = (text: string) => {
    setNotice(text);
    window.setTimeout(() => setNotice(""), 2500);
  };
  const svg = () => box.current?.querySelector<SVGSVGElement>("svg[aria-label^='Graphe']") ?? null;
  const base = `propagation-${prefix.replace(/[^\w.-]+/g, "_")}`;

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      say("Lien copié");
    } catch {
      say("Copie impossible : l'adresse de la page contient déjà la vue");
    }
  };
  const run = (job: () => void | Promise<void>) => async () => {
    try {
      await job();
    } catch (error) {
      say(error instanceof Error ? error.message : "Export impossible");
    }
  };

  const state = useApi<Propagation>(
    mode === "snapshot" ? `/prefixes/${encodeURIComponent(prefix)}/propagation` : null,
    {
      asn: asn || undefined,
      targets: targets || undefined,
      min_observations: minObs > 1 ? minObs : undefined,
      ...(range ? rangeParams(range) : {}),
    },
  );

  return (
    <section className="card" ref={box}>
      <h2>Graphe de propagation</h2>
      <Tabs
        options={MODES}
        value={mode}
        onChange={(value) => set({ mode: value === "replay" ? "replay" : "" })}
        label="Mode du graphe de propagation"
      />
      <div className="filters" style={{ marginTop: "0.6rem" }}>
        {origins.length > 1 && (
          <div className="field">
            <label htmlFor="prop-asn">Origine</label>
            <select id="prop-asn" value={asn} onChange={(e) => set({ asn: e.target.value, focus: "" })}>
              <option value="">Toutes</option>
              {origins.map((o) => (
                <OriginOption key={o.origin_asn} asn={o.origin_asn} />
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="prop-targets">Cibles (ASN séparés par des virgules)</label>
          <input
            id="prop-targets"
            type="text"
            value={targetsInput}
            placeholder="ex. 174,3356,6939"
            onChange={(e) => set({ targets: e.target.value, focus: "" })}
          />
        </div>
        {mode === "snapshot" && (
          <div className="field">
            <label htmlFor="prop-min">Chemins vus au moins</label>
            <select
              id="prop-min"
              value={minObs}
              onChange={(e) => set({ min: e.target.value === "1" ? "" : e.target.value })}
            >
              {MIN_OBSERVATIONS.map((n) => (
                <option key={n} value={n}>
                  {n === 1 ? "1 fois (tous)" : `${n} fois`}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="prop-fold">Hors Afrique</label>
          <div
            className="row"
            style={{ gap: "0.4rem", minHeight: "2rem", justifyContent: "flex-start" }}
          >
            <input
              id="prop-fold"
              type="checkbox"
              style={{ width: "auto", minWidth: "auto", padding: 0 }}
              checked={fold}
              onChange={(e) => set({ fold: e.target.checked ? "1" : "", focus: "" })}
            />
            <span>Replier les AS</span>
          </div>
        </div>
      </div>

      <div className="row" style={{ margin: "0.5rem 0", gap: "0.5rem", flexWrap: "wrap" }}>
        <span className="muted">Exporter :</span>
        <button type="button" onClick={run(() => downloadSvg(svg()!, `${base}.svg`))}>
          SVG
        </button>
        <button type="button" onClick={run(() => downloadPng(svg()!, `${base}.png`))}>
          PNG
        </button>
        {mode === "snapshot" && (
          <button
            type="button"
            disabled={!state.data || state.data.paths.length === 0}
            onClick={run(() =>
              downloadCsv(
                ["chemin", "longueur", "observations", "origine"],
                (state.data?.paths ?? []).map((p) => [
                  p.path.map((a) => `AS${a}`).join(" → "),
                  p.path.length,
                  p.observations,
                  `AS${p.path[0]}`,
                ]),
                `${base}-chemins.csv`,
              ),
            )}
          >
            Chemins (CSV)
          </button>
        )}
        <button type="button" onClick={copyLink}>
          Copier le lien
        </button>
        {notice && (
          <span role="status" className="muted">
            {notice}
          </span>
        )}
      </div>

      {mode === "snapshot" ? (
        <AsyncBlock state={state} rows={4}>
          {(body) => (
            <Snapshot
              body={body}
              fold={fold}
              focus={focus}
              onFocus={(value) => set({ focus: value === null ? "" : String(value) })}
              minObs={minObs}
            />
          )}
        </AsyncBlock>
      ) : (
        <PropagationReplay
          prefix={prefix}
          asn={asn}
          targets={targets}
          from={get("from")}
          to={get("to")}
          step={get("step", "15")}
          fold={fold}
          onWindow={(patch) => set(patch)}
          focus={focus}
          onFocus={(value) => set({ focus: value === null ? "" : String(value) })}
        />
      )}
    </section>
  );
}

function Snapshot({
  body,
  fold,
  focus,
  onFocus,
  minObs,
}: {
  body: Propagation;
  fold: boolean;
  focus: number | null;
  onFocus: (asn: number | null) => void;
  minObs: number;
}) {
  const shown = useMemo(
    () => {
      const paths = body.paths.map((p) => p.path);
      return fold
        ? foldForeign(body.nodes, body.edges, paths)
        : { nodes: body.nodes, edges: body.edges, paths, folded: 0 };
    },
    [body, fold],
  );
  if (body.nodes.length === 0) {
    return (
      <p className="muted">
        {body.paths_hidden > 0
          ? `Aucun chemin vu au moins ${minObs} fois : ${body.paths_hidden} chemin(s) sous le seuil. Abaissez-le pour les voir.`
          : "Aucun chemin observé pour ce préfixe sur la période."}
      </p>
    );
  }
  return (
    <>
      <Alerts body={body} />
      <FocusBar focus={focus} nodes={shown.nodes} onFocus={onFocus} />
      <GraphSvg
        nodes={shown.nodes}
        edges={shown.edges}
        focus={focus}
        onFocus={onFocus}
        paths={shown.paths}
      />
      <p className="card-note">
        Graphe réduit : seuls les AS effectivement vus sur un chemin observé pour ce préfixe
        apparaissent, sans complétion vers les voisins connus mais non observés. {body.paths.length}
        {body.paths_total > body.paths.length + body.paths_hidden ? "+" : ""} chemin(s) affiché(s)
        {body.paths_hidden > 0 && `, ${body.paths_hidden} masqué(s) sous le seuil de ${minObs} observations`}
        {shown.folded > 0 && `, ${shown.folded} AS hors Afrique repliés (les origines restent visibles)`}.
        Les observations comptent des messages BGP, pas des pairs distincts.
      </p>
    </>
  );
}

/** Option du sélecteur d'origine : « AS37100 · LITTORAL-TELECOM » quand le nom est connu. */
function OriginOption({ asn }: { asn: number }) {
  const name = useAsnName(asn);
  return <option value={asn}>{name ? `AS${asn} · ${name}` : `AS${asn}`}</option>;
}

/** Ce que le graphe contient d'anormal, en une ligne : origines multiples,
 *  origine sans autorisation RPKI, chemins qui violent le modèle valley-free.
 *  Rien à signaler : rien d'affiché. */
function Alerts({ body }: { body: Propagation }) {
  const invalid = body.nodes.filter((n) => n.rpki === "invalid");
  const leaks = body.edges.filter((e) => (e.violation_observations ?? 0) > 0);
  const leakPaths = body.paths.filter((p) => p.valley_violation).length;
  if (!body.moas && invalid.length === 0 && leaks.length === 0) return null;
  return (
    <div className="row" role="note" style={{ gap: "0.5rem", flexWrap: "wrap", margin: "0.3rem 0" }}>
      {body.moas && <span className="tag">Origines multiples (MOAS)</span>}
      {invalid.map((n) => (
        <span key={n.asn} className="tag" style={{ color: "#b91c1c" }}>
          AS{n.asn} : origine sans ROA valide
        </span>
      ))}
      {leaks.length > 0 && (
        <span className="tag" style={{ color: "#be185d" }}>
          Fuite probable (valley-free) : {leakPaths} chemin(s), lien
          {leaks.length > 1 ? "s" : ""} {leaks.map((e) => `AS${e.source} → AS${e.target}`).join(", ")}
        </span>
      )}
    </div>
  );
}
