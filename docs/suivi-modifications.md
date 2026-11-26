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

## Lot 4 — Durcissement HTTP — **terminé**

### 4.1 Recherche littérale — **fait**
- [x] `escape_like` (`src/abrip/api/search.py`) échappe `\`, `%` et `_` ; toutes les requêtes `LIKE` de `explore.py` utilisent désormais `ESCAPE '\'`.
- [x] Quatre filtres couverts : `q` de `/asns` et `/prefixes`, et les deux branches de `/search` (ASN et préfixe).
- [x] Tests : un `%` ou un `_` saisi ne renvoie aucun résultat, la recherche littérale continue de fonctionner.

### 4.2 Comparaison de clé en temps constant — **fait**
- [x] `api_key_matches` (`api/deps.py`) hache les deux chaînes en SHA-256 puis utilise `hmac.compare_digest` : ni le contenu ni la longueur de la clé configurée ne fuient par le temps de comparaison.
- [x] Utilisé à la fois par la dépendance globale `verify_api_key` et par le middleware qui protège `/api/docs` et `/api/openapi.json`.
- [x] Tests : clé absente, mauvaise clé, bonne clé, documentation protégée, authentification désactivée par défaut.

### 4.3 En-têtes de sécurité — **fait**
- [x] Middleware HTTP sur toutes les réponses (API et SPA) : `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` restreinte.
- [x] Pas de CSP ajoutée dans ce lot : le frontend embarque des styles en ligne et la règle doit être vérifiée parcours par parcours avant déploiement. À reprendre avec les tests d’accessibilité.
- [x] Vérification : 40 tests ciblés et 4 parcours navigateur OK.

## Lot 5 — Optimisation HTTP — **terminé**

### 5.1 Compression gzip — **fait**
- [x] `GZipMiddleware` sur les réponses de plus de 1 024 octets (`GZIP_MIN_SIZE`), API et documentation comprises ; les petites réponses ne sont pas compressées.
- [x] Test : `/api/openapi.json` est compressé quand le client envoie `Accept-Encoding: gzip`, `/api/search` (corps minimal) ne l'est pas.

### 5.2 ETag et revalidation — **fait**
- [x] ETag faible (SHA-256 du corps JSON) et `Cache-Control: private, no-cache` sur les réponses JSON 200 : revalidation à chaque appel, **304 sans corps** si le contenu est inchangé. Étiquette faible car le même JSON peut être servi compressé ou non.
- [x] `/api/health` est exclu (`no-store`) : son `generated_at` change à chaque appel et la supervision doit voir l'état courant.
- [x] Les erreurs (404, 503, 422) ne portent ni ETag ni `Cache-Control`.
- [x] Test : ETag présent, 304 sur `If-None-Match` exact et `*`, ETag différent selon les paramètres de requête, santé non cachée.

### 5.3 Connexions DuckDB — **fait**
- [x] `DataAccess` garde une connexion par thread (`threading.local`) au lieu d'en ouvrir une par requête : pas de verrou global, une connexion n'étant pas partageable entre threads.
- [x] Test : même connexion réutilisée dans un thread, connexion distincte dans un autre.
- [x] Détail et limites des mesures dans `docs/performances.md` (section « Transport HTTP »).

## Lot 6 — Accessibilité et CSP — **terminé**

### 6.1 Contrôles WCAG automatisés — **fait**
- [x] `@axe-core/playwright` 4.14.1 (dépendance de développement) et `frontend/e2e/accessibilite.spec.ts` : quatre pages (accueil, AS, préfixes, événements) analysées avec les règles `wcag2a`, `wcag2aa`, `wcag21a` et `wcag21aa`.
- [x] Contraste corrigé : `--ink-400` passe de `#63819a` à `#526e87` (4,8:1 sur papier relevé, 5,2:1 sur papier) et `--amber` de `#b8730f` à `#8d580a` (4,7:1 sur le fond ambré). 55 nœuds en échec avant le changement, zéro après.

### 6.2 CSP — **fait**
- [x] `SPA_CSP` appliquée uniquement au HTML servi par la SPA : `default-src`/`script-src 'self'`, `style-src 'self' 'unsafe-inline'` (styles injectés par les graphiques), `img-src 'self' data: blob:` (export SVG/PNG), et `object-src`/`base-uri`/`form-action`/`frame-ancestors` fermés.
- [x] Swagger UI volontairement exclu : il charge ses propres ressources et serait cassé par `script-src 'self'`.
- [x] Test Python : CSP présente sur le HTML de la SPA, absente de l'API ; test navigateur : aucun événement `securitypolicyviolation` ni erreur console.
- [x] Vérification : 21 tests Python ciblés, 9 parcours Playwright (4 accessibilité + 5 smoke), `npm run typecheck` et `npm run build` OK.

## Lot 7 — Mesure de concurrence — **terminé**

### 7.1 Test de charge reproductible — **fait**
- [x] `scripts/bench/run_charge.py` : utilisateurs simultanés configurable (`--users`), durée (`--duration`), pause éventuelle (`--think`), sortie JSON (`--json`). Découvre un préfixe et un ASN présents, préchauffe les index, puis envoie un mélange de neuf routes sans cache client.
- [x] Aucune dépendance ajoutée : `httpx` et `asyncio` suffisent, le script reste lisible et jouable avec l'environnement du projet.
- [x] Rapport : nombre de requêtes, débit, erreurs réseau et réponses non-200, p50/p95/p99 par endpoint et global.
- [x] Mesure locale de référence consignée dans `docs/performances.md` : 2,2 → 4,3 req/s de 1 à 5 utilisateurs, puis plateau à 4,3 req/s à 10 utilisateurs avec un p95 passant de 1,25 s à 9,39 s. Mono-processus et DuckDB monocœur expliquent la limite ; non joué en CI.

## Lot 8 — Rétention des couches dérivées — **terminé**

### 8.1 Politique et commande de purge — **fait**
- [x] `etl.retention_days` (90 jours par défaut) s'ajoute à la rétention brute existante (`ingestion.raw_retention_days`, 30 jours). Curés et analytiques partagent la même fenêtre pour ne pas rendre les tables journalières incompatibles avec les partitions sources.
- [x] `storage/retention.py` : plan ne considérant que les répertoires `date=AAAA-MM-JJ` strictement antérieurs à la date limite ; noms de dates validés, liens symboliques ignorés, aucun chemin configuré supprimable.
- [x] `abrip etl purge` simule par défaut et n'efface qu'avec `--apply` ; `--days` réduit ponctuellement la fenêtre. Bilan JSON : répertoires, fichiers, octets et lignes du catalogue.
- [x] Les entrées `curated_partitions` correspondant aux répertoires supprimés sont retirées du catalogue.
- [x] La compaction reste `abrip etl compact` : tri et fusion des fragments en un fichier par partition ; procédure décrite dans `docs/deploiement.md`.
- [x] Vérification : 7 tests dédiés (plan, simulation, purge effective, catalogue, CLI) et suite ETL existante OK.

## Lot 9 — Observabilité — **terminé**

### 9.1 Identifiant de requête — **fait**
- [x] Middleware HTTP générant un UUID (ou reprenant un `X-Request-ID` client court et sûr), renvoyé dans la réponse et propagé aux logs JSON via `current_request_id` (`logging_conf.py`).
- [x] Test : identifiant généré ou echoé, valeur invalide remplacée, `request_id` présent dans le format JSON, en-tête présent même sur les parcours navigateur.

### 9.2 Métriques Prometheus — **fait**
- [x] `GET /api/metrics` (hors OpenAPI, protégé par la clé API globale) expose `abrip_http_requests_total`, un histogramme de durée à neuf seaux, et des jauges `abrip_data_files`/`abrip_data_bytes`/`abrip_data_age_days` par couche.
- [x] Agrégation par **modèle de route** (`/api/asns/{asn}`) pour borner la cardinalité ; les seaux sont cumulatifs (un seul seau incrémenté par observation).
- [x] Aucune dépendance ajoutée : registre local verrouillé et format texte Prometheus.
- [x] Test : format HELP/TYPE, compteurs par route, cumul des seaux, jauges de couches, protection par clé ; 10 parcours navigateur OK.
- [x] Configuration de scrape et usage de l'en-tête documentés dans `docs/deploiement.md`.

## Lot 10 — Montée en workers — **terminé**

### 10.1 Service multi-processus — **fait**
- [x] `abrip api serve --workers N` et `api.workers` (`ABRIP_API__WORKERS`) configures uvicorn en multi-processus ; défaut inchangé à 1.
- [x] `--reload` est refusé avec plusieurs workers, `--workers 0` est rejeté.
- [x] Test : 5 cas (défaut, option CLI, configuration, incompatibilité reload, valeur nulle) sans démarrer de serveur.
- [x] Re-mesure avec 4 workers sur le jeu de démonstration : 3,6 req/s et p95 8,21 s à 10 utilisateurs, contre 4,3 req/s et 9,39 s avec un worker — aucun gain de débit sur cette machine à cœur partagé. Résultat et limites consignés dans `docs/performances.md`.
- [x] Documentation : chaque worker a son propre cache et ses propres compteurs Prometheus ; un scrape ne représente qu'un processus.

## Lot 11 — Finitions de sécurité et clavier — **terminé**

### 11.1 Limitation de débit — **fait**
- [x] `api.rate_limit_per_minute` (défaut `0`, désactivé) et `api/rate_limit.py` : fenêtre glissante par adresse client, verrouillée et testable avec une horloge injectable.
- [x] Au-delà de la limite : réponse 429 au format d'erreur normalisé, corps `{"code": "rate_limited", ...}` et en-tête `Retry-After`. `/api/health` et `/api/metrics` sont exemptés.
- [x] Les 429 sont comptés dans les métriques Prometheus (le limiteur est placé avant l'observabilité). Limite locale à chaque worker, documentée.
- [x] Test : 6 cas (fenêtre, par client, 429 HTTP, supervision exempte, comptage, défaut inchangé).

### 11.2 Interactions clavier — **fait**
- [x] `frontend/e2e/clavier.spec.ts` rejoint les éléments uniquement avec Tab : onglets ARIA d'une fiche AS pilotés aux flèches, Début et Fin ; modale ouverte avec Entrée et fermée avec Échap, avec retour du focus sur le déclencheur.
- [x] Vérification : 12 parcours Playwright OK (4 accessibilité, 6 smoke, 2 clavier), `npm run typecheck` OK.

## Lot 12 — Alerting opérationnel — **terminé**

### 12.1 Notifications d'incidents — **fait**
- [x] `alerts.webhook_url` (vide par défaut : aucun envoi), `min_severity` (`critical` par défaut), `dedupe_days` (7) et `timeout_seconds` (10).
- [x] `alerting.py` : sélection par sévérité, message lisible (préfixe, résumé, détecteurs, score, date), envoi webhook compatible Slack, puis mémorisation dans la table `alert_log` du catalogue. Un webhook en échec est journalisé et **n'interrompt jamais** la détection.
- [x] Déduplication par `incident_id` avec oubli des entrées plus anciennes que `dedupe_days` ; les incidents lus depuis les Parquet sont filtrés sur `last_seen`.
- [x] `abrip detect run --notify` et `abrip detect alert --days N` ; 6 tests sans réseau (sévérité, déduplication, échec HTTP, absence de webhook, lecture des incidents récents, commande CLI).
- [x] Compatibilité Windows : les fuseaux horaires des colonnes Parquet sont retirés avant conversion en dictionnaires Python (tzdata absent localement).

## Lot 13 — Tableau de qualité des données — **terminé**

### 13.1 Endpoint et interface — **fait**
- [x] `GET /api/quality` (`DataQuality`, schémas `SourceFreshness`, `CountryCoverage`, `RoaSummary`, `SilentCollector`) : fraîcheur par source depuis le journal d'ingestion, dix pays les mieux couverts, volume du référentiel RPKI et collecteurs sans archive depuis plus de deux jours.
- [x] Aucune donnée recalculée : l'endpoint lit le catalogue et les Parquet existants ; installation vierge incluse (listes vides et collecteurs signalés).
- [x] Page React « Qualité des données » chargée à la demande, ajoutée à la navigation, avec tableaux et états vides. Contrat frontend typé à la main dans `lib/types.ts`.
- [x] Test : 3 tests API (jeu de démo, journal d'ingestion, installation vierge), schéma OpenAPI vérifié, 14 parcours Playwright (5 accessibilité, 7 smoke, 2 clavier) et budget gzip 253 927 octets sous la limite de 270 000.

## Lot 14 — Précalcul des endpoints coûteux — **terminé**

### 14.1 Fiches AS — **fait**
- [x] `analytics/precompute.py` construit `asn_prefix_stats` (asn, prefix, mises à jour, première/dernière date, pairs distincts) en une passe DuckDB bornée en mémoire, avec écriture atomique et journalisation dans le catalogue.
- [x] `GET /api/asns/{asn}` lit cette table si elle est plus récente que toutes les partitions curées, sinon retombe sur l'ancien regroupement de `bgp_elements`. Aucun changement de contrat.
- [x] `abrip analytics precompute` (à relancer après chaque curation), documenté dans `docs/deploiement.md`.
- [x] Test : égalité stricte entre les deux chemins sur le jeu de démo, API avant/après précalcul, commande CLI.

### 14.2 Préchauffage de la vue d'ensemble — **fait**
- [x] `api.prewarm` (`ABRIP_API__PREWARM=true`, défaut `false`) remplit le cache de la synthèse 7 jours au démarrage de chaque worker ; le pic du premier appel est déplacé vers le démarrage, pas supprimé.
- [x] Test : le générateur de la vue d'ensemble est appelé une fois avec `days=7` quand l'option est active.
- [x] Vérification : 4 tests dédiés et 360 tests API/contrat/analytics existants OK. Gain à 50 M de lignes non re-mesuré (section « Précalcul » de `docs/performances.md`).

## Lot 15 — Qualification humaine L5 — **terminé**

### 15.1 Boucle de retours — **fait**
- [x] Table `event_feedback` du catalogue (`event_id`, verdict, auteur, note, horodatage) avec validation des quatre verdicts ; aucune écriture depuis l'API, qui reste en lecture seule.
- [x] `abrip detect label <event_id> --verdict ... --author ... --note ...` et `abrip detect precision` : taux de faux positifs et précision par détecteur (`unknown` exclu du dénominateur).
- [x] `configs/allowlist.yaml` versionné, chargé et validé par `qualification.py`, affichable avec `abrip detect allowlist` et appliqué aux alertes (correspondance par préfixe, ASN ou détecteur).
- [x] Test : 7 cas (verdicts, précision, allowlist YAML, CLI, silence d'une alerte admissible). Documentation L5 et guide de déploiement mis à jour.
- [x] La qualification reste une tâche humaine : sans opérateur, la boucle reste vide. Le mécanisme est prêt, le jugement ne s'automatise pas.

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
| `tests/test_securite_http.py`, `test_recherche_litterale.py` | 40 tests ciblés au total avec API/noms AS, dont en-têtes, clé API et jokers SQL ; 2 tests CSP ajoutés au lot 6 |
| `tests/test_http_cache.py`, `test_acces_donnees.py` | 11 tests : gzip, ETag/304, `no-store` de la santé, réutilisation des connexions DuckDB |
| `frontend/e2e/accessibilite.spec.ts` | 4 pages auditées par axe (WCAG 2.0/2.1 A et AA), zéro violation |
| `frontend/e2e/clavier.spec.ts` | 2 parcours : onglets aux flèches/Début/Fin, modale Entrée/Échap et retour du focus |
| `scripts/bench/run_charge.py` | Générateur async sans dépendance : `--users`, `--duration`, `--think`, `--json` ; rapport p50/p95/p99 par endpoint |
| `tests/test_retention.py` | 7 tests : plan de purge, dates invalides ignorées, simulation, purge effective, nettoyage du catalogue, CLI |
| `tests/test_metriques_prometheus.py` | 8 tests : `X-Request-ID`, corrélation JSON, format Prometheus, seaux cumulatifs, jauges, modèles de route |
| `tests/test_api_workers.py` | 5 tests : option CLI, configuration, incompatibilité `--reload`, refus de `--workers 0` |
| `tests/test_limite_debit.py` | 6 tests : fenêtre glissante, limite par client, 429, exemption supervision, comptage 429, défaut désactivé |
| `tests/test_alerting.py` | 6 tests : sévérité, déduplication, échec HTTP, webhook absent, incidents récents, commande CLI |
| `tests/test_qualite_donnees.py` | 3 tests : contrat de `/api/quality`, journal d'ingestion, installation vierge |
| `tests/test_precalcul.py` | 4 tests : équivalence précalcul/calcul direct, fiche AS avant/après, commande CLI, préchauffage |
| `tests/test_qualification.py` | 7 tests : verdicts persistés, précision, allowlist YAML, commandes CLI, alerte tue par exemption |
| `npm run test:e2e` | 14 parcours Playwright OK (5 accessibilité, 7 smoke, 2 clavier ; dont 1 exécution en mode CI) |
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
| 2026-11-26 | Lot 4 — durcissement HTTP | `api/{main,deps,search}.py`, `api/routers/explore.py`, `tests/test_securite_http.py`, `tests/test_recherche_litterale.py` | En-têtes, clé en temps constant, LIKE échappé ; 40 tests ciblés et 4 parcours navigateur OK |
| 2026-11-26 | Lot 5 — optimisation HTTP | `api/{main,deps}.py`, `tests/{test_http_cache,test_acces_donnees}.py`, `docs/performances.md` | gzip, ETag/304, santé `no-store`, connexions DuckDB par thread ; 11 tests dédiés et 49 tests ciblés OK |
| 2026-11-26 | Lot 6 — accessibilité et CSP | `api/main.py`, `src/styles.css`, `e2e/{accessibilite,smoke}.spec.ts`, `tests/test_securite_http.py` | 55 problèmes de contraste corrigés, axe WCAG sur 4 pages, CSP sur la SPA ; 21 tests Python et 9 parcours navigateur OK |
| 2026-11-26 | Lot 7 — mesure de concurrence | `scripts/bench/run_charge.py`, `docs/performances.md` | 2,2 à 4,3 req/s selon la concurrence ; p95 de 1,25 s à 9,39 s sur le jeu de démonstration |
| 2026-11-26 | Lot 8 — rétention des couches dérivées | `config.py`, `storage/retention.py`, `cli.py`, `tests/test_retention.py`, `docs/deploiement.md` | `etl purge` simulé par défaut, `--apply` explicite, catalogue nettoyé ; 7 tests dédiés |
| 2026-11-26 | Lot 9 — observabilité | `api/{main,metrics}.py`, `logging_conf.py`, `tests/test_metriques_prometheus.py`, `docs/deploiement.md` | `X-Request-ID` corrélé aux logs, métriques Prometheus sans dépendance ; 8 tests dédiés et 10 parcours navigateur OK |
| 2026-11-26 | Lot 10 — montée en workers | `config.py`, `cli.py`, `tests/test_api_workers.py`, `docs/{deploiement,performances}.md` | `--workers` et `api.workers`, garde-fous CLI ; 5 tests, re-mesure sans gain de débit sur un cœur partagé |
| 2026-11-26 | Lot 11 — finitions de sécurité | `config.py`, `api/{main,rate_limit}.py`, `tests/test_limite_debit.py`, `e2e/clavier.spec.ts` | 429 avec `Retry-After` et exemption supervision ; 6 tests Python, 2 parcours clavier, 12 parcours au total |
| 2026-11-26 | Lot 12 — alerting | `config.py`, `alerting.py`, `cli.py`, `storage/catalog.py`, `tests/test_alerting.py`, `docs/deploiement.md` | Webhook Slack, déduplication par incident, `--notify` et `detect alert` ; 6 tests sans réseau |
| 2026-11-26 | Lot 13 — qualité des données | `api/schemas.py`, `api/routers/system.py`, `pages/Quality.tsx`, `App.tsx`, `Layout.tsx`, `tests/test_qualite_donnees.py` | `/api/quality` typé et page dédiée ; 3 tests API, 14 parcours navigateur |
| 2026-11-26 | Lot 14 — précalcul | `analytics/precompute.py`, `api/{main,deps}.py`, `api/routers/{explore,system}.py`, `cli.py`, `tests/test_precalcul.py` | `asn_prefix_stats`, bascule automatique et `api.prewarm` ; 4 tests dédiés |
| 2026-11-26 | Lot 15 — qualification L5 | `catalog.py`, `qualification.py`, `configs/allowlist.yaml`, `cli.py`, `alerting.py`, `tests/test_qualification.py` | Verdicts, précision par détecteur et exemptions appliquées aux alertes ; 7 tests dédiés |

## Bilan

- **Lot 1 :** terminé et vérifié ; sa réserve sur les datetimes naïfs des réponses `dict` ad hoc est close par le lot 3.4.
- **Lot 2 :** terminé : formatage, couverture, tests frontend (unitaires et navigateur), audits, Dependabot, pre-commit et Dockerfile. L’image est construite et démarrée en CI ; les parcours critiques sont joués dans Chromium.
- **Lot 3 :** terminé : 19 endpoints ad hoc typés, contrat OpenAPI explicite et datetimes sérialisés en UTC sur toutes les réponses concernées.
- **Lot 4 :** terminé pour le durcissement HTTP (recherche littérale, clé en temps constant, en-têtes) ; la limitation de débit et la CSP restent à étudier.
- **Lot 5 :** terminé pour le transport HTTP (gzip, ETag/304, connexions DuckDB par thread) ; les gains n'ont pas été re-mesurés sur les jeux à 50 M de lignes.
- **Lot 6 :** terminé : contrôles WCAG automatisés dans Playwright, contrastes corrigés et CSP sur le HTML de la SPA ; la limitation de débit reste à étudier.
- **Lot 7 :** terminé : test de charge asyncio reproductible et première mesure de concurrence, consignée dans `docs/performances.md`.
- **Lot 8 :** terminé : rétention des couches curées et analytiques avec purge simulée par défaut et nettoyage du catalogue ; la compaction existante reste documentée.
- **Lot 9 :** terminé : identifiant de requête corrélé aux logs et exposition Prometheus des latences, erreurs et volumes stockés.
- **Lot 10 :** terminé : service multi-processus configurable, avec mesure locale montrant l'absence de gain sur un cœur partagé et la limitation des métriques à un worker.
- **Lot 11 :** terminé : limitation de débit configurable et parcours clavier automatisés ; les points 1, 2 et 4 de la feuille de route sont désormais tous traités.
- **Lot 12 :** terminé : alertes webhook sur incidents critiques avec déduplication persistée, sans réseau dans les tests.
- **Lot 13 :** terminé : tableau de qualité des données exposé dans l'API et dans l'interface, sans recalcul.
- **Lot 14 :** terminé : précalcul des préfixes par AS avec bascule automatique et préchauffage optionnel de la vue d'ensemble.
- **Lot 15 :** terminé : boucle de qualification L5 outillée (verdicts, précision, allowlist) ; le jugement humain reste nécessaire.
- **Point reporté :** détection sub-horaire. Toutes les autres pistes des sections 1, 2, 3 et 4 sont traitées.
