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


try:
    from scripts.deploy.dataset_card import ecrire_carte_dataset
except ModuleNotFoundError:  # exécution directe : scripts/deploy est dans sys.path
    from dataset_card import ecrire_carte_dataset


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
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="ne pas écrire manifest.json/README : un job final s'en charge (matrix journalière)",
    )
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
        # Updates ET RIB : analytics compute a besoin des snapshots RIB.
        for file_type in ("updates", "rib"):
            run(
                "ingest",
                "broker",
                "--from",
                jour_str,
                "--to",
                jour_str,
                "--type",
                file_type,
                *collecteurs,
            )
        run("etl", "curate", "--from", jour_str, "--to", jour_str)
        if not any((data_dir / "curated" / "rib_snapshots").glob("date=*/*.parquet")):
            raise SystemExit(
                f"Aucune partition rib_snapshots pour {jour_str} : vérifier l'ingestion RIB "
                "et le parseur MRT (l'extra bgpkit doit être installé)."
            )
        run("analytics", "compute", "--from", jour_str, "--to", jour_str)
        run("detect", "run", "--from", jour_str, "--to", jour_str, *notifier)
        # Le runner n'a que 14 Go : on ne garde pas les MRT du jour curé.
        for brut in (data_dir / "raw").glob(f"*/date={jour_str}"):
            shutil.rmtree(brut, ignore_errors=True)

    run("analytics", "precompute")

    tables: dict[str, list[str]] = {}
    if not args.no_manifest:
        tables = ecrire_manifest(data_dir)
        ecrire_carte_dataset(data_dir)
    publier(data_dir, args.hf_repo, token, prive=not args.public)
    bilan = {
        "days": (end - start).days + 1,
        "repository": args.hf_repo,
        "manifest": not args.no_manifest,
    }
    if tables:
        bilan["tables"] = {name: len(paths) for name, paths in tables.items()}
    print(json.dumps(bilan, indent=2))


if __name__ == "__main__":
    main()
