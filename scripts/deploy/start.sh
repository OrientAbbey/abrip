#!/bin/sh
set -eu

# Démarrage du service sur Render. En mode variante B, les Parquet restent sur
# Hugging Face : ABRIP_REMOTE_DATA_URL suffit, aucun téléchargement local.
PORT="${PORT:-7860}"
export ABRIP_DATA_DIR="${ABRIP_DATA_DIR:-/app/data}"

exec abrip api serve --host 0.0.0.0 --port "$PORT"
