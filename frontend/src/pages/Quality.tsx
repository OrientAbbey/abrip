import { AsyncBlock } from "../components/StateBlock";
import { day, num } from "../lib/format";
import { useApi, useTitle } from "../lib/useApi";
import type { DataQuality } from "../lib/types";

/** État des données : ce qui est frais, ce qui couvre quoi, ce qui manque. */
export default function Quality() {
  useTitle("Qualité des données");
  const quality = useApi<DataQuality>("/quality");

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Qualité des données</h1>
        <p>
          Fraîcheur des sources d'ingestion, couverture des référentiels et collecteurs
          silencieux. Ces indicateurs décrivent les fichiers déjà présents : aucune donnée
          n'est recalculée ici.
        </p>
      </div>

      <AsyncBlock state={quality} rows={4}>
        {(data) => (
          <>
            <section className="card">
              <h2>Fraîcheur par source</h2>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Collecteur</th>
                      <th>Type</th>
                      <th className="num">Fichiers</th>
                      <th>Premier</th>
                      <th>Dernier</th>
                      <th className="num">Âge</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sources.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="muted">
                          Aucune ingestion journalisée.
                        </td>
                      </tr>
                    ) : (
                      data.sources.map((source) => (
                        <tr key={`${source.collector}-${source.file_type}`}>
                          <td className="mono">{source.collector}</td>
                          <td>{source.file_type}</td>
                          <td className="num mono">{num(source.files)}</td>
                          <td className="mono">{source.oldest ? day(source.oldest) : "—"}</td>
                          <td className="mono">{source.newest ? day(source.newest) : "—"}</td>
                          <td className="num mono">
                            {source.age_days === null ? "—" : `${source.age_days} j`}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <div className="grid cols-2">
              <section className="card">
                <h2>Couverture par pays</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Pays</th>
                        <th className="num">AS référencés</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.countries.map((country) => (
                        <tr key={country.country_iso2}>
                          <td className="mono">{country.country_iso2}</td>
                          <td className="num mono">{num(country.asns)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="card">
                <h2>Référentiel RPKI</h2>
                <p>
                  <strong>{num(data.roa.roas)}</strong> ROA publiés, couvrant{" "}
                  <strong>{num(data.roa.prefixes)}</strong> préfixes distincts.
                </p>
                <p className="card-note">
                  Le détail par préfixe est disponible sur chaque fiche : la validation
                  confronte l'origine observée aux autorisations du ROA.
                </p>
              </section>
            </div>

            <section className="card">
              <h2>Collecteurs silencieux</h2>
              <p className="card-note">Aucune archive ingérée depuis plus de deux jours.</p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Collecteur</th>
                      <th>Activé</th>
                      <th>Dernier fichier</th>
                      <th className="num">Âge</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.silent_collectors.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="muted">
                          Aucun collecteur silencieux.
                        </td>
                      </tr>
                    ) : (
                      data.silent_collectors.map((collector) => (
                        <tr key={collector.name}>
                          <td className="mono">{collector.name}</td>
                          <td>{collector.enabled ? "oui" : "non"}</td>
                          <td className="mono">
                            {collector.last_file_ts ? day(collector.last_file_ts) : "—"}
                          </td>
                          <td className="num mono">
                            {collector.age_days === null ? "—" : `${collector.age_days} j`}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </AsyncBlock>
    </div>
  );
}
