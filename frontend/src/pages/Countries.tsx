import { Link } from "react-router-dom";
import { useApi, useTitle } from "../lib/useApi";
import type { CountryRow } from "../lib/types";
import { AsyncBlock, EmptyState } from "../components/StateBlock";
import { Glossary, Term } from "../components/Term";
import { countryLabel, dec, num, pct } from "../lib/format";

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

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Pays</h1>
        <p>
          Indicateurs agrégés par pays d'allocation AFRINIC. Ils décrivent la fragilité structurelle
          du routage d'un pays — de qui il dépend pour sortir sur Internet, et dans quelle mesure on
          le voit — pas la qualité de service que ses utilisateurs en perçoivent. Survolez un
          en-tête pour sa définition, ou lisez le glossaire en bas de page.
        </p>
      </div>

      <AsyncBlock state={countries} rows={6}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState title="Aucune métrique pays disponible">
              <p>Lancez le calcul des métriques pour alimenter cette page.</p>
            </EmptyState>
          ) : (
            <section className="card">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Pays</th>
                      <th className="num"><Term k="asnsObserved">AS</Term></th>
                      <th className="num"><Term k="prefixesVisible">Préfixes</Term></th>
                      <th className="num"><Term k="upstreams">Fournisseurs</Term></th>
                      <th className="num"><Term k="hhi">Concentration</Term></th>
                      <th className="num"><Term k="dependency">Dépendance</Term></th>
                      <th className="num"><Term k="visibility" /></th>
                      <th className="num"><Term k="coverage">Couv. obs.</Term></th>
                      <th className="num"><Term k="roa">Couv. ROA</Term></th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c) => (
                      <tr key={c.country_iso2}>
                        <td>
                          <Link to={`/countries/${c.country_iso2}`}>{countryLabel(c.country_iso2)}</Link>{" "}
                          <span className="muted mono">{c.country_iso2}</span>
                        </td>
                        <td className="num mono">{num(c.asns_observed)}</td>
                        <td className="num mono">{num(c.prefixes_visible)}</td>
                        <td className="num mono">{dec(c.avg_upstream_count, 1)}</td>
                        <td className="num"><Meter value={c.hhi_transit} /></td>
                        <td className="num"><Meter value={c.transit_dependency_ratio} /></td>
                        <td className="num mono">{pct(c.avg_visibility)}</td>
                        <td className="num"><Meter value={c.coverage_ratio} invert /></td>
                        <td className="num"><Meter value={c.rpki_coverage_ratio} invert /></td>
                        <td>
                          <Link to={`/countries/${c.country_iso2}`}>détail</Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="card-note">
                Ces chiffres ne portent que sur les AS effectivement vus depuis les collecteurs. Un
                pays dont le trafic reste local et ne remonte à aucun collecteur sera
                sous-représenté — la couverture d'observation indique de combien.
              </p>
            </section>
          )
        }
      </AsyncBlock>

      <section className="card">
        <h2>Glossaire</h2>
        <Glossary
          keys={["hhi", "dependency", "visibility", "upstreams", "coverage", "roa", "asnsObserved", "prefixesVisible"]}
        />
      </section>
    </div>
  );
}
