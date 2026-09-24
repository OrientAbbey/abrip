# Image en deux étapes : le frontend est compilé dans un conteneur Node, puis
# seuls les fichiers statiques produits passent dans l'image Python. L'image
# finale ne contient donc ni Node, ni node_modules, ni sources TypeScript.

# --- étape 1 : compilation du frontend --------------------------------------
FROM node:22-slim AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- étape 2 : application ---------------------------------------------------
FROM python:3.12-slim

# Pas de fichiers .pyc, sortie non tamponnée pour que les journaux
# apparaissent en direct dans la console de l'hébergeur.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ABRIP_DATA_DIR=/app/data

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY configs/ ./configs/
COPY --from=frontend /build/dist ./frontend/dist

# Le jeu de démonstration est généré à la construction : l'image démarre avec
# des données, sans téléchargement ni volume à monter. Environ 3 Mo.
RUN abrip demo bootstrap && abrip demo verify

# Un utilisateur non privilégié : plusieurs hébergeurs le refusent autrement,
# et rien ici n'a besoin de root.
RUN useradd --create-home --uid 1000 abrip && chown -R abrip:abrip /app
USER abrip

# 7860 est le port attendu par Hugging Face Spaces ; les autres hébergeurs
# injectent leur propre valeur dans PORT.
ENV PORT=7860
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health')"

# Forme shell volontaire : il faut que $PORT soit résolu au démarrage.
CMD abrip api serve --host 0.0.0.0 --port ${PORT}
