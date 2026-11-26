# Améliorations proposées pour ABRIP

Ce document conserve l’ensemble des pistes d’amélioration identifiées dans la revue du projet. Les lots 1 à 12 (correctifs, garde-fous, schémas typés, durcissement HTTP, optimisation du transport, accessibilité/CSP, mesure de concurrence, rétention, observabilité, montée en workers, finitions de sécurité et alerting) sont terminés et consignés dans `docs/suivi-modifications.md` ; le reste des points 3 et 4 est à planifier.

## 1. Correctifs fonctionnels et de fiabilité — terminé

- **Conserver l’historique des métriques lors d’un recalcul partiel** (`src/abrip/analytics/metrics.py`, `src/abrip/api/deps.py`) : partitionner les sorties par jour afin qu’un calcul quotidien ne remplace pas les métriques calculées précédemment pour d’autres jours.
- **Réparer la pagination de la liste des AS** (`frontend/src/pages/AsnList.tsx`) : ne supprimer `offset` que lorsque l’utilisateur change un filtre, pas lors des actions Précédent/Suivant.
- **Rendre les horodatages UTC sans ambiguïté** (`src/abrip/api/schemas.py`, `frontend/src/lib/format.ts`) : sérialiser les dates avec un indicateur de fuseau (`Z`) et couvrir le formatage par des tests.
- **Récupérer toutes les pages du broker BGPKIT** (`src/abrip/ingestion/broker.py`) : parcourir `page=1…n` jusqu’à la dernière page, sans perdre silencieusement les fichiers au-delà de 1 000 résultats.
- **Borner la mémoire lors de la curation** (`src/abrip/etl/curate.py`, `src/abrip/etl/pch_parser.py`) : écrire les RIB par lots avec `ParquetBatchWriter` et parcourir les relevés PCH en flux plutôt que de charger tout le fichier avec `readlines()`.
- **Accélérer la validation RPKI** (`src/abrip/analytics/metrics.py`, `src/abrip/reference/rpki.py`) : utiliser `validate_frame`, qui déduplique les couples préfixe/origine, au lieu de valider chaque ligne répétée.

## 2. Garde-fous de qualité — terminé

- **Vérifier le formatage Ruff en CI** : ajouter `ruff format --check` au workflow GitHub Actions, en cohérence avec `make lint`.
- **Mesurer la couverture Python** : activer `pytest-cov` en CI, publier un rapport et fixer un seuil initial réaliste pour empêcher les régressions.
- **Ajouter des tests frontend** : mettre en place Vitest pour les fonctions et composants isolables (formatage, graphe, filtres, pagination) et prévoir un smoke test navigateur pour les parcours clés.
- **Automatiser la veille des dépendances** : ajouter Dependabot ou Renovate et une vérification de vulnérabilités adaptée aux dépendances Python et npm.
- **Reproduire l’environnement Python dans l’image Docker** : installer les dépendances à partir de `uv.lock` avec `uv sync --locked`, au lieu de résoudre à nouveau les paquets lors du build.
- **Ajouter des contrôles locaux avant commit** : proposer une configuration pre-commit pour Ruff (lint et format) et Mypy.

## 3. Améliorations produit — à planifier

- **Boucle de qualification humaine L5** (`docs/limites-et-remediations.md`, CLI et interface) : enregistrer les retours sur les événements, fournir `abrip detect label` et `abrip detect precision`, versionner une allowlist et afficher la précision par détecteur. Le rappel mesuré sur les anomalies de démonstration ne suffit pas à mesurer les faux positifs réels.
- **Schémas de réponse typés partout — lot 3 terminé** : les 19 endpoints qui renvoyaient des `dict` ad hoc (statistiques de préfixe, séries DuckDB, fiches, tableaux, historiques, propagation) ont désormais un `response_model` Pydantic explicite. La sérialisation UTC est unifiée via `ApiModel` et les clés conditionnelles du contrat sont préservées. Détail des sous-lots dans `docs/suivi-modifications.md`.
- **Détection sub-horaire** : compléter les détecteurs raisonnant actuellement par jour avec des fenêtres glissantes et des signatures adaptées aux incidents courts.
- **Alerting opérationnel — fait** : webhook compatible Slack pour les incidents au seuil configuré (`critical` par défaut), déduplication par `incident_id` dans le catalogue, commandes `detect run --notify` et `detect alert`. Configuration et échecs non bloquants documentés dans `docs/deploiement.md`.
- **Tableau de qualité des données** : exposer la fraîcheur par source, la couverture par pays, le statut ROA et les collecteurs silencieux à partir des métriques et métadonnées existantes.
- **Métriques d’exploitation — fait** : `/api/metrics` expose compteurs HTTP, histogramme de latence par modèle de route et jauges de taille/fraîcheur des couches ; chaque réponse porte un `X-Request-ID` également présent dans les logs JSON. Configuration de scrape dans `docs/deploiement.md`.

## 4. Performance, exploitation et sécurité — à planifier

- **Réduire les temps de réponse analytiques** (`docs/performances.md`) : cibler la fiche AS et la vue d’ensemble, notamment via des pré-calculs adaptés et le préchauffage du cache.
- **Optimiser l’API — fait** : gzip au-delà de 1 024 octets, ETag faible avec revalidation systématique (304 sans corps), `/api/health` en `no-store`, et une connexion DuckDB par thread réutilisée entre requêtes. Détail dans `docs/performances.md`.
- **Maîtriser la croissance du stockage — fait** : `etl.retention_days` (90 jours) pour les couches curées et analytiques, `abrip etl purge` simulé par défaut (`--apply` pour supprimer), avec nettoyage du catalogue. La compaction des fragments reste assurée par `abrip etl compact`. Procédure dans `docs/deploiement.md`.
- **Mesurer la concurrence — fait** : `scripts/bench/run_charge.py` génère une charge asyncio configurable et rapporte débit et percentiles ; première mesure locale dans `docs/performances.md` (débit plafonnant vers 4,3 req/s sur une instance). La montée en workers reste à étudier.
- **Renforcer les protections HTTP — fait** : clés API comparées en temps constant via `hmac.compare_digest`, en-têtes `nosniff`/`DENY`/`no-referrer`/`Permissions-Policy` sur toutes les réponses, CSP sur le HTML de la SPA (Swagger UI exclu) et limitation de débit configurable (`api.rate_limit_per_minute`, 0 par défaut).
- **Rendre la recherche littérale — fait** : `escape_like` échappe `\`, `%` et `_`, avec `ESCAPE '\'` sur les quatre filtres SQL concernés.
- **Automatiser l’accessibilité frontend — fait** : `axe-core` vérifie quatre pages sur les règles WCAG 2.0/2.1 A et AA dans Playwright ; les 55 problèmes de contraste détectés ont été corrigés. Deux parcours clavier couvrent les onglets ARIA et la modale (focus, Entrée, Échap).

## Références

- `docs/limites-et-remediations.md`
- `docs/performances.md`
- `docs/revue-2026-09-24.md`
- `.github/workflows/ci.yml`
