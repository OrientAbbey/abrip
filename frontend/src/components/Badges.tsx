import { Link } from "react-router-dom";
import { CONFIDENCE_LABEL, SEVERITY_LABEL } from "../lib/format";

/** AS<numéro>, avec le nom (CAIDA AS2Org) entre parenthèses quand il est
 *  connu. De nombreux AS africains n'ont pas d'entrée AS2Org : on affiche
 *  alors le numéro seul plutôt qu'une mention vide ou trompeuse. */
export function AsLink({ asn, name }: { asn: number; name?: string | null }) {
  return (
    <Link to={`/asns/${asn}`}>
      <span className="mono">AS{asn}</span>
      {name ? ` (${name})` : ""}
    </Link>
  );
}

/** La couleur ne porte jamais l'information seule : le libellé est toujours
 *  écrit, et les trois teintes diffèrent aussi par la luminance. */
export function SeverityBadge({ severity }: { severity: string }) {
  const label = SEVERITY_LABEL[severity] ?? severity;
  return (
    <span className={`badge ${severity}`} title={`Sévérité : ${label}`}>
      {label}
    </span>
  );
}

export function ConfidenceBadge({ confidence }: { confidence: string }) {
  return <span className="badge plain">{CONFIDENCE_LABEL[confidence] ?? confidence}</span>;
}

const DATAPLANE_VERDICT_STYLE: Record<string, { css: string; label: string }> = {
  confirmed: { css: "watch", label: "confirmé par le plan de données" },
  contradicted: { css: "reassuring", label: "contredit par le plan de données" },
  inconclusive: { css: "plain", label: "non concluant" },
  not_attempted: { css: "plain", label: "non vérifié" },
};

export function DataplaneVerdictBadge({ verdict }: { verdict: string }) {
  const style = DATAPLANE_VERDICT_STYLE[verdict] ?? { css: "plain", label: verdict };
  return <span className={`badge ${style.css}`}>{style.label}</span>;
}

export function ScoreBar({ score }: { score: number }) {
  const width = Math.max(2, Math.min(100, score * 100));
  const tone = score >= 0.65 ? "var(--crimson)" : score >= 0.35 ? "var(--amber)" : "var(--ink-400)";
  return (
    <span className="row" style={{ gap: "0.4rem" }}>
      <span
        aria-hidden="true"
        style={{
          display: "inline-block",
          width: "3.2rem",
          height: "0.4rem",
          background: "var(--paper-sunk)",
          borderRadius: "2px",
          overflow: "hidden",
        }}
      >
        <span style={{ display: "block", width: `${width}%`, height: "100%", background: tone }} />
      </span>
      <span className="mono">{score.toFixed(2)}</span>
    </span>
  );
}
