import { useApi, useTitle } from "../lib/useApi";
import type { Health } from "../lib/types";
import { AsyncBlock } from "../components/StateBlock";
import { dt, num } from "../lib/format";

const DETECTORS: Array<[string, string]> = [
  [
    "Origines multiples (MOAS)",
    "Un même préfixe annoncé par plusieurs AS d'origine sur une fenêtre courte. Légitime en multi-homing, suspect quand l'origine nouvelle apparaît brutalement et contredit un ROA.",
  ],
  [
    "Annonce de sous-préfixe",
    "Un bloc plus spécifique annoncé par un AS différent de celui du bloc couvrant. C'est le détournement le plus efficace, car le plus spécifique gagne toujours.",
  ],
  [
    "Invalide RPKI",
    "L'annonce contredit un ROA publié, soit par l'origine, soit par la longueur du préfixe. Preuve cryptographique, pas heuristique.",
  ],
  [
    "Violation valley-free",
    "Le chemin d'AS remonte vers un fournisseur après être redescendu, ce qui trahit une fuite de routes. Repose sur les relations inférées par CAIDA.",
  ],
  [
    "Pic d'instabilité",
    "Volume de messages très supérieur à la référence du préfixe, mesuré par un score z robuste (médiane et écart absolu médian) pour résister aux valeurs extrêmes.",
  ],
  [
    "Chute de visibilité",
    "Le préfixe disparaît d'une part significative des points de vue entre deux instantanés RIB.",
  ],
  [
    "Bogon",
    "Annonce d'un préfixe réservé ou d'un AS privé, qui ne devrait jamais circuler dans la table globale.",
  ],
];

export default function About() {
  useTitle("À propos");
  const health = useApi<Health>("/health");

  return (
    <div className="stack">
      <div className="page-head">
        <h1>À propos</h1>
        <p>
          ABRIP observe le routage inter-domaines africain à partir de données publiques, et tente
          d'expliquer ce qu'il montre plutôt que d'aligner des alertes.
        </p>
      </div>

      <section className="card prose">
        <h2>Ce que la plateforme mesure</h2>
        <p>
          Les collecteurs BGP enregistrent les annonces reçues de leurs voisins. En les recoupant
          avec les allocations AFRINIC, les autorisations RPKI et les relations inter-AS inférées
          par CAIDA, on peut suivre trois choses : la visibilité d'un préfixe depuis différents
          points du réseau, la concentration du transit d'un AS ou d'un pays, et les écarts entre ce
          qui est annoncé et ce qui est autorisé.
        </p>
        <p>
          Les collecteurs africains donnent la vue locale ; un collecteur extérieur sert de
          référence. L'écart entre les deux est souvent plus parlant que chaque courbe prise
          séparément.
        </p>
      </section>

      <section className="card">
        <h2>Les sept détecteurs</h2>
        <dl className="kv">
          {DETECTORS.map(([name, description]) => (
            <div key={name} style={{ display: "contents" }}>
              <dt style={{ color: "var(--ink-700)", fontWeight: 600 }}>{name}</dt>
              <dd>{description}</dd>
            </div>
          ))}
        </dl>
        <p className="card-note">
          Chaque détecteur produit un score entre 0 et 1, une confiance fondée sur le nombre de
          points de vue concordants, et les observations qui l'ont déclenché. Quand plusieurs
          détecteurs pointent le même préfixe dans la même fenêtre, ils sont regroupés en incident.
        </p>
      </section>

      <section className="card prose">
        <h2>Ce que la plateforme ne mesure pas</h2>
        <ul>
          <li>
            <strong>Le trafic.</strong> BGP est le plan de contrôle. Une route annoncée ne dit rien
            du volume qui l'emprunte, ni de la latence, ni de la qualité perçue.
          </li>
          <li>
            <strong>L'ensemble du routage.</strong> On ne voit que ce que les peers des collecteurs
            veulent bien annoncer. Un préfixe absent d'ici peut être parfaitement joignable.
          </li>
          <li>
            <strong>La vérité sur les relations commerciales.</strong> Les relations CAIDA sont
            inférées à partir des chemins observés, pas issues de contrats.
          </li>
          <li>
            <strong>Une conclusion d'attaque.</strong> Un événement signale une anomalie de routage.
            Distinguer l'erreur de configuration du détournement délibéré demande un contexte que
            les données publiques n'apportent pas.
          </li>
        </ul>
      </section>

      <section className="card">
        <h2>État des données</h2>
        <AsyncBlock state={health} rows={4}>
          {(data) => (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Couche</th>
                      <th>État</th>
                      <th className="num">Lignes</th>
                      <th>Plus ancienne</th>
                      <th>Plus récente</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.layers.map((layer) => (
                      <tr key={layer.name}>
                        <td className="mono">{layer.name}</td>
                        <td>
                          <span className={`badge ${layer.present ? "info" : "watch"}`}>
                            {layer.present ? "présente" : "absente"}
                          </span>
                        </td>
                        <td className="num mono">{num(layer.rows)}</td>
                        <td className="mono">{layer.oldest ? dt(layer.oldest) : "—"}</td>
                        <td className="mono">{layer.newest ? dt(layer.newest) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="card-note">
                Version {data.version} · état généré le {dt(data.generated_at)}
              </p>
            </>
          )}
        </AsyncBlock>
      </section>

      <section className="card prose">
        <h2>Sources</h2>
        <ul>
          <li>RouteViews et RIPE RIS — archives MRT des collecteurs, dont ceux hébergés en Afrique.</li>
          <li>AFRINIC et les autres RIR — fichiers <code>delegated-extended</code> pour l'attribution pays.</li>
          <li>RPKI — jeu de ROA validés, pour la vérification d'origine.</li>
          <li>CAIDA AS-relationships et AS2Org — relations inter-AS inférées et regroupement organisationnel.</li>
          <li>PeeringDB — présence aux points d'échange.</li>
        </ul>
        <p className="muted">
          Toutes les sources sont publiques et horodatées : une analyse peut être rejouée à
          l'identique à partir des mêmes instantanés.
        </p>
      </section>
    </div>
  );
}
