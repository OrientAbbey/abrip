# Suivi détaillé des modifications ABRIP

Ce fichier est le carnet d’exécution des améliorations listées dans `docs/ameliorations-proposees.md`. Une case n’est cochée qu’après vérification réelle ; les points non faits restent ouverts avec leur raison.

## Lot 1 — Correctifs fonctionnels et fiabilité — **terminé**

### 1.1 Historique des métriques
- [x] Schémas et colonnes temporelles confirmés : toutes les métriques portent `window_start`, sauf `metric_visibility` (`snapshot_ts`), d’où la détection automatique de la colonne de temps.
- [x] Disposition retenue : `data/analytics/<métrique>/date=AAAA-MM-JJ/part-*.parquet`, comme `analytics/daily.py`.
- [x] Écriture d’une partition par jour : `_persist` (`src/abrip/analytics/metrics.py`) regroupe la trame par date UTC avant écriture et ne touche qu’aux jours présents dans la trame.
- [x] Idempotence conservée : `write_frame` remplace atomiquement la partition du jour ; une trame vide renvoie `0` sans rien écrire.
- [x] Anciennes tables plates migrées : les fichiers à la racine sont relus, répartis par jour, réécrits en partitions, puis supprimés seulement après succès.
- [x] Lecture API adaptée : `src/abrip/api/deps.py` utilise `metric_*/**/*.parquet` (le motif couvre aussi d’éventuels anciens fichiers plats). `DataAccess.exists` utilisait déjà `rglob`.
- [x] Test de régression : `tests/test_metrics_persistence.py` (calcul multi-jours, recalcul d’un seul jour, migration d’une table plate, motif API).
- [x] Catalogue vérifié : `register_partition` fait un `ON CONFLICT (partition_key) DO UPDATE`, donc une réécriture de jour ne duplique pas la ligne.
- [x] Démonstration et détection vérifiées : `abrip demo bootstrap --force` puis `abrip demo verify` (rappel 1.0, 5/5) ; les métriques sont bien écrites en 7 partitions journalières.

### 1.2 Pagination de la liste des AS
- [x] `frontend/src/pages/AsnList.tsx` ne supprime plus `offset` lors des changements de page.
- [x] Logique extraite dans `frontend/src/lib/searchParams.ts` : `withFilter` réinitialise la pagination, `withOffset` la conserve.
- [x] `Prefixes.tsx` aligné sur la même aide, pour que les deux listes ne divergent plus.
- [x] Tests Vitest : `frontend/src/lib/searchParams.test.ts` (page suivante, retour, remise à zéro après filtre, vidage de filtre).
- [x] `npm test` (11 tests), `npm run typecheck` et `npm run build` passent.

### 1.3 Horodatages UTC
- [x] Sémantique établie : DuckDB et les générateurs produisent des datetimes **naïfs** exprimés en UTC.
- [x] Sérialisation explicite des schémas typés : `ApiModel` + `_serialize_datetimes` (`src/abrip/api/schemas.py`) ajoutent `Z` (ou ramènent un offset à UTC), y compris dans les objets imbriqués et `details`/`last_run`.
- [x] Endpoints typés vérifiés : `Health`, `LayerStatus`, `Series`, `TimePoint`, `EventOut`, `Page`.
- [x] Frontend : `parseUtc` (`frontend/src/lib/format.ts`) traite une valeur naïve comme UTC, une date seule comme minuit UTC, et respecte un `Z`/offset explicite.
- [x] Composants alignés : `TimeChart`, `EventDetail` et `PropagationReplay` utilisent `parseUtc` au lieu d’un `new Date(...)` local.
- [x] Tests backend : `tests/test_schemas.py` (naïf, offset non UTC, imbrication, `last_run`).
- [x] Tests frontend : `frontend/src/lib/format.test.ts`.
- [x] Limite connue et acceptée : les quelques endpoints qui renvoient des `dict` ad hoc (statistiques de préfixe, séries DuckDB) gardent des datetimes sans suffixe ; le frontend les interprète désormais comme UTC. Un passage systématique par des schémas typés reste souhaitable (voir section 3).
- [x] `npm run typecheck`, `npm test` et la suite API passent.

### 1.4 Pagination du broker BGPKIT
- [x] Forme de la réponse vérifiée : `{"data": [...], "total": ...}` ; `page` et `page_size` sont des paramètres documentés (maximum 1 000 par page).
- [x] `_search_pages` (`src/abrip/ingestion/broker.py`) parcourt les pages jusqu’à épuisement (`total` atteint, page incomplète ou vide), avec `MAX_PAGES` comme garde-fou.
- [x] Filtres, retries (`_query`), repli archive et tri final conservés.
- [x] Échec en cours de pagination : l’exception remonte à `search`, qui journalise et bascule sur `build_archive_urls` — aucune récupération partielle silencieuse.
- [x] Doublons d’URL dédupliqués entre pages.
- [x] Tests : `tests/test_broker.py` (pages complètes avec `total`, dernière page incomplète sans `total`, doublons).
- [x] Suite d’ingestion ciblée et tests complets passent.

### 1.5 Curation à mémoire bornée (RIB et PCH)
- [x] `_curate_rib` (`src/abrip/etl/curate.py`) écrit via `ParquetBatchWriter` dans un dossier temporaire puis remplace la partition : plus d’accumulation en mémoire.
- [x] Schéma, noms de partitions, horodatages, compteur et enregistrement catalogue préservés.
- [x] Idempotence conservée : remplacement atomique, suppression du temporaire si aucune ligne.
- [x] `PchTextDumpParser.parse` (`src/abrip/etl/pch_parser.py`) lit l’en-tête dans les 20 premières lignes puis itère le fichier en flux (`chain`), sans `readlines()`.
- [x] Tests : `tests/test_curate_rib.py` (plusieurs lots, remplacement) et `tests/test_pch_parser.py` (relevé de 5 000 routes consommé en générateur, préambule non interprété, fichier sans en-tête).
- [x] `abrip demo verify` toujours à 5/5 après recuration complète.

### 1.6 Validation RPKI par couples distincts
- [x] `compute_rpki_coverage` (`src/abrip/analytics/metrics.py`) appelle `RpkiValidator.validate_frame`.
- [x] Statuts vérifiés : `valid`, `invalid`, `not-found` ; sans ROA, tout est `not-found`.
- [x] Agrégations pays et compteurs de préfixes distincts inchangés.
- [x] Tests : `tests/test_metrics_rpki.py` (annonces répétées, MOAS, préfixe sans ROA, absence de ROA) avec équivalence explicite vis-à-vis de la validation ligne à ligne.
- [x] Pas de benchmark séparé : la démonstration complète sert de mesure de bout en bout (bootstrap + verify).

### 1.7 Stabilité des agrégats multi-partitions (découvert pendant la vérification)
- [x] Cause identifiée : `any_value(primary_upstream)` choisissait une ligne arbitraire parmi les jours de `metric_upstream`, et les moyennes de ratios sommées sur plusieurs fichiers pouvaient varier d’un ULP. Les tests d’équivalence des tables journalières comparaient deux appels identiques et échouaient par intermittence (8 tests).
- [x] `explore.py` : `arg_max(..., window_start)` pour `upstream_count` et `primary_upstream` (valeur du jour le plus récent, déterministe).
- [x] Ratios agrégés arrondis à 6 décimales dans les réponses (`/prefixes`, `/countries`, séries de visibilité), bien au-delà de la précision affichée.
- [x] Vérification : `tests/test_tables_journalieres.py` passe (316 tests), et les listes AS/préfixes restent stables sur trois exécutions consécutives.

## Lot 2 — Garde-fous de qualité

### 2.1 Formatage Ruff en CI — **fait**
- [x] `.github/workflows/ci.yml` exécute `ruff format --check src tests`.
- [x] `uv run --locked ruff format --check src tests` passe localement (84 fichiers) et `ruff check src tests` aussi.
- [x] Le workflow YAML a été validé syntaxiquement (parsing `yaml.safe_load`).

### 2.2 Couverture Python — **fait**
- [x] Couverture mesurée sur la suite complète : **81,03 %** (4 633 instructions, 879 non couvertes, 743 tests exécutés).
- [x] Seuil fixé à **80 %** dans `pyproject.toml` (`[tool.coverage.report] fail_under`), soit un peu sous la mesure.
- [x] CI : `pytest --cov=abrip --cov-report=term-missing --cov-report=xml:coverage.xml` ; l’étape échoue sous 80 %.
- [x] Rapport XML publié comme artefact (`actions/upload-artifact`, même en cas d’échec) ; `coverage.xml` ajouté au `.gitignore`.
- [x] Vérification locale : `coverage report` applique le seuil et sort en succès à 81,03 %.
- [x] Note : la mesure complète prend ~26 min sur ce poste (tests de démonstration compris) ; la CI la parallélise mieux mais reste le poste le plus long.

### 2.3 Tests frontend — **fait**
- [x] Configuration vérifiée : Vite 8, TypeScript 7, npm, aucun test existant.
- [x] Vitest 5.1.2 ajouté en dépendance exacte et script `npm test`.
- [x] Tests des fonctions pures : `format.test.ts` (UTC) et `searchParams.test.ts` (pagination).
- [x] Régression de pagination couverte par `searchParams.test.ts`, y compris le cas « changer d’offset ».
- [x] Tests intégrés à la CI (`npm test` avant le typecheck et le build).
- [x] `npm test` (11 tests), `npm run typecheck`, `npm run build` passent.
- [x] Smoke test Playwright : `@playwright/test` 1.65.1 (dépendance exacte) et script `npm run test:e2e`.
- [x] `playwright.config.ts` démarre `abrip api serve` sur le port 8010 et attend `/api/health` ; le service sert `frontend/dist` et les données de démonstration sur la même origine.
- [x] `frontend/e2e/smoke.spec.ts` couvre quatre parcours : vue d’ensemble, liste des AS → fiche AS, liste des préfixes → fiche préfixe, liste des événements → détail. Chaque parcours vérifie aussi l’absence d’erreur console, d’exception JS et de réponse HTTP 5xx.
- [x] Vitest est limité à `src/**/*.test.ts` (`vitest.config.ts`) pour ne pas tenter d’exécuter les specs Playwright avec son runner ; la configuration Playwright est incluse au typecheck (`@types/node` ajouté).
- [x] CI : job `e2e` dédié (Python + uv + Node, `demo bootstrap`, build, `npx playwright install --with-deps chromium`, parcours, traces uploadées en cas d’échec). Le job `image` attend désormais ce job.
- [x] Vérification locale : 4 parcours réussis, y compris en mode CI (serveur démarré par Playwright, deux workers). Le jeu de démonstration ne contient que 10 AS (page de 25) : la pagination « Suivant » reste couverte par les tests Vitest de `searchParams.ts`, pas par le navigateur.

### 2.4 Audit et veille des dépendances — **fait**
- [x] Dependabot configuré (`.github/dependabot.yml`) pour `uv`, `npm`, GitHub Actions et Docker, mises à jour hebdomadaires groupées (mensuelles pour les Actions et l’image).
- [x] `pip-audit==2.10.1` ajouté au groupe dev et exécuté en CI ; localement : « No known vulnerabilities found ».
- [x] `npm audit --audit-level=high` ajouté à la CI ; localement, `npm install` rapporte 0 vulnérabilité.
- [x] Aucun faux positif constaté ; le paquet local `abrip` est simplement ignoré par `pip-audit` (absent de PyPI).
- [x] Premier passage de Dependabot traité : groupe Python fusionné (CI verte), actions GitHub montées en v7 (checkout, setup-node, setup-python, setup-uv, upload-artifact — l’avertissement Node 20 disparaît). `node:25-slim` écarté (version non LTS) ; on reste sur `node:22-slim` jusqu’à la prochaine LTS.
- [x] `react-router-dom 7.18.6` appliqué seul dans un premier temps, puis `recharts` pris dans sa **dernière version (3.11.1)** sur décision explicite. Le bundle gzip passe à 259 328 octets : le plafond est relevé de 256 000 à **270 000 octets** dans la CI et dans `docs/deploiement.md`, avec ~10 Ko de marge résiduelle.

### 2.5 Installation Docker reproductible — **modifié, non construit localement**
- [x] `Dockerfile` : `uv==0.13.1` installé puis `uv sync --locked --no-dev`, sans cache conservé, `PATH` pointant sur `/app/.venv/bin`.
- [x] Étapes, utilisateur non-root, healthcheck et point d’entrée inchangés.
- [x] `uv.lock` copié dans l’image et verrouillage réellement utilisé (`--locked` échoue si le verrou diverge).
- [x] Construction de l’image validée par la CI (job `Construction de l’image`, 1 min 16 s) : build puis démarrage et interrogation du service. Docker reste absent du poste local, la vérification est donc faite en CI.

### 2.6 Pre-commit — **fait**
- [x] Configuration légère `.pre-commit-config.yaml` en hooks `local` : Ruff lint (avec `--fix`), Ruff format et Mypy.
- [x] Mêmes versions/options que la CI (outils du `pyproject.toml`, `uv run --locked`).
- [x] Installation documentée en tête du fichier (`pipx install pre-commit` puis `pre-commit install`).
- [x] Aucun téléchargement implicite d’environnement : les hooks réutilisent l’environnement `uv` du projet.

## Lot 3 — Schémas de réponse typés — **terminé**

Objectif : clore la réserve du lot 1 sur les horodatages des endpoints qui renvoient encore des `dict` ad hoc et rendre le contrat OpenAPI explicite. Découpage retenu après cartographie des 19 endpoints concernés, du plus sûr au plus risqué ; chaque sous-lot apporte ses tests de contrat avant d’attaquer le suivant.

### 3.0 et 3.1 — Facets, pays et table des noms — **fait**
- [x] `EventFacets` (4 cardinalités `dict[str, int]`) et `response_model` sur `/events/facets`.
- [x] `CountryIndicator` (9 champs, dont `rpki_coverage_ratio` nullable) et `response_model=list[CountryIndicator]` sur `/countries`.
- [x] `AsnNames` (`RootModel[dict[str, str]]`) sur `/asns/names` : les clés dynamiques (ASN → nom) sont préservées.
- [x] Vérification : `test_api_contrat_schemas.py` contrôle les clés, les types et les schémas présents dans `/api/openapi.json`.

### 3.2 — Incidents et relations d’un pays — **fait**
- [x] `IncidentOut` (base `ApiModel`) sur `/incidents` : contrairement aux `dict` bruts, les datetimes imbriqués passent par le sérialiseur UTC (`Z`).
- [x] `CountryRelation` et `CountryRelationships` sur `/countries/{iso2}/relationships`, avec listes ordonnées inchangées.
- [x] Vérification : `test_api_contrat_schemas.py` exige le suffixe `Z` sur `first_seen`/`last_seen` des incidents ; les tests existants de relations passent sans changement.

### 3.3 Tableaux et historiques de l’explorateur — **fait**
- [x] `PrefixRow` sur `/asns/{asn}/prefixes` et `/countries/{iso2}/prefixes` : `first_seen`/`last_seen` passent en UTC explicite (`Z`), les comptes de jours et statuts restent identiques.
- [x] `NeighbourRow`, `CountryNeighbourRow` et enveloppes `NeighboursResponse` / `CountryNeighboursResponse` sur les deux tables de voisins : le champ `member_asn` n’existe que dans la vue pays, conformément au contrat actuel.
- [x] `RoaHistoryRow`, `RouteHistoryRow` et enveloppes typées sur les deux historiques de référentiel : `trust_anchor`/`max_length` d’un côté, `source` de l’autre, sans clés parasites.
- [x] `PeriodRun` (avec `observations`) contre `PeriodPresence` (sans) et `DailyObservation` / `DailyPresence` sur les deux historiques : les clés conditionnelles restent absentes plutôt qu’à `null`.
- [x] `PrefixFacets` déplacé dans `api/schemas.py` et aligné sur `ApiModel` ; les helpers internes (`_runs`, `_add_statuses`) restent en `dict`, le modèle n’étant appliqué qu’à la frontière HTTP.
- [x] Vérification : 326 tests réussis (dont les 316 d’équivalence tables journalières) et 4 parcours navigateur OK.

### 3.4 Fiches AS, préfixe et timeline — **fait**
- [x] `AsnDetail`, `PrefixDetail` et `EventTimeline` avec `response_model` explicite sur `/asns/{asn}`, `/prefixes/{prefix}` et `/events/{id}/timeline`.
- [x] Sous-modèles dédiés (`AsnIdentity`, `PrefixOrigin`, `TopPath`, `VisibilitySnapshot`, `RoaEntry`, `ChurnPoint`, `VisibilityPoint`, …) : plus aucun `dict` ad hoc dans ces trois réponses.
- [x] Les datetimes naïfs de ces endpoints sortent désormais avec `Z`, y compris dans `event`, `related_events`, `incident` et les séries de la timeline (anciennement `model_dump()` en mode python, sans suffixe).
- [x] `identity` reste un schéma explicite aligné sur `REF_ASN_SCHEMA` ; les colonnes inattendues d’un `SELECT *` ne fuient plus dans le contrat.
- [x] Vérification : 13 tests de contrat, 65 tests ciblés et 4 parcours navigateur OK. **La réserve UTC du lot 1 est ainsi close.**

### 3.5 Propagation — **fait**
- [x] `PropagationResponse`, `PropagationReplayResponse` et `UpstreamsResponse` sur les trois endpoints de `propagation.py`.
- [x] Deux variantes de nœuds et d’arêtes : le graphe statique porte `paths`/`hidden_paths`/`observations`, le rejeu uniquement les champs communs — aucune clé parasite dans la réponse.
- [x] `ReplayFrame` contre `ReplayFrameWithPaths` : `path_ids` est présent quand la liste des chemins est fournie, totalement absent au-delà de la borne (union discriminée par le type réel, pas un `null`).
- [x] `UpstreamPoint.values` reste un `dict[str, int]` à clés dynamiques `as{n}` ; les `ts` restent des chaînes ISO avec `+00:00` (format attendu par les tests et le frontend).
- [x] Vérification : 46 tests ciblés (dont les tests de bornes du rejeu), 16 tests de contrat et 4 parcours navigateur OK. **Les 19 endpoints ad hoc sont désormais typés.**

## Vérification finale du lot 1 + 2

| Vérification | Résultat |
|---|---|
| `uv run --locked ruff check src tests` | OK |
| `uv run --locked ruff format --check src tests` | OK (84 fichiers) |
| `uv run --locked mypy src` | OK (51 fichiers) |
| Tests Python ciblés (persistance, schémas, broker, RPKI, curation, PCH, API) | OK |
| Suite Python complète | 735 réussis, 8 échecs d’équivalence corrigés en 1.7 ; fichiers API/tableaux rejoués après correction : 316 + 216 réussis |
| Couverture Python | 81,03 % (seuil CI 80 %) |
| `npm test` | 11 tests OK |
| `tests/test_api_contrat_schemas.py` | 16 tests de contrat (OpenAPI, facets, pays, noms AS, incidents UTC, relations, préfixes, voisins, historiques, périodes, fiches AS/préfixe/timeline, propagation et amonts) |
| `npm run test:e2e` | 4 parcours Playwright OK (dont 1 exécution en mode CI) |
| `npm run typecheck` | OK (src, e2e et configurations) |
| `npm run build` | OK |
| Budget gzip mesuré | 259 328 octets (plafond relevé à 270 000) |
| `abrip demo verify` | rappel 1.0, 5/5 |
| Construction Docker | validée en CI (build + service interrogé, 1 min 16 s) |

## Journal d’exécution

| Date | Étape | Fichiers/zone | Vérifications et résultat |
|---|---|---|---|
| 2026-11-25 | Plan et suivi rédigés | `docs/ameliorations-proposees.md`, `docs/suivi-modifications.md` | — |
| 2026-11-25 | Métriques partitionnées par jour | `analytics/metrics.py`, `api/deps.py`, `tests/test_metrics_persistence.py` | 3 tests OK ; bootstrap + verify 5/5 ; 7 partitions par métrique |
| 2026-11-25 | Pagination et fuseau UTC frontend | `AsnList.tsx`, `Prefixes.tsx`, `searchParams.ts`, `format.ts`, `TimeChart.tsx`, `EventDetail.tsx`, `PropagationReplay.tsx` | 11 tests Vitest, typecheck et build OK |
| 2026-11-25 | UTC côté API | `api/schemas.py`, `tests/test_schemas.py` | 4 tests OK |
| 2026-11-25 | Pagination broker | `ingestion/broker.py`, `tests/test_broker.py` | 3 tests OK |
| 2026-11-25 | Curation bornée | `etl/curate.py`, `etl/pch_parser.py`, `tests/test_curate_rib.py`, `tests/test_pch_parser.py` | 12 tests OK |
| 2026-11-25 | RPKI vectorisée | `analytics/metrics.py`, `tests/test_metrics_rpki.py` | 2 tests OK |
| 2026-11-25 | Garde-fous CI | `ci.yml`, `dependabot.yml`, `.pre-commit-config.yaml`, `Dockerfile`, `Makefile`, frontend | YAML valide ; `pip-audit` sans vulnérabilité |
| 2026-11-25 | Couverture mesurée | `pyproject.toml`, `ci.yml`, `.gitignore` | 81,03 % ; seuil 80 % ; `coverage report` sort en succès |
| 2026-11-25 | Stabilité des agrégats | `api/routers/explore.py`, `api/routers/metrics.py` | 316 tests d’équivalence OK, trois exécutions stables |
| 2026-11-25 | Fusion PR #4 | `main` (commit `ce0d650`) | CI verte sur `main` : Python 2 min 7 s, frontend 11 s, image 1 min 16 s |
| 2026-11-25 | Dependabot : premier passage | `pyproject.toml`, `uv.lock`, `ci.yml`, `frontend/package*.json`, `docs/deploiement.md` | Groupe Python et actions v7 fusionnés (CI verte) ; `react-router-dom 7.18.6` seul ; recharts 3.11.0 et node 25-slim écartés (budget gzip, non LTS) |
| 2026-11-25 | Smoke test navigateur | `frontend/e2e/smoke.spec.ts`, `playwright.config.ts`, `vitest.config.ts`, `ci.yml` | 4 parcours OK en local et en mode CI ; aucun signalement d’erreur console/HTTP 5xx |
| 2026-11-25 | Dernière version de recharts | `frontend/package*.json`, `ci.yml`, `docs/deploiement.md` | 3.11.1 installée ; 11 tests, typecheck, build et 4 parcours navigateur OK ; budget 270 000 octets |
| 2026-11-25 | Lot 3, sous-lots 0 à 2 | `api/schemas.py`, `api/routers/{explore,events,asn_explorer}.py`, `tests/test_api_contrat_schemas.py` | 63 tests ciblés OK, ruff et mypy OK ; 5 endpoints typés, UTC conservé sur les incidents |
| 2026-11-25 | Lot 3, sous-lot 3.3 | `api/schemas.py`, `api/routers/asn_explorer.py`, `tests/test_api_contrat_schemas.py` | 8 endpoints typés ; 326 tests OK dont 316 d’équivalence, 4 parcours navigateur OK |
| 2026-11-25 | Lot 3, sous-lot 3.4 | `api/schemas.py`, `api/routers/{explore,events}.py`, `tests/test_api_contrat_schemas.py` | 3 fiches typées ; datetimes en `Z` ; 13 tests de contrat et 4 parcours navigateur OK |
| 2026-11-25 | Lot 3, sous-lot 3.5 | `api/schemas.py`, `api/routers/propagation.py`, `tests/test_api_contrat_schemas.py` | 3 endpoints typés ; `path_ids` conditionnel préservé ; 46 tests ciblés et 4 parcours navigateur OK |

## Bilan

- **Lot 1 :** terminé et vérifié ; sa réserve sur les datetimes naïfs des réponses `dict` ad hoc est close par le lot 3.4.
- **Lot 2 :** terminé : formatage, couverture, tests frontend (unitaires et navigateur), audits, Dependabot, pre-commit et Dockerfile. L’image est construite et démarrée en CI ; les parcours critiques sont joués dans Chromium.
- **Lot 3 :** terminé : 19 endpoints ad hoc typés, contrat OpenAPI explicite et datetimes sérialisés en UTC sur toutes les réponses concernées.
- **Points reportés :** section 4 de `docs/ameliorations-proposees.md` (performance, exploitation, sécurité) et autres pistes produit de la section 3.
