# Bilan général des travaux — ABRIP

Document de synthèse autonome des lots 1 à 16, rédigé après la fusion du lot 16
(2026-11-26). Il rassemble les décisions, les changements, les vérifications et
les réserves éparpillées dans `docs/suivi-modifications.md`,
`docs/ameliorations-proposees.md`, `docs/performances.md` et
`docs/limites-et-remediations.md`. Ce dernier reste la source de vérité
opérationnelle : le présent document ne le remplace pas, il le résume.

## 1. État final

- `main` est propre et aligné sur `origin/main` ; aucune pull request ouverte.
- La CI du run de fusion du lot 16 (`45869278272`) est **verte sur les quatre jobs** :
  `Compilation du frontend` (22 s), `Tests Python` (2 min 23 s),
  `Parcours navigateur` (57 s, 14 parcours), `Construction de l'image` (59 s).
- La feuille de route `docs/ameliorations-proposees.md` est **complète** : sections 1
  (correctifs), 2 (garde-fous), 3 (produit) et 4 (performance/exploitation/sécurité).
- Dernier commit : `2d2a918` — « feat: ajouter la detection des incidents sub-horaires (#31) ».
- Le contrat public, la sérialisation UTC, la sécurité HTTP, l'observabilité, la
  rétention, l'alerting et la qualification humaine sont désormais traités.

## 2. Vue d'ensemble par lot

| Lot | Thème | PR / commit | Livrable principal | Vérification marquante |
|---|---|---|---|---|
| 1 | Fiabilité | #4 `ce0d650` | Métriques partitionnées, pagination, UTC, broker, curation bornée, RPKI vectorisée | `abrip demo verify` 5/5 ; rappel 1.0 |
| 2 | Garde-fous | #4, #13, #14, `cd1def1` | Ruff/CI, couverture 80 %, Vitest, Playwright, audits, Dependabot, Docker, pre-commit | Couverture 81,03 % ; image construite en CI |
| 3 | Schémas typés | #15–#18 | 19 endpoints `dict` → modèles Pydantic | 16 tests de contrat ; UTC `Z` partout |
| 4 | Durcissement HTTP | #19 | `LIKE` échappé, clé en temps constant, en-têtes de sécurité | 40 tests ciblés |
| 5 | Transport HTTP | #20 | gzip, ETag/304, connexions DuckDB par thread | 11 tests dédiés |
| 6 | Accessibilité + CSP | #21 | axe WCAG, contrastes corrigés, CSP de la SPA | 55 violations → 0 |
| 7 | Concurrence | #22 | `scripts/bench/run_charge.py` | 2,2 → 4,3 req/s puis plateau |
| 8 | Rétention | #23 | `etl.retention_days`, `etl purge` | 7 tests dédiés |
| 9 | Observabilité | #24 | `/api/metrics`, `X-Request-ID` | 8 tests Prometheus |
| 10 | Workers | #25 | `--workers`, `api.workers` | re-mesure sans gain sur un cœur |
| 11 | Finitions | #26 | limitation de débit, parcours clavier | 429 + `Retry-After` ; 2 parcours clavier |
| 12 | Alerting | #27 | webhook Slack, déduplication | 6 tests sans réseau |
| 13 | Qualité des données | #28 | `/api/quality` + page React | 3 tests API, budget gzip respecté |
| 14 | Précalcul | #29 | `asn_prefix_stats`, `api.prewarm` | égalité stricte des deux chemins |
| 15 | Qualification L5 | #30 | verdicts, précision, allowlist | 7 tests dédiés |
| 16 | Sub-horaire | #31 | `SubHourWithdrawalDetector` opt-in | 4 tests dédiés |

## 3. Détail des lots

### Lot 1 — Correctifs fonctionnels et fiabilité

- **Persistance des métriques** : colonne temporelle détectée automatiquement
  (`window_start`, sauf `metric_visibility` → `snapshot_ts`) ; écriture d'une
  partition `date=AAAA-MM-JJ` par jour via `_persist` dans
  `src/abrip/analytics/metrics.py`, remplacement atomique et migration des
  anciennes tables plates. `DataAccess` lit `metric_*/**/*.parquet`.
- **Pagination frontend** : `withFilter` remet `offset` à zéro, `withOffset` le
  conserve ; logique extraite dans `frontend/src/lib/searchParams.ts` et
  appliquée à `AsnList.tsx` et `Prefixes.tsx`.
- **UTC** : `ApiModel` et `_serialize_datetimes` (`api/schemas.py`) ajoutent `Z`
  même dans les objets imbriqués ; `parseUtc` (`frontend/src/lib/format.ts`)
  interprète un datetime naïf comme UTC.Les endpoints `dict` ad hoc restaient
  en datetime naïf : réserve close par le lot 3.4.
- **Broker BGPKIT** : `_search_pages` parcourt toutes les pages jusqu'à
  épuisement de `total`, avec `MAX_PAGES` comme garde-fou, déduplication des
  URLs et bascule sur l'archive en cas d'échec.
- **Curation bornée** : `_curate_rib` écrit via `ParquetBatchWriter` dans un
  temporaire puis remplace la partition ; `PchTextDumpParser.parse` lit en flux.
- **RPKI vectorisée** : `compute_rpki_coverage` appelle `validate_frame`, avec
  équivalence explicite vis-à-vis de la validation ligne à ligne.
- **Stabilité des agrégats** (découvert pendant la vérification) :
  `any_value(primary_upstream)` remplacé par `arg_max(..., window_start)` et
  ratios arrondis à 6 décimales, pour supprimer 8 tests d'équivalence
  intermittents.

### Lot 2 — Garde-fous de qualité

- `ruff format --check src tests` et `ruff check src tests` en CI ; 84 fichiers
  vérifiés localement au moment de la mesure.
- Couverture 81,03 % mesurée sur 743 tests ; seuil `fail_under = 80` dans
  `pyproject.toml`, rapport XML publié comme artefact.
- Vitest 5.1.2, 11 tests (`format.test.ts`, `searchParams.test.ts`) ; Playwright
  1.65.1, `playwright.config.ts` démarrant `abrip api serve` sur 8010 et
  `smoke.spec.ts` couvrant quatre parcours avec surveillance des erreurs
  console, exceptions JS et réponses 5xx.
- Dependabot groupé (uv, npm, Actions, Docker) ; `pip-audit` et
  `npm audit --audit-level=high` en CI, sans vulnérabilité.
- Actions GitHub migrées en v7 ; `node:25-slim` écarté (non LTS), `node:22-slim`
  conservé. `recharts 3.11.1` retenu sur décision explicite après écart de la
  3.11.0 : budget gzip porté de 256 000 à **270 000** octets (mesure 259 328).
- `Dockerfile` : `uv sync --locked --no-dev`, utilisateur non-root, healthcheck ;
  image construite et interrogée en CI (Docker absent de la machine locale).
- `.pre-commit-config.yaml` : hooks `local` Ruff lint/format et Mypy via
  `uv run --locked`, sans environnement téléchargé.

### Lot 3 — Schémas de réponse typés partout

Découpage du plus sûr au plus risqué, avec tests de contrat à chaque étape :

- **3.0/3.1** : `EventFacets`, `CountryIndicator`, `AsnNames` (`RootModel` pour
  les clés ASN dynamiques) — PR #15.
- **3.2** : `IncidentOut` (datetimes imbriqués en `Z`) et
  `CountryRelation`/`CountryRelationships` — PR #15.
- **3.3** : huit tableaux/historiques de `asn_explorer.py` — `PrefixRow`,
  `NeighbourRow`, `CountryNeighbourRow`, `RoaHistoryRow`, `RouteHistoryRow`,
  `PeriodRun` / `PeriodPresence`, `DailyObservation` / `DailyPresence`,
  `PrefixFacets` rapatrié dans `api/schemas.py` — PR #16 ; 326 tests, dont 316
  d'équivalence.
- **3.4** : `AsnDetail`, `PrefixDetail`, `EventTimeline` et sous-modèles — PR
  #17 ; 13 tests de contrat, réserve UTC du lot 1 close.
- **3.5** : `PropagationResponse`, `PropagationReplayResponse`,
  `UpstreamsResponse` — PR #18 ; `path_ids` absent au-delà des bornes plutôt
  que `null`, clés dynamiques `as{n}` et timestamps `+00:00` préservés.
- **Décision structurante** : les helpers internes (`_runs`, `_add_statuses`,
  `_node`) restent en `dict` ; le modèle n'est appliqué qu'à la frontière HTTP,
  ce qui préserve les tests d'égalité stricte. `HistoryResponse[T]` générique
  évite la variance de `list[...]` sous mypy.

### Lot 4 — Durcissement HTTP

- `escape_like` (`api/search.py`) échappe `\`, `%` et `_`, avec `ESCAPE '\'` sur
  les quatre filtres SQL de `explore.py`.
- `api_key_matches` hache les deux clés en SHA-256 puis compare avec
  `hmac.compare_digest` ; utilisé par `verify_api_key` et par le middleware qui
  protège `/api/docs` et `/api/openapi.json`.
- En-têtes `nosniff`, `DENY`, `no-referrer` et `Permissions-Policy` sur toutes
  les réponses ; la CSP est volontairement reportée à cause des styles en ligne.

### Lot 5 — Optimisation HTTP

- `GZipMiddleware` avec `GZIP_MIN_SIZE = 1024` : les petites réponses ne sont
  pas compressées.
- ETag faible (SHA-256 du corps JSON) et `Cache-Control: private, no-cache` :
  revalidation à chaque appel, 304 sans corps. Étiquette faible car un même
  JSON peut être compressé ou non. `/api/health` est `no-store` (horodatage
  variable) ; les erreurs n'ont ni ETag ni `Cache-Control`.
- `DataAccess` garde une connexion DuckDB par thread (`threading.local`) :
  pas de verrou global, pas de partage inter-thread interdit par DuckDB.

### Lot 6 — Accessibilité et CSP

- `@axe-core/playwright` 4.14.1 (dev), quatre pages auditées en WCAG 2.0/2.1 A
  et AA. 55 nœuds en échec de contraste ramenés à zéro :
  `--ink-400` `#63819a` → `#526e87` (4,8:1 / 5,2:1) et `--amber` `#b8730f` →
  `#8d580a` (4,7:1 sur fond ambré).
- `SPA_CSP` s'applique **uniquement au HTML de la SPA** : `script-src 'self'`,
  `style-src 'self' 'unsafe-inline'` (styles injectés par Recharts),
  `img-src 'self' data: blob:` (export SVG/PNG), `object-src`, `base-uri`,
  `form-action`, `frame-ancestors` fermés. Swagger UI est exclu, sans quoi ses
  ressources CDN et ses scripts en ligne seraient bloqués.

### Lot 7 — Mesure de concurrence

- `scripts/bench/run_charge.py` : asyncio + httpx, `--users`, `--duration`,
  `--think`, `--json`, découverte d'un préfixe et d'un ASN, préchauffage, puis
  neuf routes en boucle sans cache client. Aucun paquet ajouté.
- Mesures locales (jeu de démonstration, une instance) : 2,2 req/s à 1
  utilisateur (p95 1,25 s), 4,3 req/s à 5 (p95 4,12 s), 4,3 req/s à 10
  (p95 9,39 s). Le script n'est pas joué en CI : les valeurs dépendent de la
  machine, la procédure est reproductible.

### Lot 8 — Rétention des couches dérivées

- `etl.retention_days = 90` s'ajoute à `ingestion.raw_retention_days = 30`.
  Curés et analytiques partagent la même fenêtre pour rester cohérents avec
  les tables journalières.
- `storage/retention.py` ne considère que `date=AAAA-MM-JJ` strictement
  antérieurs au seuil ; noms validés, liens symboliques ignorés.
- `abrip etl purge` simule par défaut ; `--apply` supprime, `--days` réduit la
  fenêtre. Bilan JSON : répertoires, fichiers, octets, lignes de catalogue.
  Les entrées `curated_partitions` correspondantes sont effacées.

### Lot 9 — Observabilité

- `X-Request-ID` : UUID généré ou valeur client courte et sûre, renvoyé dans la
  réponse et propagé dans les logs JSON via `current_request_id` (`ContextVar`).
- `GET /api/metrics` (hors OpenAPI, protégé par la clé API globale) :
  compteur par méthode/**modèle de route**/statut, histogramme à neuf seaux
  cumulatifs, jauges de fichiers/octets/âge par couche. Registre local
  verrouillé, aucun paquet ajouté.
- Erreur corrigée en cours de lot : incrémenter un seul seau par observation,
  sinon les bornes supérieures surcomptaient.

### Lot 10 — Montée en workers

- `abrip api serve --workers N` et `api.workers` / `ABRIP_API__WORKERS`, défaut
  1 ; `--reload` refusé avec plusieurs workers, `--workers 0` rejeté.
- Re-mesure à 4 workers, 10 utilisateurs : 3,6 req/s et p95 8,21 s, contre
  4,3 req/s et 9,39 s avec un worker — **pas de gain** sur cette machine à cœur
  partagé. Chaque worker a son propre cache et ses propres compteurs : un
  scrape `/api/metrics` ne couvre qu'un processus.

### Lot 11 — Finitions de sécurité et clavier

- `api.rate_limit_per_minute` (`0` = désactivé) et fenêtre glissante par adresse
  dans `api/rate_limit.py`, horloge injectable pour les tests. 429 normalisé
  avec `Retry-After`, `/api/health` et `/api/metrics` exemptés, 429 comptés dans
  Prometheus. Limite locale à chaque worker.
- `frontend/e2e/clavier.spec.ts` : onglets ARIA aux flèches/Début/Fin, modale
  ouverte avec Entrée et fermée avec Échap, focus rendu au déclencheur.

### Lot 12 — Alerting opérationnel

- `AlertSettings` : `webhook_url` vide par défaut (aucun envoi), `min_severity`
  `critical`, `dedupe_days` 7, `timeout_seconds` 10.
- `alerting.py` : message lisible (préfixe, résumé, détecteurs, score, date),
  webhook compatible Slack, déduplication par `incident_id` dans `alert_log`
  (avec oubli des entrées anciennes). Un échec réseau est journalisé **sans
  interrompre la détection**.
- Commandes `abrip detect run --notify` et `abrip detect alert --days N`.
- Windows : retrait des fuseaux des colonnes Parquet avant conversion Python
  (tzdata absent localement).

### Lot 13 — Tableau de qualité des données

- `GET /api/quality` (`DataQuality`) : fraîcheur par source depuis le journal
  d'ingestion, dix pays les plus couverts, volume RPKI, collecteurs sans
  archive depuis plus de deux jours. Aucune donnée recalculée ; installation
  vierge couverte.
- Page React « Qualité des données » chargée à la demande, ajoutée à la
  navigation ; types frontend écrits à la main dans `lib/types.ts`.
- Budget gzip mesuré à 253 927 octets, sous la limite de 270 000.

### Lot 14 — Précalcul des endpoints coûteux

- `analytics/precompute.py` produit `asn_prefix_stats` (asn, préfixe, mises à
  jour, première/dernière date, pairs distincts) en une passe DuckDB à mémoire
  bornée, écriture atomique et journalisation dans le catalogue.
- `/api/asns/{asn}` lit la table si elle est plus récente que toutes les
  partitions curées, sinon retombe sur le regroupement direct de
  `bgp_elements`. Réponse identique, vérifiée sur la démo.
- `abrip analytics precompute`, à relancer après chaque curation.
- `api.prewarm` / `ABRIP_API__PREWARM=true` remplit le cache de la synthèse
  7 jours au démarrage de chaque worker : le coût est déplacé, pas supprimé.

### Lot 15 — Qualification humaine L5

- Table `event_feedback` (`event_id`, verdict, auteur, note, horodatage) avec
  validation des quatre verdicts ; aucune écriture depuis l'API.
- `abrip detect label`, `abrip detect precision` (précision = 1 − légitimes /
  qualifiés, `unknown` exclu) et `abrip detect allowlist`.
- `configs/allowlist.yaml` versionné, chargé/validé par `qualification.py` et
  appliqué aux alertes (préfixe, ASN, détecteur facultatif).

### Lot 16 — Détection sub-horaire

- `SubHourWithdrawalDetector` regroupe les retraits en fenêtres de 15 minutes,
  exige un pic ≥ 6 peers avec ratio 3 sur la fenêtre précédente, puis un retour
  à la normale dans l'heure. L'événement porte fenêtre, durée, pairs et
  bascule en `evidence`.
- Enregistré dans `DETECTORS`, configuré dans `configs/detection.yaml`,
  **désactivé par défaut** : calibration requise sur des données réelles avant
  activation.

## 4. Matrice de vérification finale

| Contrôle | Résultat | Où |
|---|---|---|
| CI frontend + budget | 4 jobs verts ; bundle < 270 000 octets gzip | run `45869278272` |
| CI Python | ruff check, format, mypy, audits, tests, couverture > 80 % | idem |
| Parcours navigateur | 14 (5 accessibilité axe, 7 smoke, 2 clavier) | idem |
| Image Docker | build + démarrage + requête | idem |
| `abrip demo verify` | rappel 1.0, 5/5 | lots 1 et 2 |
| Contrat API | 16 tests de contrat, schémas OpenAPI explicites | lot 3 |
| Sécurité HTTP | en-têtes, CSP, clé temps constant, LIKE échappé, 429 | lots 4, 6, 11 |
| Observabilité | ETag/304, Prometheus, `X-Request-ID` | lots 5, 9 |
| Données | purge simulée, précalcul équivalent, `/api/quality` | lots 8, 13, 14 |
| Détection | 316 tests d'équivalence des tables journalières, 4 tests sub-horaires | lots 1, 16 |
| Qualification | 7 tests verdicts/précision/allowlist | lot 15 |

La suite complète a été mesurée à **743 tests / 81,03 %** au lot 2 puis à
**802 tests / 83,89 %** au lot 9 ; les ajouts suivants (lots 10 à 16) passent
en CI dans le job Python, sans nouvelle mesure de couverture publiée ici.

## 5. Décisions structurantes et compromis

1. **Contrat stable avant tout** : pas de renommage de clés JSON, pas de `null`
  introduit là où une clé était absente (`path_ids`, `observations`,
  `member_asn`). Les modèles distincts reproduisent les unions conditionnelles.
2. **UTC explicite** : `Z` pour tous les champs `datetime` typés ; les `ts` de
  propagation restent des chaînes `+00:00` attendues par les tests et le
  frontend.
3. **Cache revalidation plutôt que fraîcheur forcée** : `private, no-cache`
  évite de servir des données périmées 60 secondes, tout en économisant les
  octets via 304. `/health` est `no-store`.
4. **État local par worker** : connexions DuckDB, compteurs Prometheus et
  limitation de débit sont thread-local ou process-local ; aucun verrou global,
  mais un scrape ne résume qu'un processus.
5. **Suppressions explicites** : aucune purge automatique ; `etl purge` simule
  par défaut et n'efface qu'avec `--apply`.
6. **CSP ciblée** : appliquée au HTML de la SPA uniquement, pour ne pas casser
  Swagger UI ; `style-src 'unsafe-inline'` assumé à cause des styles injectés.
7. **Bascule en repli** : les optimisations (tables journalières, précalcul)
  sont conditionnées à leur fraîcheur ; l'API retombe sur le calcul direct
  plutôt que de renvoyer une erreur.
8. **Opt-in pour le risque** : détecteur sub-horaire, workers multiples,
  préchauffage, limitation de débit et alertes restent désactivés par défaut.

## 6. Référence des commandes introduites

| Commande | Rôle | Lot |
|---|---|---|
| `abrip etl purge [--days N] [--apply]` | Purger les couches curées/analytiques | 8 |
| `abrip api serve --workers N` | Multi-processus | 10 |
| `abrip detect alert --days N` | Envoyer les alertes d'incidents | 12 |
| `abrip detect run --notify` | Alerter après détection | 12 |
| `abrip analytics precompute` | Construire `asn_prefix_stats` | 14 |
| `abrip detect label <id> --verdict ...` | Qualifier un événement | 15 |
| `abrip detect precision` | Précision par détecteur | 15 |
| `abrip detect allowlist` | Afficher les exemptions | 15 |
| `python scripts/bench/run_charge.py ...` | Test de charge | 7 |

## 7. Référence des réglages ajoutés

| Réglage | Défaut | Effet | Lot |
|---|---|---|---|
| `etl.retention_days` | 90 | Fenêtre de purge curés/analytiques | 8 |
| `api.workers` | 1 | Processus uvicorn | 10 |
| `api.rate_limit_per_minute` | 0 | Limite par adresse (0 = off) | 11 |
| `api.prewarm` | false | Préchauffage de la vue d'ensemble | 14 |
| `alerts.webhook_url` | null | Webhook Slack/générique | 12 |
| `alerts.min_severity` | critical | Seuil d'alerte | 12 |
| `alerts.dedupe_days` | 7 | Fenêtre de déduplication | 12 |
| `detection.detectors.subhour_withdrawal.enabled` | false | Détecteur 15 min | 16 |

Variables d'environnement associées : `ABRIP_ETL__RETENTION_DAYS`,
`ABRIP_API__WORKERS`, `ABRIP_API__RATE_LIMIT_PER_MINUTE`, `ABRIP_API__PREWARM`,
`ABRIP_ALERTS__WEBHOOK_URL`, `ABRIP_ALERTS__MIN_SEVERITY`,
`ABRIP_ALERTS__DEDUPE_DAYS`.

## 8. Réserves et suites possibles

1. **Calibrer `subhour_withdrawal`** sur de vraies archives avant activation :
   `window_minutes`, `min_peers` et `ratio` ont été choisis sans vérité terrain.
2. **Re-mesurer le précalcul à 50 M de lignes** : l'égalité des réponses est
   vérifiée, le gain de temps ne l'est pas encore au volume cible.
3. **Poursuivre la qualification humaine** : l'outillage L5 est prêt, mais sans
   opérateur pour qualifier les événements, la précision reste non mesurée sur
   des données réelles.
4. **Surveiller la limite de concurrence** : mono-processus et DuckDB monocœur
   plafonnent le débit vers 4 req/s sur la machine de mesure ; la montée en
   workers n'a pas apporté de gain local.

## 9. Chronologie des fusions

```
ce0d650  #4   fiabilité, pagination, garde-fous (2026-11-25)
cd1def1       documentation de l'image Docker
3ce622c..c24f5e6  Dependabot Python et Actions v7
cfba9b0       react-router-dom 7.18.6
54e5b87       compte rendu Dependabot
4619fe9  #13  smoke test navigateur
292e4bf  #14  recharts 3.11.1, budget 270 000
604f4c0  #15  schémas 3.0–3.2
3f56838  #16  schémas 3.3
0158c6e  #17  schémas 3.4
669fe87  #18  schémas 3.5 (propagation)
bcdbf2b  #19  durcissement HTTP
650863a  #20  optimisation HTTP
7c17079  #21  accessibilité et CSP
6a71793  #22  test de charge
002c0fb  #23  rétention
d2599f4  #24  observabilité
e8d3182  #25  workers
697933b  #26  limitation de débit et clavier
8f825a0  #27  alerting
9a72ee9  #28  qualité des données
c6c0f9d  #29  précalcul
f393eca  #30  qualification L5
2d2a918  #31  détection sub-horaire
```
