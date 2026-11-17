# Comparaison backend — `dev_cl` vs `dev_cl5`

**Date :** 2026-11-17  
**Branches comparées :** `dev_cl` au commit de fusion `6ff61d6` (la branche de travail `feat/ui-review-followups` ajoute quelques commits UI et l'endpoint additif `/prefixes/facets`, signalés ci-dessous) et `dev_cl5` au commit `12fd25a`.  
**Méthode :** revue statique des deux arbres (`src/abrip/**`, `pyproject.toml`, `docs/`, `.github/workflows/ci.yml`), complétée par des mesures ponctuelles sur les deux serveurs locaux de démonstration (ports 8000 et 8001) et par la régénération des schémas OpenAPI via `create_app().openapi()`. Le previous rapport `comparaison-dev_cl-dev_cl5.md` annonçait 54/53 routes : ce chiffre n'est pas reproductible dans l'état actuel et **ne doit pas être repris** ; le comptage ci-dessous est celui des opérations effectivement présentes.

> Note technique : `GET /openapi.json` sur les serveurs locaux renvoie le HTML de repli SPA (les deux branches servent le frontend sur toutes les routes inconnues). Le schéma a donc été généré en processus avec `app.openapi()`, pas via HTTP.

## Indicateurs généraux

| Indicateur | `dev_cl` | `dev_cl5` |
|---|---|---|
| Fichiers Python (`src`) | 50 | 49 |
| Lignes Python | 9 526 | 8 643 |
| Fichiers TypeScript (`frontend/src`) | 38 | 29 |
| Lignes TypeScript | 5 789 | 4 028 |
| Fichiers de tests Python | 26 | 14 |
| Opérations OpenAPI | **37** | **33** |
| `response_model=` dans les routeurs | 18 | 12 (aucun dans `topology.py`) |
| Routeur principal | `asn_explorer.py` (983 l.) + `propagation.py` (518 l.) | `topology.py` (909 l., monolithe) |
| Tables journalières | `analytics/daily.py` (164 l.) | absent |
| Historique de référence | absent | `reference/history.py` (113 l.) |
| Scripts de benchmark | `scripts/bench/` | absent |
| `docs/performances.md` | présent | absent |

## 1. Architecture et simplicité

- `dev_cl` sépare l'exploration (`api/routers/asn_explorer.py`) de la propagation (`propagation.py`) ; `dev_cl5` fusionne exploration et topologie dans un seul routeur `topology.py`. Le découpage de `dev_cl` est plus lisible et plus facile à faire évoluer.
- `analytics/replay.py` et `reference/relationships.py` (avec `RelationshipIndex`) sont **identiques octet pour octet** dans les deux branches : ce ne sont pas des apports de `dev_cl5`.
- `dev_cl` typage davantage ses contrats : 18 `response_model=` contre 12, et **aucun** dans le routeur `topology.py` de `dev_cl5` (retours `dict[str, Any]`).
- Les ajouts de `dev_cl` sont globalement **additifs** ; ceux de `dev_cl5` sont souvent **substitutifs** et cassants (voir §4).
- Points faibles propres à `dev_cl` : la classification New/Left/Unstable est dupliquée (règle SQL dans la requête de changements `asn_explorer.py:260-272`, puis `_presence_status`/`_add_statuses`/`_runs` en Python `:763-813`). `dev_cl5` centralise cette règle dans `classify_presence` (`reference/history.py:79-95`) — l'abstraction la plus propre est paradoxalement dans la branche à supprimer.
- Correctibilité : `dev_cl5` attribue l'origine MOAS de façon arbitraire (`origin_of[prefix]` écrasé ligne par ligne, `topology.py:192-195`) et compare `ts <= date_to` à minuit (`:158-160`), ce qui vide une série d'un seul jour. `dev_cl` utilise `ts < d1 + INTERVAL 1 DAY` (`asn_explorer.py:148,250,473`). Ces défauts ont été reproduits dans la revue précédente.

## 2. Performance

**Conception.** `dev_cl` a deux optimisations structurantes absentes de `dev_cl5` :

1. **Tri des partitions** par `(prefix, ts)` à l'écriture (`storage/parquet.py:180-223`, `etl/curate.py:128-134`, commande `abrip etl compact`), qui permet à DuckDB de sauter les groupes via les statistiques min/max. Mesures documentées (`docs/performances.md:54-56`) à 10 M lignes : fiche préfixe 1,1 → 0,3 s, graphe 0,7 → 0,25 s, amont 1,7 → 0,4 s, rejeu 1,6 → 0,7 s.
2. **Tables journalières** `daily_prefix_origin` / `daily_adjacency` (`analytics/daily.py`), avec garde de fraîcheur et repli exact sur le brut. À 50 M lignes (`docs/performances.md:25-45`) : préfixes d'un AS 0,06 s au lieu de 3,3 s, voisins 0,07 s au lieu de 5,7 s, liste des préfixes 0,11 s au lieu de 4,8 s ; pic mémoire 315 Mo. Coût de calcul : 55 s, 252 Mo, 0,9 Mo sur disque (`:92-93`).

`dev_cl5` relit `bgp_elements` pour ces mêmes endpoints (`topology.py:151-184,233-267`), matérialise toutes les paires/jours en Python, ne pagine pas les `items` de topologie (`:359-374,423-439,530-550,578-599`) et ne plafonne pas le nombre de chemins de rejeu (`:828-877`) là où `dev_cl` borne la payload (500 chemins, 3 000 chemins / 400 000 références, `propagation.py:264-268,360-363`).

**Mesures locales indicatives** (démo ~27 000 éléments, médianes après échauffement, bruit important — à ne pas extrapoler telles quelles) :

| Endpoint | `dev_cl` | `dev_cl5` |
|---|---|---|
| `GET /api/overview` | ~15 ms | ~11 ms |
| `GET /api/asns/37100` | ~1 045 ms | ~1 469 ms |
| `GET /api/asns/37100/prefixes/timeseries` | ~784 ms | ~607 ms |
| `GET /api/asns/37100/prefixes` vs `/prefixes/changes` | ~667 ms | ~1 819 ms |

Ces ordres de grandeur confirment surtout que le jeu de démo est trop petit pour départager les deux ; les mesures à 1–50 M lignes de `dev_cl` restent la seule preuve de Passage à l'échelle disponible.

**Dettes communes :** relecture des référentiels à chaque requête via `pl.read_parquet`, une connexion DuckDB par appel `query()`, aucun ETag/`Cache-Control`/gzip, cache TTL 60 s utilisé seulement par `/overview`. `dev_cl` garde une dette propre : `_prefix_page` charge toutes les lignes avant découpage en Python (`asn_explorer.py:318-323`) et les endpoints par préfixe restent sur le brut (rejeu chaud 2,47 s à 50 M, `docs/performances.md:118-125`).

**Verdict performance :** `dev_cl` est nettement plus scalable ; `dev_cl5` est plus court mais paie chaque vue par un scan brut et une matérialisation non paginée.

## 3. Sécurité

Les deux branches partagent les mêmes garde-fous et présentent un profil défensif très proche :

- Validation FastAPI/Pydantic identique : `limit` `[1,500]`, `offset ≥ 0`, regex sur `ip_version`, `status`, `relation`, `sort`, `window`, bornes numériques sur `min_score`, `max_paths`, `min_observations`, `step`, `max_frames`, `bucket_hours` ; dates parsées par Pydantic.
- SQL paramétré partout (`con.execute(sql, params)`) ; les f-strings n'assemblent que des identifiants issus d'une table blanche (`data.table()`) ou des fragments fixes. Aucune injection identifiée ; aucun endpoint d'écriture.
- Correctif C1 du « path traversal » SPA présent et testé des deux côtés (`main.py:147-153` / `main.py:141-147`, `tests/test_api.py:158` / `:392`).
- CORS restreint à `http://localhost:5173`, `allow_credentials=False` ; erreurs sans stack trace ni chemin interne ; aucun secret codé en dur ; image Docker non root.
- Frontend : `URLSearchParams` pour l'encodage, aucun `dangerouslySetInnerHTML`/`innerHTML`/`eval` ; noms de fichiers d'export assainis et cellules CSV échappées dans `dev_cl`.

**Différentiel matériel :** `dev_cl` protège le répertoire de données de démonstration (marqueur `.abrip-demo.json`, `dataset_state()`, `_refuse_if_not_demo()`, `demo check`, `demo bootstrap --force`) ; `dev_cl5` n'a aucun de ces garde-fous (`demo/bootstrap.py:82`, `cli.py:313-331`) et peut écraser silencieusement un vrai jeu de données. C'est le seul avantage de sécurité net de `dev_cl`.

**Lacune commune :** `verify_api_key()` est défini mais jamais monté comme dépendance de routeur (`deps.py:151` / `:171`). Si la clé API doit protéger le service, c'est un correctif à faire indépendamment du choix de branche.

**Dépendances :** pins identiques (React/Router, recharts, Vite, TypeScript, polars/duckdb/pyarrow, FastAPI, Pydantic, etc.) ; `dev_cl` ajoute seulement `numpy<2.4`. Aucune sortie d'audit (`npm audit`/`pip-audit`) trouvée, donc aucune allégation de CVE ;faible reproductibilité Python due aux planchers `>=` des deux côtés.

## 4. Contrats API

Schémas générés en processus : **37 opérations** dans `dev_cl`, **33** dans `dev_cl5`, **23 communes**.

**Uniquement dans `dev_cl` (14) :** `/asns/names`, `/asns/{asn}/neighbours[/timeseries]/{neighbour}/history`, `/asns/{asn}/prefixes`, `/asns/{asn}/prefixes/facets` (nouveau), `/asns/{asn}/prefixes/{prefix}/roa-history`, `route-history`, `/countries/{iso2}/neighbours[/timeseries]`, `/countries/{iso2}/prefixes`, `/countries/{iso2}/prefixes/facets` (nouveau), `/countries/{iso2}/relationships`, `/prefixes/{prefix}/upstreams`.

**Uniquement dans `dev_cl5` (10) :** `/asns/{asn}/neighbors[/timeseries]/{neighbor}/history`, `/asns/{asn}/prefixes/changes`, `/countries/{iso2}/asns`, `/countries/{iso2}/neighbors[/timeseries]`, `/countries/{iso2}/prefixes/changes`, `/prefixes/{prefix}/roa-history`, `/prefixes/{prefix}/route-object-history`.

Les différences de nom (`neighbours` vs `neighbors`, `route-history` vs `route-object-history`, historiques ROA imbriqués sous l'AS vs à la racine) sont des **ruptures de contrat**, pas des ajouts. Aucun élément ne suggère qu'un consommateur dépende de la variante `dev_cl5`.

## 5. Apports backend exclusifs à `dev_cl5`

| Candidat | Statut | Verdict |
|---|---|---|
| `reference/history.py` — diff d'instantanés et `classify_presence` | **Vrai exclusif**, testé (`tests/test_reference.py:149-158`, `test_api.py:235,244`) | **Seul apport backend réellement unique.** Mérite un port ou un rejet explicite. |
| Historiques ROA/IRR *classés* (`change`, `first_seen`, `last_seen`) via `diff_entities` | **Vrai exclusif** (`topology.py:630-639,890-899`) | Valeur fonctionnelle réelle ; à porter avec le module ci-dessus si l'on veut remplacer `_history`. |
| Moteur de rejeu | Faux exclusif : fichier identique | Rien à transférer |
| `RelationshipIndex` | Faux exclusif : fichier identique | Rien à transférer |
| Codes CAIDA bruts | Hypothèse infirmée : `parse_as_rel` mappe dans les deux branches | Rien à préserver à ce titre |
| `topology.py` en bloc | Variante consolidée, non typée, avec les défauts §1 et §2 | À écarter |

## 6. Conclusion backend

`dev_cl` est en avance sur l'architecture, les contrats, la performance et la protection des données de démonstration. `dev_cl5` n'est pas une branche de remplacement : c'est une variante qui retranche des routes et des contrôles, avec des chemins de lecture moins scalables.

**Une seule réserve avant suppression :** le module `reference/history.py` et les endpoints d'historique ROA/IRR classés. Soit on les porte dans `dev_cl` (recommandé, ils résolvent la duplication de classification), soit on décide formellement de les écarter. Tout le reste peut être supprimé sans perte fonctionnelle identifiée.
