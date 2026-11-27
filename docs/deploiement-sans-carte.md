# Déploiement 100 % cloud, sans carte bancaire — étude novembre 2026

Contexte : héberger ABRIP avec de vraies données BGP, **sans aucun moyen de paiement utilisable** (carte virtuelle de 1 000 FCFA refusée par Oracle) et **sans qu'aucune étape ne passe par la machine de l'utilisateur**. Ce document remplace la version précédente, qui supposait que le pipeline tourne en local.

## 1. Ce qui est exclu

| Service | Raison |
|---|---|
| **Oracle Cloud Always Free** | Carte physique obligatoire ; refus explicite des cartes virtuelles/prépayées |
| **Google Cloud / Cloud Run** | Compte de facturation obligatoire ; cartes virtuelles refusées |
| **Koyeb Free** | Pré-autorisation de 29 $ à l'inscription |
| **Fly.io Free** | $5/mois avec carte ; l'essai sans carte se limite à 1 $ / 7 jours et 5 min par machine |
| **Hugging Face Spaces compute / Jobs** | Spaces Docker/Gradio exigent PRO/Team ; HF Jobs exigent un solde créditeur positif |
| **PythonAnywhere Free** | 512 Mo de disque, sortie Internet filtrée, 100 CPU-s/jour |

Sources : [Oracle FAQ](https://www.oracle.com/cloud/free/faq/), [Google signup troubleshooting](https://docs.cloud.google.com/support/docs/troubleshoot-signup), [Koyeb Pricing FAQ](https://www.koyeb.com/docs/faqs/pricing), [Fly.io Free Plan](https://docs.fly.io/about/free-plan), [HF Jobs pricing](https://huggingface.co/docs/hub/en/jobs-pricing), [PythonAnywhere Free](https://help.pythonanywhere.com/pages/FreeAccountsFeatures).

## 2. Les briques gratuites retenues

| Brique | Service | Gratuité | Rôle |
|---|---|---|---|
| Pipeline ETL | **GitHub Actions** (cron) | Minutes gratuites et illimitées sur dépôt public ; 2 000 min/mois sur dépôt privé | Télécharger MRT, curer, calculer, détecter, précalculer |
| Stockage des données | **Hugging Face Hub** | 100 Go privés ou stockage public « best-effort », egress inclus | Publier les Parquet et le catalogue |
| API | **Render Free web service** | 512 Mo RAM, mise en veille après 15 min | Exécuter `abrip api serve` |
| Frontend | GitHub Pages / Vercel / Netlify | Statique gratuit | Servir `frontend/dist` |
| Réveil du service | GitHub Actions cron + requête HTTP | Gratuit | Éviter la mise en veille si nécessaire |

Sources : [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage), [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), [HF storage limits](https://huggingface.co/docs/hub/en/storage-limits), [Render Free](https://render.com/docs/free).

### Pourquoi GitHub Actions convient au pipeline

- Runner Linux public : **4 vCPU / 16 Go de RAM / 14 Go de SSD**, sans limite de minutes facturées.
- Runner privé : 2 vCPU / 8 Go / 14 Go, avec 2 000 min/mois gratuites.
- Chaque job peut tourner jusqu'à **6 heures** ; un cron quotidien suffit largement.
- Le runner a un accès Internet sortant : `abrip ingest broker` peut télécharger les archives MRT directement depuis RouteViews/RIPE RIS.
- Les secrets (token Hugging Face, clé API, webhook) sont stockés dans **GitHub Secrets**, gratuitement.

Le disque de 14 Go impose de **traiter jour par jour** et de supprimer les MRT bruts après curation de chaque date (pas de rétention de 30 jours sur le runner) : 1–15 Go de téléchargement, puis quelques centaines de Mo de Parquet à publier.

## 3. Architecture retenue

```
GitHub Actions (cron quotidien, 03:00 UTC)          GitHub Actions (cron /10 min)
  └─ uv sync --locked                                 └─ curl /api/health (réveil Render)
  └─ ABRIP_DATA_DIR=$RUNNER_TEMP/data
  └─ abrip ingest broker --type updates
  └─ abrip etl curate  (jour par jour, raw supprimé)
  └─ abrip analytics compute
  └─ abrip detect run --notify
  └─ abrip analytics precompute
  └─ huggingface_hub upload → dataset HF (privé ou public)
                    │
                    ▼
Render Free  ── start.sh ──► télécharge le dataset HF dans ABRIP_DATA_DIR
             └─ abrip api serve --host 0.0.0.0 --port $PORT
                    │
                    ▼
GitHub Pages / Vercel : frontend statique
```

**Aucune commande ne s'exécute sur ton poste.**

### Variante A — recommandée pour démarrer

`start.sh` télécharge le dataset depuis HF avec `huggingface_hub.snapshot_download` (token en variable d'environnement si le dataset est privé), puis lance l'API existante sans modification du code applicatif. Le jeu doit rester léger (< 100–150 Mo) car il est re-téléchargé à chaque réveil du service.

### Variante B — évolution

Adapter `DataAccess` pour que DuckDB lise les Parquet du dataset HF en HTTPS avec `httpfs` (range requests) : plus de téléchargement complet au démarrage, mais des changements de code et des tests. Utile si le volume dépasse ~150 Mo. Le token HF peut être transmis comme en-tête HTTP pour un dataset privé, ou le dataset peut rester public.

Sources : [DuckDB HTTP(S)/httpfs](https://duckdb.org/docs/1.4/core_extensions/httpfs/https).

## 4. Workflow complet

1. **Workflow GitHub Actions `.github/workflows/pipeline.yml`** : déclenché par `schedule` (cron) et `workflow_dispatch`.
   - checkout du dépôt, `uv sync --locked`, `ABRIP_DATA_DIR=$RUNNER_TEMP/data` ;
   - `abrip ingest broker --from … --to … --type updates` avec les collecteurs choisis ;
   - `abrip etl curate` par jour, puis suppression des fichiers `raw/` du jour ;
   - `abrip analytics compute`, `abrip detect run --notify`, `abrip analytics precompute` ;
   - `huggingface_hub.upload_folder` vers `<compte>/abrip-data` avec `HF_TOKEN` ;
   - `abrip etl purge --days 90 --apply` si un historique plus long est conservé sur le runner (inutile si `data/` est recreated à chaque run).
2. **Dataset Hugging Face** `<compte>/abrip-data` : privé (100 Go gratuits) avec un token en lecture seule pour Render, ou public si les données peuvent être ouvertes.
3. **Service Render** : Dockerfile existant, avec une commande de démarrage qui appelle `start.sh` ; variables `ABRIP_DATA_DIR`, `HF_TOKEN`, `ABRIP_API__API_KEY`, `ABRIP_API__RATE_LIMIT_PER_MINUTE`, `ABRIP_LOG_LEVEL`.
4. **Frontend** : `npm run build` puis publication de `frontend/dist` sur GitHub Pages/Vercel. Si le frontend est sur un autre domaine que l'API, renseigner `ABRIP_API__CORS_ORIGINS`.
5. **Réveil** : un second workflow GitHub Actions appelle `/api/health` toutes les 10 minutes pour éviter la mise en veille de 15 minutes de Render.

## 5. Limites acceptées

- **14 Go de disque sur le runner** : traiter par jour et supprimer les MRT après curation ; ne pas activer la rétention brute de 30 jours sur le runner.
- **6 h par job** : suffisant pour quelques jours de données ; pour un mois, découper en plusieurs exécutions.
- **Render Free** : 512 Mo, veille après 15 min, système de fichiers éphémère.
- **Pas d'écritures persistantes côté API** : `event_feedback`, `alert_log` et le catalogue restent sur le runner/Actions ; la qualification L5 est donc à exécuter via le workflow, pas sur le service public.
- **Dataset privé** : nécessite un token HF côté Render ; sans token, le dataset doit être public.
- **Tout est dans le cloud** : ton poste ne sert qu'à consulter le résultat.

## 6. Coût et réseau

| Poste | Coût | Réseau |
|---|---|---|
| GitHub Actions | 0 FCFA | 1–15 Go de MRT entrants sur le runner |
| Hugging Face dataset | 0 FCFA | Upload initial des Parquet ; downloads vers Render |
| Render Free | 0 FCFA | JSON API (~254 Ko gzip pour le frontend) |
| Frontend statique | 0 FCFA | — |
| Carte bancaire | **aucune** | — |

## 7. Plan d'action proposé

1. Créer les comptes GitHub, Hugging Face et Render **sans carte**.
2. Créer le dataset `<compte>/abrip-data` (privé de préférence) et un token HF en lecture/écriture dans les Secrets GitHub, un token en lecture seule dans Render.
3. Ajouter `.github/workflows/pipeline.yml` et `start.sh` (variante A) au dépôt.
4. Déployer sur Render et vérifier `/api/health`, `/api/overview` et les parcours du frontend.
5. Ajouter le workflow de réveil, puis mesurer le trafic HF au réveil ; basculer vers la variante B si le téléchargement devient gênant.
6. Si une carte physique devient disponible plus tard, migrer vers Oracle Cloud : le dataset HF sert alors d'amorçage du volume bloc.

## 8. Fichiers fournis

L'implémentation de la variante B est livrée dans le dépôt :

| Fichier | Rôle |
|---|---|
| `src/abrip/storage/remote.py` | Chargement du `manifest.json` HTTPS et construction des URLs HF |
| `src/abrip/api/deps.py` | Mode distant de `DataAccess` : `httpfs`, secret Bearer, `read_parquet([...])` |
| `scripts/deploy/run_pipeline.py` | Pipeline cloud : ingestion/curation journalières, détection, précalcul, manifeste, publication HF |
| `scripts/deploy/start.sh` | Commande de démarrage du service sur Render |
| `.github/workflows/pipeline.yml` | Cron quotidien (7 derniers jours par défaut) du pipeline |
| `.github/workflows/keep-awake.yml` | Ping `/api/health` toutes les 10 minutes |
| `render.yaml` | Blueprint Render Free avec variables à synchroniser |

Configuration côté GitHub : Secrets `HF_TOKEN`, `ABRIP_ALERTS__WEBHOOK_URL` (optionnel), `ABRIP_HEALTH_URL` ; Variables `HF_DATASET_REPO` (ex. `moncompte/abrip-data`). Le dataset HF peut rester privé : le token sert alors aussi bien à l'upload qu'à la lecture depuis Render.

Configuration côté Render : renseigner `ABRIP_REMOTE_DATA_URL` (`https://huggingface.co/datasets/<compte>/<repo>/resolve/main`), `ABRIP_REMOTE_DATA_TOKEN` (jeton HF en lecture seule) et `ABRIP_API__API_KEY`. La clé API est indispensable dès que le service est public : la limitation de débit et la protection des métriques en dépendent.

Le manifeste publié par le pipeline a la forme :

```json
{"tables": {"bgp_elements": ["curated/bgp_elements/date=2026-11-20/part-00000.parquet"]}}
```

`DataAccess` en mode distant ne consulte aucun fichier local : chaque table exposée devient un `read_parquet([...urls...], union_by_name=true)`. Le mode local reste inchangé et tous les tests existants passent.

## 9. Conclusion

Le couple **GitHub Actions + Hugging Face + Render Free** permet de faire tourner l'intégralité du cycle de vie dans le cloud, gratuitement et sans carte bancaire, y compris l'ingestion des MRT. Aucune étape ne passe par la machine de l'utilisateur : le runner GitHub exécute le pipeline, le dataset HF sert de point d'échange et l'API DuckDB lit les Parquet en HTTPS par range requests. C'est la solution la plus proche d'un déploiement réel dans les contraintes actuelles.
