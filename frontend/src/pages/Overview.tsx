import { Link } from "react-router-dom";
import { useApi, useTitle } from "../lib/useApi";
import type { CollectorInfo, Overview as OverviewData, Series } from "../lib/types";
import { AsyncBlock } from "../components/StateBlock";
import { PALETTE, TimeChart } from "../components/TimeChart";
import { SeverityBadge } from "../components/Badges";
import { day, detectorLabel, num, pct } from "../lib/format";

export default function Overview() {
  useTitle("Vue d'ensemble");
  const overview = useApi<OverviewData>("/overview");
  const visibility = useApi<Series>("/metrics/visibility");
  const collectors = useApi<CollectorInfo[]>("/meta/collectors");

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Vue d'ensemble</h1>
        <p>
          État du routage observé depuis les collecteurs africains et une vue extérieure de
          référence. Les chiffres portent sur la fenêtre couverte par les données chargées, pas
          sur le temps réel.
        </p>
      </div>

      <AsyncBlock state={overview} rows={3}>
        {(data) => (
          <>
            <div className="grid cols-4">
              <div className="card stat">
                <span className="label">Préfixes suivis</span>
                <span className="value">{num(data.prefixes_tracked)}</span>
                <span className="hint">
                  {data.window_from ? `depuis le ${day(data.window_from)}` : ""}
                </span>
              </div>
              <div className="card stat">
                <span className="label">AS d'origine</span>
                <span className="value">{num(data.asns_tracked)}</span>
                <span className="hint">{num(data.countries_tracked)} pays représentés</span>
              </div>
              <div className="card stat">
                <span className="label">Visibilité médiane</span>
                <span className="value">{pct(data.median_visibility)}</span>
                <span className="hint">part des points de vue voyant le préfixe</span>
              </div>
              <div className="card stat">
                <span className="label">Événements</span>
                <span className="value">
                  {num(Object.values(data.events_by_severity).reduce((a, b) => a + b, 0))}
                </span>
                <span className="hint row" style={{ gap: "0.3rem" }}>
                  {Object.entries(data.events_by_severity).map(([sev, n]) => (
                    <span key={sev}>
                      <SeverityBadge severity={sev} /> {n}
                    </span>
                  ))}
                </span>
              </div>
            </div>

            <div className="grid cols-2">
              <section className="card">
                <h2>Préfixes les plus instables</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Préfixe</th>
                        <th className="num">Mises à jour</th>
                        <th className="num">Retraits</th>
                        <th className="num">Origines</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_unstable_prefixes.map((row) => {
                        const prefix = String(row.prefix);
                        return (
                          <tr key={prefix}>
                            <td>
                              <Link className="mono" to={`/prefixes/${encodeURIComponent(prefix)}`}>
                                {prefix}
                              </Link>
                            </td>
                            <td className="num mono">{num(Number(row.updates))}</td>
                            <td className="num mono">{num(Number(row.withdrawals))}</td>
                            <td className="num mono">{num(Number(row.origins))}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="card-note">
                  Instabilité mesurée en nombre de messages BGP, pas en impact sur le trafic : un
                  préfixe très bavard n'est pas forcément un préfixe en panne.
                </p>
              </section>

              <section className="card">
                <h2>Répartition par détecteur</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Détecteur</th>
                        <th className="num">Événements</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(data.events_by_detector)
                        .sort((a, b) => b[1] - a[1])
                        .map(([detector, n]) => (
                          <tr key={detector}>
                            <td>{detectorLabel(detector)}</td>
                            <td className="num mono">{num(n)}</td>
                            <td>
                              <Link to={`/events?detector=${detector}`}>voir</Link>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
                <p className="card-note">
                  Chaque événement porte ses preuves : aucune alerte n'est affichée sans les
                  observations qui la motivent.
                </p>
              </section>
            </div>
          </>
        )}
      </AsyncBlock>

      <section className="card">
        <h2>Visibilité moyenne des préfixes suivis</h2>
        <AsyncBlock state={visibility} rows={3}>
          {(series) => (
            <TimeChart
              points={series.points}
              height={220}
              yDomain={[0, 1]}
              valueFormat={(v) => `${Math.round(v * 100)}%`}
              series={[
                { key: "visibility_ratio", label: "Visibilité globale", color: PALETTE.ink },
                { key: "visibility_local", label: "Collecteurs africains", color: PALETTE.teal },
                { key: "visibility_external", label: "Vue extérieure", color: PALETTE.amber },
              ]}
            />
          )}
        </AsyncBlock>
        <p className="card-note">
          Un écart durable entre la courbe africaine et la vue extérieure signale une propagation
          asymétrique : le préfixe est vu ailleurs mais plus localement, ou l'inverse.
        </p>
      </section>

      <section className="card">
        <h2>Points d'observation</h2>
        <AsyncBlock state={collectors} rows={3}>
          {(rows) => (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Collecteur</th>
                    <th>Projet</th>
                    <th>Localisation</th>
                    <th>Rôle</th>
                    <th className="num">Fichiers</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.name}>
                      <td className="mono">{c.name}</td>
                      <td>{c.project}</td>
                      <td>{c.location}</td>
                      <td>
                        <span className="tag">
                          {c.role === "local" ? "africain" : "vue extérieure"}
                        </span>
                      </td>
                      <td className="num mono">{num(c.files_ingested)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AsyncBlock>
      </section>
    </div>
  );
}
