# Guide de déploiement

La plateforme se déploie gratuitement et sans modification du code. Trois propriétés le permettent :

- **aucune base de données externe** — les données sont des fichiers Parquet lus par DuckDB ;
- **un seul processus** — FastAPI sert à la fois l'API et le frontend compilé ;
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

Quel que soit l'hébergeur, ces quatre appels valident le déploiement :

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
```

Si `/api/health` renvoie des couches `present: false`, la génération du jeu de démonstration a échoué pendant la construction. Les journaux de build le montrent : l'étape `abrip demo verify` échoue bruyamment plutôt que de laisser passer une image vide.

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
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
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
          echo "Total compressé : $((TAILLE / 1024)) Ko"
          test "$TAILLE" -lt 256000
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
