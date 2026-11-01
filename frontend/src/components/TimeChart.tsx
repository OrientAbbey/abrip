/** Graphiques temporels, au-dessus de Recharts.
 *
 * Toute la configuration visuelle est centralisée ici : les pages décrivent
 * des séries (clé, libellé, couleur, forme) et ne touchent jamais à Recharts
 * directement. Changer de bibliothèque ne toucherait donc que ce fichier.
 *
 * Deux conventions valent d'être dites :
 *   - les horodatages de la plateforme sont en UTC et restent affichés en UTC,
 *     parce qu'un incident BGP se raconte dans le fuseau des collecteurs, pas
 *     dans celui du navigateur ;
 *   - les axes sont numériques (`type="number"`, échelle temps) et non
 *     catégoriels, sinon des points espacés irrégulièrement seraient dessinés
 *     comme s'ils étaient réguliers.
 */

import {
  Area,
  Bar,
  Brush,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TimePoint } from "../lib/types";

export const PALETTE = {
  ink: "#1d3b52",
  teal: "#1f6f6a",
  amber: "#b8730f",
  crimson: "#9d2f33",
  slate: "#63819a",
};

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
  kind?: "line" | "bar" | "area";
  /** Épaisseur du trait pour les courbes ; ignoré pour les barres. */
  width?: number;
  dashed?: boolean;
}

interface Props {
  points: TimePoint[];
  series: ChartSeries[];
  height?: number;
  /** Instants à souligner : fenêtre d'un événement, date d'un snapshot… */
  markers?: Array<{ ts: string; label: string }>;
  yDomain?: [number | "auto", number | "auto"];
  valueFormat?: (value: number) => string;
  note?: string;
  stacked?: boolean;
  /** Affiche une poignée de sélection sous le graphique. `onBrush` reçoit les
   *  instants (ms epoch) de début et de fin de la sélection : c'est ce qui
   *  permet à un graphique de piloter le tableau placé en dessous. */
  brush?: boolean;
  onBrush?: (fromMs: number, toMs: number) => void;
  /** Courbe en escalier : pour des comptages entiers, un lissage inventerait
   *  des valeurs intermédiaires (« 1,5 voisin ») qui n'existent pas. */
  step?: boolean;
  /** Axe et infobulle en jours (sans l'heure), pour des points journaliers. */
  daily?: boolean;
}

const AXIS_STYLE = { fill: "#63819a", fontSize: 11, fontFamily: "ui-monospace, Menlo, monospace" };

const fmtTick = (value: number): string =>
  new Date(value).toISOString().slice(5, 16).replace("T", " ");

const fmtFull = (value: number): string =>
  `${new Date(value).toISOString().slice(0, 16).replace("T", " ")} UTC`;

// Données journalières : l'heure (toujours 00:00) n'est que du bruit.
const fmtDayTick = (value: number): string => new Date(value).toISOString().slice(5, 10);
const fmtDayFull = (value: number): string => new Date(value).toISOString().slice(0, 10);

export function TimeChart({
  points,
  series,
  height = 220,
  markers = [],
  yDomain = ["auto", "auto"],
  valueFormat = (v) => new Intl.NumberFormat("fr-FR").format(Math.round(v * 1000) / 1000),
  note,
  stacked = false,
  brush = false,
  onBrush,
  step = false,
  daily = false,
}: Props) {
  const tickFmt = daily ? fmtDayTick : fmtTick;
  const fullFmt = daily ? fmtDayFull : fmtFull;
  const curve = step ? "stepAfter" : "monotone";
  if (points.length === 0) {
    return <p className="muted">Pas de point à afficher sur cette fenêtre.</p>;
  }

  const rows = points.map((p) => ({ t: new Date(p.ts).getTime(), ...p.values }));
  const labels = Object.fromEntries(series.map((s) => [s.key, s.label]));

  return (
    <figure style={{ margin: 0 }}>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#e6eae6" vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={tickFmt}
            tick={AXIS_STYLE}
            stroke="#cfd8d4"
            minTickGap={48}
          />
          <YAxis
            domain={yDomain}
            tickFormatter={valueFormat}
            tick={AXIS_STYLE}
            stroke="#cfd8d4"
            width={56}
          />
          <Tooltip
            labelFormatter={(value) => fullFmt(Number(value))}
            formatter={(value, name) => [
              typeof value === "number" ? valueFormat(value) : String(value),
              labels[String(name)] ?? String(name),
            ]}
            contentStyle={{
              background: "#fbfcfa",
              border: "1px solid #cfd8d4",
              borderRadius: 3,
              fontSize: 12,
              fontFamily: "system-ui, sans-serif",
            }}
            cursor={{ stroke: "#92a9bc", strokeDasharray: "3 3" }}
          />
          <Legend
            verticalAlign="bottom"
            height={26}
            formatter={(name) => (
              <span style={{ color: "#3f6079", fontSize: 12 }}>
                {labels[String(name)] ?? String(name)}
              </span>
            )}
          />
          {markers.map((m, i) => (
            <ReferenceLine
              key={i}
              x={new Date(m.ts).getTime()}
              stroke={PALETTE.crimson}
              strokeDasharray="4 3"
              label={{ value: m.label, position: "insideTopRight", fill: PALETTE.crimson, fontSize: 11 }}
            />
          ))}
          {series.map((s) => {
            if (s.kind === "bar") {
              return (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.key}
                  fill={s.color}
                  fillOpacity={0.75}
                  stackId={stacked ? "stack" : undefined}
                  isAnimationActive={false}
                />
              );
            }
            if (s.kind === "area") {
              return (
                <Area
                  key={s.key}
                  type={curve}
                  dataKey={s.key}
                  name={s.key}
                  stroke={s.color}
                  fill={s.color}
                  fillOpacity={0.14}
                  strokeWidth={s.width ?? 1.6}
                  isAnimationActive={false}
                />
              );
            }
            return (
              <Line
                key={s.key}
                type={curve}
                dataKey={s.key}
                name={s.key}
                stroke={s.color}
                strokeWidth={s.width ?? 1.6}
                strokeDasharray={s.dashed ? "5 3" : undefined}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            );
          })}
          {brush && rows.length > 1 && (
            <Brush
              dataKey="t"
              height={22}
              stroke="#63819a"
              travellerWidth={8}
              tickFormatter={(value) => tickFmt(Number(value))}
              onDragEnd={(range) => {
                const start = rows[range.startIndex ?? 0]?.t;
                const end = rows[range.endIndex ?? rows.length - 1]?.t;
                if (start !== undefined && end !== undefined && onBrush) onBrush(start, end);
              }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      {note && <figcaption className="card-note">{note}</figcaption>}
    </figure>
  );
}
