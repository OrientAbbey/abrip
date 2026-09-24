import { useState } from "react";
import { useApi, useTitle } from "../lib/useApi";
import type { CountryRow, Series } from "../lib/types";
import { AsyncBlock, EmptyState } from "../components/StateBlock";
import { PALETTE, TimeChart } from "../components/TimeChart";
import { countryLabel, dec, num, pct } from "../lib/format";

/** Barre de proportion en ligne : plus lisible qu'un chiffre nu dans un
 *  tableau où l'on compare des pays entre eux. */
/** Barre de proportion en ligne : plus lisible qu'un chiffre nu dans un
 *  tableau où l'on compare des pays entre eux. Par défaut, une valeur haute
 *  est mauvaise (dépendance, HHI) ; `invert` retourne l'échelle pour les
 *  métriques où une valeur haute est bonne (couverture). */
function Meter({ value, invert = false }: { value: number | null; invert?: boolean }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  const width = Math.max(2, Math.min(100, value * 100));
  const bad = invert ? value <= 0.2 : value >= 0.8;
  const warn = invert ? value <= 0.5 : value >= 0.5;
  const tone = bad ? "var(--crimson)" : warn ? "var(--amber)" : "var(--teal)";
  return (
    <span className="row" style={{ gap: "0.4rem", justifyContent: "flex-end" }}>
      <span className="mono">{dec(value, 2)}</span>
      <span
        aria-hidden="true"
        style={{
          width: "3.5rem",
          height: "0.4rem",
          background: "var(--paper-sunk)",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <span style={{ display: "block", width: `${width}%`, height: "100%", background: tone }} />
      </span>
    </span>
  );
}

export default function Countries() {
  useTitle("Pays");
  const countries = useApi<CountryRow[]>("/countries");
  const [selected, setSelected] = useState<string | null>(null);
  const series = useApi<Series>(selected ? "/metrics/countries" : null, { country: selected });

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Pays</h1>
        <p>
          Indicateurs agrégés par pays d'allocation AFRINIC. La dépendance au transit mesure la part
          des AS du pays dont tout le trafic entrant passe par un seul fournisseur : c'est un
          indicateur de fragilité structurelle, pas de qualité de service.
        </p>
      </div>

      <AsyncBlock state={countries} rows={6}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState title="Aucune métrique pays disponible">
              <p>Lancez le calcul des métriques pour alimenter cette page.</p>
            </EmptyState>
          ) : (
            <>
              <section className="card">
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Pays</th>
                        <th className="num">AS observés</th>
                        <th className="num">Préfixes visibles</th>
                        <th className="num">Fournisseurs (moy.)</th>
                        <th className="num">HHI transit</th>
                        <th className="num">Dépendance</th>
                        <th className="num">Visibilité</th>
                        <th className="num">Couverture obs.</th>
                        <th className="num">Couverture ROA</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((c) => (
                        <tr key={c.country_iso2}>
                          <td>
                            {countryLabel(c.country_iso2)}{" "}
                            <span className="muted mono">{c.country_iso2}</span>
                          </td>
                          <td className="num mono">{num(c.asns_observed)}</td>
                          <td className="num mono">{num(c.prefixes_visible)}</td>
                          <td className="num mono">{dec(c.avg_upstream_count, 1)}</td>
                          <td className="num">
                            <Meter value={c.hhi_transit} />
                          </td>
                          <td className="num">
                            <Meter value={c.transit_dependency_ratio} />
                          </td>
                          <td className="num mono">{pct(c.avg_visibility)}</td>
                          <td className="num">
                            <Meter value={c.coverage_ratio} invert />
                          </td>
                          <td className="num">
                            <Meter value={c.rpki_coverage_ratio} invert />
                          </td>
                          <td>
                            <button onClick={() => setSelected(c.country_iso2)}>tendance</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="card-note">
                  Ces chiffres ne portent que sur les AS effectivement vus depuis les collecteurs.
                  Un pays dont le trafic reste local et ne remonte à aucun collecteur sera
                  sous-représenté. La couverture observationnelle indique la part des AS alloués au
                  pays réellement vus ici — un chiffre bas relativise tous les autres indicateurs de
                  la ligne. La couverture ROA indique la part des préfixes annoncés par ce pays
                  couverte par une autorisation RPKI valide ; un chiffre bas ne signale rien
                  d'anormal, seulement l'adoption encore partielle de RPKI dans la région.
                </p>
              </section>

              {selected && (
                <section className="card">
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <h2>Tendance — {countryLabel(selected)}</h2>
                    <button onClick={() => setSelected(null)}>fermer</button>
                  </div>
                  <AsyncBlock state={series} rows={3}>
                    {(data) => (
                      <TimeChart
                        points={data.points}
                        height={220}
                        yDomain={[0, 1]}
                        valueFormat={(v) => dec(v, 2)}
                        series={[
                          {
                            key: "transit_dependency_ratio",
                            label: "Dépendance au transit",
                            color: PALETTE.crimson,
                          },
                          { key: "hhi_transit", label: "HHI moyen", color: PALETTE.amber },
                          { key: "visibility", label: "Visibilité moyenne", color: PALETTE.teal },
                        ]}
                      />
                    )}
                  </AsyncBlock>
                </section>
              )}
            </>
          )
        }
      </AsyncBlock>
    </div>
  );
}
