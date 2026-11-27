"""Manifest des fichiers Parquet servis en HTTPS.

Le service n'a pas de disque persistant : un workflow publie les Parquet et un
`manifest.json` sur un dataset Hugging Face. `DataAccess` lit ce manifeste pour
construire des expressions `read_parquet([...])` que DuckDB peut interroger en
range requests, sans télécharger les fichiers.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx

MANIFEST_NAME = "manifest.json"


def file_url(base_url: str, path: str) -> str:
    """Construit l'URL d'un fichier du dataset, en échappant les segments."""
    return f"{base_url.rstrip('/')}/{quote(path.lstrip('/'), safe='/=+-._')}"


def load_manifest(base_url: str, token: str | None = None) -> dict[str, list[str]]:
    """Récupère `{"tables": {"<table>": ["chemin/relatif.parquet", ...]}}`."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=30.0) as client:
        response = client.get(file_url(base_url, MANIFEST_NAME), headers=headers)
        response.raise_for_status()
        payload = response.json()
    tables = payload.get("tables", {}) if isinstance(payload, dict) else {}
    if not isinstance(tables, dict):
        return {}
    return {
        str(name): [file_url(base_url, str(path)) for path in paths]
        for name, paths in tables.items()
        if isinstance(paths, list)
    }
