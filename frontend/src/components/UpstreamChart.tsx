import { useSearchParams } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { AsyncBlock } from "./StateBlock";
import { rangeParams, type DateRange } from "./DateRangeSelector";
import { PALETTE, TimeChart, type ChartSeries } from "./TimeChart";
import type { TimePoint } from "../lib/types";

interface Upstreams {
  prefix: string;
  asn: number | null;
  bucket_hours: number;
  upstreams: Array<{ asn: number; as_name: string | null; peak_peers: number }>;
  points: TimePoint[];
}

// Les cinq couleurs de la plateforme, puis des teintes de même registre.
const COLORS = [
  PALETTE.ink,
  PALETTE.teal,
  PALETTE.amber,
  PALETTE.crimson,
  PALETTE.slate,
  "#6b5b95",
  "#8a8d3a",
  "#2f7fa3",
];

/** Fournisseurs amont d'un préfixe dans le temps : pour chaque tranche, les
 *  pairs (collecteur, adresse) qui le voient par chacun de ses fournisseurs,
 *  barres empilées. Un basculement de fournisseur se lit comme une barre qui
 *  en remplace une autre ; un creux, comme une perte de visibilité.
 *  L'origine suit le filtre du graphe de propagation (`g_asn` dans l'URL). */
export function UpstreamChart({ prefix, range }: { prefix: string; range?: DateRange }) {
  const [params] = useSearchParams();
  const asn = params.get("g_asn") ?? "";
  const state = useApi<Upstreams>(`/prefixes/${encodeURIComponent(prefix)}/upstreams`, {
    asn: asn || undefined,
    ...(range ? rangeParams(range) : {}),
  });

  return (
    <section className="card">
      <h2>Fournisseurs amont dans le temps</h2>
      <AsyncBlock state={state} rows={3}>
        {(body) => {
          if (body.upstreams.length === 0) {
            return (
              <p className="muted">
                Aucun chemin d'au moins deux AS sur cette période : l'origine n'a pas de
                fournisseur amont observable.
              </p>
            );
          }
          const series: ChartSeries[] = body.upstreams.map((u, i) => ({
            key: `as${u.asn}`,
            label: u.as_name ? `AS${u.asn} · ${u.as_name}` : `AS${u.asn}`,
            color: COLORS[i % COLORS.length],
            kind: "bar",
          }));
          return (
            <TimeChart
              points={body.points}
              series={series}
              height={220}
              stacked
              valueFormat={(v) => `${Math.round(v)}`}
              note={`Pairs (collecteur, adresse) qui ont annoncé le préfixe via ce fournisseur, par tranche de ${body.bucket_hours} h${asn ? ` — origine AS${asn}` : ""}. Le fournisseur amont est le voisin de l'origine sur le chemin, côté collecteur ; les chemins d'un seul AS n'en ont pas et sont ignorés. Un pair peut changer de fournisseur : il compte alors dans les deux tranches.`}
            />
          );
        }}
      </AsyncBlock>
    </section>
  );
}
