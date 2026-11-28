"""Finalise le dataset Hugging Face après le pipeline parallélisé par jour.

Les jobs journaliers publient les Parquet ; ce script liste les fichiers distants,
construit `manifest.json` et téléverse la carte de données. Il n'y a aucun
téléchargement des Parquet.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

try:
    from scripts.deploy.dataset_card import CARTE_DATASET
except ModuleNotFoundError:  # exécution directe
    from dataset_card import CARTE_DATASET

COUCHES = {"curated", "analytics", "reference"}


def build_manifest(files: list[str]) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for path in sorted(files):
        if not path.endswith(".parquet"):
            continue
        parts = path.split("/")
        if len(parts) < 2 or parts[0] not in COUCHES:
            continue
        tables.setdefault(parts[1], []).append(path)
    return tables


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hf-repo", required=True)
    parser.add_argument("--public", action="store_true", help="dataset public au lieu de privé")
    args = parser.parse_args()
    token = os.environ.get("HF_TOKEN")
    if not token:
        parser.error("HF_TOKEN doit être défini dans les secrets GitHub")

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    files = api.list_repo_files(repo_id=args.hf_repo, repo_type="dataset")
    tables = build_manifest(list(files))
    manifest = json.dumps({"tables": tables}, ensure_ascii=False, indent=2)

    with tempfile.TemporaryDirectory() as tmp:
        manifest_path = Path(tmp) / "manifest.json"
        readme_path = Path(tmp) / "README.md"
        manifest_path.write_text(manifest, encoding="utf-8")
        readme_path.write_text(CARTE_DATASET, encoding="utf-8")
        for path_in_repo, local in (("manifest.json", manifest_path), ("README.md", readme_path)):
            api.upload_file(
                path_or_fileobj=str(local),
                path_in_repo=path_in_repo,
                repo_id=args.hf_repo,
                repo_type="dataset",
            )

    print(
        json.dumps(
            {"repository": args.hf_repo, "tables": {k: len(v) for k, v in tables.items()}},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
