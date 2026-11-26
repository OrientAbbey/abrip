# Guide de déploiement

La plateforme se déploie gratuitement et sans modification du code. Trois propriétés le permettent :

- **aucune base de données externe** — les données sont des fichiers Parquet lus par DuckDB ;
- **un seul processus par défaut** — FastAPI sert à la fois l'API et le frontend compilé (la montée en workers reste optionnelle) ;
- **un jeu de données de 3,4 Mo** — il tient dans l'image, donc aucun volume persistant n'est nécessaire.

Ce guide couvre trois hébergements gratuits, du plus adapté au moins adapté, puis l'automatisation du déploiement.

---

## Choisir son hébergeur

| Hébergeur | Gratuit | RAM | Mise en veille | Verdict |
|---|---|---|---|---|
| **Hugging Face Spaces** | oui, sans carte bancaire | 16 Go | non (reste allumé) | **recommandé** |
| **Render** | oui, sans carte bancaire | 512 Mo | après 15 min d'inactivité, ~50 s au réveil | bonne alternative |
| **Fly.io** | crédit gratuit, carte requise | 256 Mo à 1 Go | configurable | si vous avez déjà un compte |

Hugging Face Spaces est le meilleur choix ici : il accepte un `Dockerfile` quelconque, ne met pas le service en veille, et offre 16 Go de mémoire — largement au-dessus du besoin, ce qui laisse la possibilité de charger des données réelles et non seulement le jeu de démonstration.

---

## Option A — Hugging Face Spaces (recommandé)

### 1. Préparer le dépôt

Un Space Docker lit un fichier `README.md` dont l'en-tête YAML configure l'espace. Créez `deploy/huggingface/README.md` :

```markdown
---
title: ABRIP - Routage BGP africain
emoji: 🛰️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
---

Observation du routage inter-domaines africain : visibilité des préfixes,
dépendance au transit et détection d'anomalies expliquées.
```

Le champ `app_port: 7860` doit correspondre au port exposé par le `Dockerfile`, qui vaut déjà 7860 par défaut.

### 2. Créer le Space

Sur [huggingface.co/new-space](https://huggingface.co/new-space) : nom du space, **SDK : Docker**, template **Blank**, visibilité publique, matériel **CPU basic (gratuit)**.

### 3. Pousser le code

```bash
# Le Space est un dépôt git ordinaire
git remote add space https://huggingface.co/spaces/<votre-compte>/<nom-du-space>

# Le README du Space doit être à la racine pour être lu par la plateforme
cp deploy/huggingface/README.md README-space.md
git mv README.md README-projet.md && git mv README-space.md README.md
git commit -am "Déploiement Space"
git push space main
```

Si vous préférez ne pas renommer le README du projet, créez un dépôt séparé pour le Space, contenant uniquement le `Dockerfile`, un `README.md` avec l'en-tête ci-dessus, et une ligne `FROM` pointant vers une image publiée — voir la section CI plus bas.

### 4. Vérifier

La construction prend 5 à 8 minutes : compilation du frontend, installation Python, génération du jeu de démonstration. Les journaux sont visibles dans l'onglet **Logs**.

Une fois en ligne :

```bash
curl https://<votre-compte>-<nom-du-space>.hf.space/api/health
```

La réponse doit lister les couches `bgp_elements`, `metric_*` et `events` en `present: true`.

### 5. Variables d'environnement

Dans **Settings → Variables and secrets** :

| Variable | Valeur | Rôle |
|---|---|---|
| `ABRIP_API__CORS_ORIGINS` | `[]` | inutile : le frontend est servi par la même origine |
| `ABRIP_LOG_LEVEL` | `INFO` | passez à `WARNING` pour alléger les journaux |
| `ABRIP_LOG_FILE` | `logs/abrip.log` | journal JSON, relatif à `ABRIP_DATA_DIR` ; rotation `ABRIP_LOG_MAX_BYTES` (10 Mo) × `ABRIP_LOG_BACKUP_COUNT` (5) |
| `ABRIP_INGESTION__ARCHIVE_ROOT` | JSON, ex. `{"routeviews": "https://miroir…", "riperis": "…", "pch": "…"}` | changer de miroir d'archives sans toucher au code (donner les trois projets) |

Aucune n'est obligatoire : l'image démarre correctement sans configuration.

---

## Option B — Render

### 1. Fichier de configuration

Créez `render.yaml` à la racine :

```yaml
services:
  - type: web
    name: abrip
    runtime: docker
    plan: free
    dockerfilePath: ./Dockerfile
    healthCheckPath: /api/health
    envVars:
      - key: ABRIP_LOG_LEVEL
        value: INFO
```

Render injecte lui-même la variable `PORT`, que le `Dockerfile` consomme déjà.

### 2. Déployer

Sur [dashboard.render.com](https://dashboard.render.com) : **New → Blueprint**, sélectionnez le dépôt, Render lit `render.yaml` et construit l'image.

### 3. Contrainte à connaître

Le plan gratuit limite la mémoire à **512 Mo** et met le service en veille après 15 minutes sans requête. Le premier appel après une veille prend une cinquantaine de secondes.

L'API seule tient largement dans 512 Mo puisqu'elle ne fait que lire des Parquet. En revanche, **n'exécutez pas le pipeline ETL sur ce plan** : la curation d'une journée réelle dépasse cette limite. Le jeu de démonstration, lui, est généré pendant la construction de l'image, où la mémoire disponible est plus élevée.

Pour atténuer la mise en veille, un ping externe gratuit (UptimeRobot, cron-job.org) toutes les 10 minutes sur `/api/health` suffit.

---

## Option C — Fly.io

```bash
fly launch --no-deploy --name abrip
```

Puis dans le `fly.toml` généré :

```toml
[http_service]
  internal_port = 7860
  force_https = true
  auto_stop_machines = "suspend"
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  memory = "512mb"
  cpu_kind = "shared"
  cpus = 1

[checks.health]
  type = "http"
  path = "/api/health"
  interval = "30s"
  timeout = "5s"
```

```bash
fly deploy
```

Fly demande une carte bancaire même pour rester dans l'enveloppe gratuite, ce qui en fait le dernier choix des trois.

---

## Vérifier un déploiement

Quel que soit l'hébergeur, ces appels valident le déploiement :

```bash
BASE=https://votre-instance

# 1. Les couches de données sont présentes
curl -s $BASE/api/health | python -m json.tool

# 2. Des événements ont été détectés
curl -s "$BASE/api/events?limit=3" | python -m json.tool

# 3. Le frontend est servi
curl -sI $BASE/ | head -1          # doit répondre 200 et du HTML

# 4. Le routage côté client fonctionne après rechargement
curl -sI $BASE/events | head -1    # doit aussi répondre 200, pas 404

# 5. Les noms d'AS (AS2Org) sont servis, et le graphe de propagation répond
curl -s $BASE/api/asns/names | head -c 200
curl -s "$BASE/api/prefixes/197.155.64.0%2F22/propagation" | head -c 200
```

Un `/api/health` qui répond `degraded` signale l'absence de `bgp_elements` ou d'`events` : la route répond quand même (HTTP 200), c'est son rôle. Si `/api/health` renvoie des couches `present: false`, la génération du jeu de démonstration a échoué pendant la construction. Les journaux de build le montrent : l'étape `abrip demo verify` échoue bruyamment plutôt que de laisser passer une image vide.

---

## Automatiser avec GitHub Actions

Créez `.github/workflows/ci.yml` :

```yaml
name: CI

on:
  push: { branches: [main] }
  pull_request:

jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: ruff check src tests
      - run: mypy src
      # Le pipeline complet avant les tests : les tests de non-régression
      # exigent des données produites, pas simulées.
      - run: abrip demo bootstrap
      - run: abrip demo verify
      - run: pytest -q

  frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: frontend } }
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm run build
      # Le budget de bundle fait partie du contrat : on le vérifie.
      - name: Vérifier le budget de bundle
        run: |
          TAILLE=$(find dist/assets -name '*.js' -o -name '*.css' \
            | xargs gzip -c | wc -c)
          echo "Total compressé : $TAILLE octets"
          test "$TAILLE" -le 270000
```

Pour pousser automatiquement vers Hugging Face à chaque `main`, ajoutez un secret `HF_TOKEN` (jeton avec droit d'écriture, créé dans les paramètres Hugging Face) et ce job :

```yaml
  deploy:
    needs: [python, frontend]
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - name: Pousser vers le Space
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
        run: |
          git push --force \
            https://user:$HF_TOKEN@huggingface.co/spaces/<compte>/<space> main
```

---

## Construire et tester l'image en local

```bash
docker build -t abrip .
docker run --rm -p 8000:7860 -e PORT=7860 abrip
# http://localhost:8000
```

L'étape `abrip demo verify` s'exécute pendant la construction : si la détection ne retrouve pas les cinq anomalies plantées, l'image ne se construit pas. Un déploiement ne peut donc pas partir avec une détection cassée.

---

## Passer aux données réelles

Le jeu de démonstration convient à une démonstration publique. Pour des données réelles :

```bash
# Sur une machine disposant de mémoire (poste local, VM, runner CI)
abrip reference sync --sources afrinic,rpki,caida
abrip ingest broker --from 2026-08-01 --to 2026-08-07
abrip etl curate  --from 2026-08-01 --to 2026-08-07
abrip analytics compute --from 2026-08-01 --to 2026-08-07
abrip detect run --from 2026-08-01 --to 2026-08-07
```

### Mise à jour d'une installation existante

Les partitions `bgp_elements` sont triées par (prefix, ts) à l'écriture depuis la
version qui introduit `etl.sort_partitions`. Celles déjà écrites ne le sont pas, et
portent `collector` en `Categorical` : polars refuse de lire ensemble les deux
formes. Après la mise à jour, une seule fois :

```bash
abrip etl compact        # trie les anciennes partitions ; idempotent
abrip analytics compute --from <premier jour> --to <dernier jour>   # tables journalières
```

La seconde commande produit les tables journalières (`daily_prefix_origin`,
`daily_adjacency`) qui rendent rapides les pages par AS et la liste des préfixes. Sans
elles — ou après une nouvelle curation, qui les rend périmées — l'API répond quand même,
par le calcul direct, plus lent mais identique.

Détails et mesures : [performances.md](performances.md).

### Rétention des couches dérivées

La couche brute est purgée par `abrip ingest purge` (30 jours par défaut). Les
Parquet curés et analytiques sont conservés `etl.retention_days` jours (90 par
défaut, réglable dans `configs/settings.yaml`). La purge n'est **jamais**
automatique : on simule, puis on applique.

```bash
abrip etl purge                 # simulation : partitions, fichiers, octets et lignes de catalogue
abrip etl purge --apply         # suppression effective
abrip etl purge --days 30 --apply   # fenêtre ponctuellement plus courte
```

Seuls les répertoires `date=AAAA-MM-JJ` antérieurs à la date limite sont
supprimés, avec les entrées correspondantes du catalogue. Les deux couches
partagent la même fenêtre : garder moins de jours curés que de jours analytiques
ferait recalculer directement certaines pages, plus lentement. La compaction
reste assurée par `abrip etl compact` (tri et fusion des fragments en un seul
fichier par partition), à relancer après une curation d'anciennes dates.

### Observabilité

`GET /api/metrics` expose au format Prometheus (sous la clé API si elle est
configurée) : compteurs et histogramme de latence par modèle de route, ainsi que
le nombre d'octets et l'âge de la partition la plus récente pour chaque couche.
Les libellés utilisent le **modèle** de route (`/api/asns/{asn}`), pas l'URL
réelle, pour borner la cardinalité.

```yaml
scrape_configs:
  - job_name: abrip
    metrics_path: /api/metrics
    static_configs:
      - targets: ["127.0.0.1:8000"]
```

Chaque réponse porte un en-tête `X-Request-ID` (UUID généré, ou valeur reçue
dans la requête si elle est courte et sans caractère suspect). Le même
identifiant est ajouté aux logs JSON sous `request_id`, ce qui permet de passer
d'une alerte à la trace d'une requête.

### Montée en workers

`abrip api serve --workers 4` lance quatre processus uvicorn ; la variable
`ABRIP_API__WORKERS=4` fait de même sans changer la commande. Le défaut reste
`1` : avec un seul processus, le cache en mémoire et les index RPKI/IRR sont
partagés entre toutes les requêtes. `--reload` est réservé au développement et
est incompatible avec plusieurs workers.

Attention : chaque worker possède **son propre cache et ses propres compteurs
Prometheus**. Un scrape de `/api/metrics` ne voit qu'un seul worker ; les
chiffres sont des indicateurs par processus, pas un total agrégé. Sur une
machine à un cœur, la montée en workers n'apporte pas de gain de débit (voir
`docs/performances.md`) : mesurer avant de changer le réglage.

### Premier essai réel : un collecteur, un jour

Le parcours sur données réelles n'a pas pu être exécuté de bout en bout par les auteurs : l'environnement de développement n'atteint ni RouteViews, ni RIPE, ni IODA, ni PeeringDB. Ce qui est vérifié, c'est le comportement **quand les sources sont injoignables** (tests `tests/test_hors_demo.py` et essai manuel) ; ce qui ne l'est pas, c'est le succès sur de vraies archives. Commencez petit, depuis un poste qui a accès à Internet :

```bash
export ABRIP_DATA_DIR=./data-reel            # ne mélange pas avec la démonstration
abrip ingest broker --from AAAA-MM-JJ --to AAAA-MM-JJ --collectors rrc19 --dry-run
abrip ingest broker --from AAAA-MM-JJ --to AAAA-MM-JJ --collectors rrc19   # un jour d'updates
abrip reference sync --sources afrinic,rpki,caida
abrip etl curate --from AAAA-MM-JJ --to AAAA-MM-JJ
abrip analytics compute --from AAAA-MM-JJ --to AAAA-MM-JJ
abrip detect run --from AAAA-MM-JJ --to AAAA-MM-JJ
abrip ingest ris-live --duration 30          # flux temps réel, 30 secondes
```

Points à contrôler, dans l'ordre : le nombre de fichiers téléchargés (`downloaded`) ; des lignes dans `ref_asn`, `ref_roa` et `ref_as_rel` ; un `abrip demo verify` **ne s'applique pas** (il vérifie la vérité terrain de la démonstration) — regardez plutôt `/api/health` et les événements produits. Le parseur PCH n'a été testé que sur un échantillon synthétique : tout écart de format apparaîtra dans le journal.

Quand une source ne répond pas, les commandes le disent plutôt que de réussir en silence : `abrip reference sync` et `abrip ingest broker` sortent avec le code 1 si rien n'a pu être récupéré, et le journal (`data/logs/abrip.log`) donne pour chaque échec le type d'erreur, la méthode, l'URL et le statut HTTP éventuel :

```bash
jq 'select(.level == "WARNING") | {message, error_type, method, url, status_code}' data/logs/abrip.log
```

Deux façons de publier le résultat, selon le volume :

**Données légères (< 100 Mo)** — copiez `data/` dans l'image en remplaçant l'étape `abrip demo bootstrap` du `Dockerfile` par `COPY data/ ./data/`. Le déploiement reste un simple `docker build`.

**Données plus volumineuses** — publiez `data/` comme *dataset* Hugging Face (gratuit, jusqu'à plusieurs Go) et téléchargez-le au démarrage du conteneur, avant de lancer le service. La variable `ABRIP_DATA_DIR` permet de pointer ailleurs que dans le répertoire du projet, y compris vers un volume monté.

Dans les deux cas, l'API reste inchangée : elle ne sait pas d'où viennent les fichiers qu'elle lit.

---

## Sécurité

L'API est en lecture seule et n'expose aucune donnée personnelle — uniquement des informations de routage publiques. Un déploiement public ne présente donc pas de risque particulier.

Si vous souhaitez malgré tout la restreindre, le champ `api.api_key` de `configs/settings.yaml` active une vérification de clé par en-tête, sans modification de code :

```bash
ABRIP_API__API_KEY=une-valeur-longue-et-aleatoire
```

Le frontend devra alors transmettre cet en-tête — ce qui n'a de sens que pour un usage interne, une clé embarquée dans une page publique n'étant pas un secret.
