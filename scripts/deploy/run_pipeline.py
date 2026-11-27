"""Pipeline ABRIP exécuté dans GitHub Actions, sans machine locale.

Enchaîne ingestion, curation, analytics, détection, précalcul, puis publie les
Parquet et un `manifest.json` dans un dataset Hugging Face. Les fichiers bruts
sont supprimés jour par jour pour rester sous la limite de 14 Go du runner.

    uv run --with huggingface_hub python scripts/deploy/run_pipeline.py \
        --from 2026-11-01 --to 2026-11-07 --hf-repo <compte>/abrip-data
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


def run(*arguments: str) -> None:
    subprocess.run([sys.executable, "-m", "abrip.cli", *arguments], check=True)


def jours(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def ecrire_manifest(data_dir: Path) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for path in sorted(data_dir.rglob("*.parquet")):
        if "raw" in path.parts:
            continue
        relative = path.relative_to(data_dir).as_posix()
        parts = relative.split("/")
        if len(parts) < 2:
            continue
        table = parts[1] if parts[0] in {"curated", "analytics", "reference"} else parts[0]
        tables.setdefault(table, []).append(relative)
    (data_dir / "manifest.json").write_text(
        json.dumps({"tables": tables}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return tables


def ecrire_carte_dataset(data_dir: Path) -> None:
    """Décrit la provenance : on ne peut pas relicencier les sources amont."""
    carte = """---
license: other
---
# ABRIP — données BGP dérivées

Jeu généré automatiquement par le pipeline ABRIP. Ce n'est pas une source
primaire : les conditions des sources d'origine s'appliquent.

## Sources et attribution

- **RouteViews** (University of Oregon) — données MRT sous **CC BY 4.0**.
  « This dataset utilizes data provided by RouteViews (www.routeviews.org).
  Use of this data is subject to the CC BY 4.0 license. » DOI : 10.7264/1y7v-2d90.
- **RIPE NCC RIS** — « The RIPE Routing Information Service (RIS) is a RIPE NCC
  service. » https://www.ripe.net/ris — conditions d'usage commercial décrites
  par le RIPE NCC.
- **CAIDA AS Relationships Dataset** — « The CAIDA AS Relationships Dataset,
  période utilisée, https://www.caida.org/catalog/datasets/as-relationships/ ».
  Usage régi par le CAIDA Acceptable Use Agreement ; redistribution à vérifier.
- **AFRINIC et autres RIR** (délégations), **RPKI**, **IRR**, **PeeringDB** et
  **bgp.tools** — selon les conditions propres à chaque source.

## Licence

Le tag `other` indique qu'ABRIP ne transmet aucun droit sur les données amont.
Toute redistribution doit respecter les conditions de chaque source. Les
fichiers calculés par ABRIP (métriques, événements, incidents, précalcul) sont
fournis sans garantie, pour la démonstration et la recherche.
"""
    (data_dir / "README.md").write_text(carte, encoding="utf-8")


def publier(data_dir: Path, repo_id: str, token: str, prive: bool) -> None:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=prive, exist_ok=True)
    api.upload_folder(
        folder_path=str(data_dir),
        repo_id=repo_id,
        repo_type="dataset",
        commit_message="Mise à jour automatique du pipeline ABRIP",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--collectors")
    parser.add_argument("--hf-repo", required=True)
    parser.add_argument("--public", action="store_true", help="dataset public au lieu de privé")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        parser.error("HF_TOKEN doit être défini dans les secrets GitHub")

    data_dir = Path(os.environ.get("ABRIP_DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    collecteurs = ["--collectors", args.collectors] if args.collectors else []
    notifier = ["--notify"] if os.environ.get("ABRIP_ALERTS__WEBHOOK_URL") else []

    for jour in jours(start, end):
        jour_str = jour.isoformat()
        run("ingest", "broker", "--from", jour_str, "--to", jour_str, *collecteurs)
        run("etl", "curate", "--from", jour_str, "--to", jour_str)
        run("analytics", "compute", "--from", jour_str, "--to", jour_str)
        run("detect", "run", "--from", jour_str, "--to", jour_str, *notifier)
        # Le runner n'a que 14 Go : on ne garde pas les MRT du jour curé.
        for brut in (data_dir / "raw").glob(f"*/date={jour_str}"):
            shutil.rmtree(brut, ignore_errors=True)

    run("analytics", "precompute")

    tables = ecrire_manifest(data_dir)
    ecrire_carte_dataset(data_dir)
    publier(data_dir, args.hf_repo, token, prive=not args.public)
    print(
        json.dumps(
            {
                "days": (end - start).days + 1,
                "tables": {name: len(paths) for name, paths in tables.items()},
                "repository": args.hf_repo,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
