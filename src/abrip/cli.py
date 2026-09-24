"""Point d'entrée unique de la plateforme.

Une seule commande ``abrip`` pour tout le cycle de vie : ingérer, curer,
calculer, détecter, servir. Chaque sous-commande est journalisée dans le
catalogue, donc reproductible et traçable.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import typer
from rich.console import Console
from rich.table import Table

from abrip.config import get_settings
from abrip.logging_conf import setup_logging

app = typer.Typer(help="African BGP Routing Intelligence Platform", no_args_is_help=True)
ingest_app = typer.Typer(help="Ingestion des archives BGP")
reference_app = typer.Typer(help="Référentiels ASN, RPKI, relations")
etl_app = typer.Typer(help="Transformation vers la couche curée")
analytics_app = typer.Typer(help="Calcul des indicateurs")
detect_app = typer.Typer(help="Détection d'anomalies")
demo_app = typer.Typer(help="Jeu de démonstration")
api_app = typer.Typer(help="Service web")

app.add_typer(ingest_app, name="ingest")
app.add_typer(reference_app, name="reference")
app.add_typer(etl_app, name="etl")
app.add_typer(analytics_app, name="analytics")
app.add_typer(detect_app, name="detect")
app.add_typer(demo_app, name="demo")
app.add_typer(api_app, name="api")

console = Console()


def _bootstrap_runtime():
    settings = get_settings()
    setup_logging(settings.log_level, json_output=False)
    settings.ensure_dirs()
    from abrip.storage.catalog import Catalog

    return settings, Catalog(settings.catalog_path)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _split(value: str | None) -> list[str] | None:
    return [item.strip() for item in value.split(",") if item.strip()] if value else None


# ---------------------------------------------------------------------------
@app.command()
def status() -> None:
    """Affiche l'état des données : couverture, dernière exécution, volumétrie."""
    settings, catalog = _bootstrap_runtime()
    coverage = catalog.coverage()

    table = Table(title="Ingestion", show_lines=False)
    for column in ("Collecteur", "Type", "Du", "Au", "Fichiers"):
        table.add_column(column)
    for row in coverage["ingestion"]:
        table.add_row(
            row["collector"], row["file_type"], str(row["from"]), str(row["to"]), str(row["files"])
        )
    console.print(table)

    layers = Table(title="Couches")
    layers.add_column("Couche")
    layers.add_column("Chemin")
    layers.add_column("Présente")
    for name, path in (
        ("brute", settings.raw_dir),
        ("curée", settings.curated_dir),
        ("analytique", settings.analytics_dir),
        ("référentiel", settings.reference_dir),
    ):
        has_data = path.exists() and any(path.rglob("*"))
        layers.add_row(name, str(path), "oui" if has_data else "non")
    console.print(layers)

    if coverage["last_run"]:
        console.print(f"Dernière exécution : {coverage['last_run']}")


# --- ingestion -------------------------------------------------------------
@ingest_app.command("broker")
def ingest_broker(
    from_: str = typer.Option(..., "--from", help="Date de début AAAA-MM-JJ"),
    to: str = typer.Option(..., "--to", help="Date de fin AAAA-MM-JJ"),
    collectors: str | None = typer.Option(None, help="Liste séparée par des virgules"),
    file_type: str = typer.Option("updates", "--type", help="updates | rib"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Estime le volume sans télécharger"),
) -> None:
    """Découvre et télécharge les fichiers MRT d'une plage de dates."""
    settings, catalog = _bootstrap_runtime()
    from abrip.ingestion.broker import BrokerClient
    from abrip.ingestion.downloader import Downloader
    from abrip.storage.catalog import RunContext

    names = _split(collectors)
    selected = [c for c in settings.enabled_collectors() if names is None or c.name in names]
    if not selected:
        console.print("[red]Aucun collecteur actif. Vérifier configs/collectors.yaml.[/red]")
        raise typer.Exit(1)

    start = datetime.combine(_parse_date(from_), datetime.min.time())
    end = datetime.combine(_parse_date(to), datetime.max.time())

    with RunContext(catalog, "ingest.broker", start=from_, end=to, type=file_type) as run:
        files = BrokerClient(settings).search(selected, start, end, file_type)  # type: ignore[arg-type]
        report = Downloader(settings, catalog).run(files, dry_run=dry_run)
        run.rows_in = len(files)
        run.rows_out = report.downloaded

    console.print(f"Fichiers identifiés : {len(files)}")
    console.print(json.dumps(report.as_dict(), indent=2))


@ingest_app.command("purge")
def ingest_purge(days: int | None = typer.Option(None, help="Rétention en jours")) -> None:
    """Purge la couche brute au-delà de la rétention configurée."""
    settings, catalog = _bootstrap_runtime()
    from abrip.ingestion.downloader import Downloader

    removed = Downloader(settings, catalog).purge_raw(days)
    console.print(f"Fichiers supprimés : {removed}")


@ingest_app.command("ris-live")
def ingest_ris_live(
    duration: int = typer.Option(300, help="Durée d'écoute en secondes"),
    prefixes: str | None = typer.Option(None, help="Filtre de préfixes"),
) -> None:
    """Capture le flux RIS Live pendant une durée donnée."""
    import asyncio

    settings, _ = _bootstrap_runtime()
    from abrip.ingestion.ris_live import capture

    written = asyncio.run(capture(settings, duration=duration, prefixes=_split(prefixes)))
    console.print(f"Messages capturés : {written}")


# --- référentiels ----------------------------------------------------------
@reference_app.command("sync")
def reference_sync(
    sources: str = typer.Option("afrinic,rpki,caida", help="Sources à rafraîchir"),
) -> None:
    """Télécharge et met à jour les référentiels datés."""
    settings, catalog = _bootstrap_runtime()
    from abrip.reference.sync import sync_references

    result = sync_references(settings, catalog, _split(sources) or [])
    console.print(json.dumps(result, indent=2, default=str))


# --- ETL -------------------------------------------------------------------
@etl_app.command("curate")
def etl_curate(
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    collectors: str | None = typer.Option(None),
    synthetic: bool = typer.Option(False, help="Utilise le générateur au lieu des fichiers MRT"),
) -> None:
    """Transforme la couche brute en tables curées Parquet."""
    settings, catalog = _bootstrap_runtime()
    from abrip.etl.curate import curate_range

    totals = curate_range(
        settings, catalog, _parse_date(from_), _parse_date(to), _split(collectors), synthetic
    )
    console.print(json.dumps(totals, indent=2))


# --- analytics -------------------------------------------------------------
@analytics_app.command("compute")
def analytics_compute(
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    window: str | None = typer.Option(None, help="5m | 1h | 24h"),
    collectors: str | None = typer.Option(None),
) -> None:
    """Calcule les indicateurs et les écrit dans la couche analytique."""
    settings, catalog = _bootstrap_runtime()
    from abrip.analytics.metrics import compute_all

    written = compute_all(
        settings, catalog, _parse_date(from_), _parse_date(to), window, _split(collectors)
    )
    console.print(json.dumps(written, indent=2))


# --- détection -------------------------------------------------------------
@detect_app.command("run")
def detect_run(
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    detectors: str | None = typer.Option(None, help="Sous-ensemble de détecteurs"),
    all_regions: bool = typer.Option(False, help="Ne pas restreindre aux AS africains"),
) -> None:
    """Exécute les détecteurs et produit la table des candidats d'anomalie."""
    settings, catalog = _bootstrap_runtime()
    from abrip.anomaly.engine import run_detection

    result = run_detection(
        settings,
        catalog,
        _parse_date(from_),
        _parse_date(to),
        _split(detectors),
        african_only=not all_regions,
    )
    console.print(json.dumps(result, indent=2))


@detect_app.command("list")
def detect_list() -> None:
    """Liste les détecteurs disponibles et leur état."""
    settings, _ = _bootstrap_runtime()
    from abrip.anomaly.engine import DETECTORS

    configs = settings.detection.get("detectors", {})
    table = Table(title="Détecteurs")
    for column in ("Nom", "Actif", "Poids", "Rôle"):
        table.add_column(column)
    for name, klass in DETECTORS.items():
        config = configs.get(name, {})
        doc = (klass.__doc__ or "").strip().split("\n")[0]
        table.add_row(
            name,
            "oui" if config.get("enabled", True) else "non",
            str(config.get("score_weight", klass.default_weight)),
            doc,
        )
    console.print(table)


@detect_app.command("watch")
def detect_watch(
    minutes: int = typer.Option(5, help="Durée d'une fenêtre de capture, en minutes"),
    iterations: int = typer.Option(1, help="Nombre de fenêtres à traiter avant de s'arrêter"),
    prefixes: str | None = typer.Option(None, help="Filtre de préfixes RIS Live"),
) -> None:
    """Détection en continu sur le flux RIS Live (L7 — granularité).

    Les archives MRT sont publiées avec 5 à 15 minutes de retard minimum : un
    incident bref peut être lissé, ou simplement pas encore visible, avant
    même la publication de l'archive qui le contiendrait. RIS Live pousse les
    messages en direct ; cette commande capture une fenêtre, la cure aussitôt
    (``curate_ris_live_window``, fusion idempotente dans la même couche
    curée que les archives) puis relance la détection — ce qui réduit le délai
    entre l'incident réel et sa détection au temps de capture, plus quelques
    secondes, au lieu d'attendre la prochaine publication d'archive.

    Précision assumée : la détection elle-même continue de s'exécuter à la
    granularité du jour calendaire (comme ``detect run``), pas de la fenêtre
    de 5 minutes — c'est le délai de *disponibilité* de la donnée qui est
    réduit, pas la granularité d'analyse des détecteurs eux-mêmes. Rejouer
    plusieurs fenêtres du même jour est sans risque : la curation est
    idempotente et les identifiants d'événements sont déterministes.
    """
    import asyncio

    settings, catalog = _bootstrap_runtime()
    from abrip.anomaly.engine import run_detection
    from abrip.etl.curate import curate_ris_live_window
    from abrip.ingestion.ris_live import capture

    for i in range(iterations):
        console.print(f"[cyan]Fenêtre {i + 1}/{iterations} — capture {minutes} min…[/cyan]")
        window_start = datetime.now(UTC)
        messages = asyncio.run(capture(settings, duration=minutes * 60, prefixes=_split(prefixes)))
        console.print(f"  messages capturés : {messages}")

        stream_dir = settings.raw_dir / "ris-live" / "stream"
        cutoff = window_start - timedelta(seconds=5)
        jsonl_files = [
            p
            for p in stream_dir.glob("date=*/*.jsonl")
            if datetime.fromtimestamp(p.stat().st_mtime, tz=UTC) >= cutoff
        ]
        curated = {"elements": 0}
        for jsonl_path in jsonl_files:
            report = curate_ris_live_window(settings, catalog, jsonl_path)
            curated["elements"] += report["elements"]
        console.print(f"  éléments curés : {curated['elements']}")

        window_end = datetime.now(UTC)
        result = run_detection(
            settings,
            catalog,
            window_start.date(),
            window_end.date(),
        )
        console.print(
            f"  [green]événements : {result['events']}, incidents : {result['incidents']}[/green]"
        )


# --- démonstration ---------------------------------------------------------
@demo_app.command("bootstrap")
def demo_bootstrap(days: int = typer.Option(7, help="Nombre de jours à générer")) -> None:
    """Génère un jeu complet et exécute tout le pipeline dessus."""
    settings, _ = _bootstrap_runtime()
    from abrip.demo.bootstrap import bootstrap

    result = bootstrap(settings, days)
    console.print(json.dumps(result, indent=2, default=str))
    console.print("\n[green]Prêt.[/green] Lancer ensuite : abrip api serve")


@demo_app.command("verify")
def demo_verify() -> None:
    """Vérifie que les anomalies plantées ont bien été détectées."""
    settings, _ = _bootstrap_runtime()
    from abrip.demo.bootstrap import verify

    result = verify(settings)
    console.print(json.dumps(result, indent=2, default=str))


# --- API -------------------------------------------------------------------
@api_app.command("serve")
def api_serve(
    host: str | None = typer.Option(None),
    port: int | None = typer.Option(None),
    reload: bool = typer.Option(False, help="Rechargement automatique en développement"),
) -> None:
    """Démarre le service FastAPI."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "abrip.api.main:create_app",
        factory=True,
        host=host or settings.api.host,
        port=port or settings.api.port,
        reload=reload,
    )


# --- pipeline --------------------------------------------------------------
@app.command()
def pipeline(
    day: str | None = typer.Option(None, help="Journée à traiter, par défaut hier"),
    synthetic: bool = typer.Option(False),
) -> None:
    """Enchaîne ingestion, curation, indicateurs et détection pour une journée."""
    settings, catalog = _bootstrap_runtime()
    from abrip.analytics.metrics import compute_all
    from abrip.anomaly.engine import run_detection
    from abrip.etl.curate import curate_range

    target = _parse_date(day) if day else date.today() - timedelta(days=1)
    if not synthetic:
        ingest_broker(
            from_=target.isoformat(),
            to=target.isoformat(),
            collectors=None,
            file_type="updates",
            dry_run=False,
        )
    curate_range(settings, catalog, target, target, None, synthetic)
    compute_all(settings, catalog, target, target)
    result = run_detection(settings, catalog, target, target)
    console.print(json.dumps(result, indent=2))


if __name__ == "__main__":
    app()
