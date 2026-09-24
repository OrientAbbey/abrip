"""Indicateurs BGP calculés sur la couche curée.

Tous les calculs sont écrits en Polars *lazy* : les filtres et projections sont
poussés au plus près de la lecture Parquet, ce qui évite de matérialiser des
millions de lignes pour produire quelques milliers d'agrégats.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import polars as pl

from abrip.config import Settings
from abrip.logging_conf import get_logger
from abrip.models import METRIC_COVERAGE_SCHEMA, METRIC_RPKI_COVERAGE_SCHEMA
from abrip.reference.rpki import RpkiValidator
from abrip.storage.catalog import Catalog, RunContext
from abrip.storage.parquet import read_partitions, write_frame

log = get_logger(__name__)

WINDOW_ALIASES = {"5m": "5m", "15m": "15m", "1h": "1h", "6h": "6h", "24h": "1d", "1d": "1d"}


def _window(value: str) -> str:
    if value not in WINDOW_ALIASES:
        raise ValueError(f"Fenêtre inconnue : {value}. Valeurs acceptées : {list(WINDOW_ALIASES)}")
    return WINDOW_ALIASES[value]


def _elements(
    settings: Settings, start: date, end: date, collectors: list[str] | None
) -> pl.LazyFrame:
    return read_partitions(
        settings.curated_dir,
        "bgp_elements",
        date_from=start.isoformat(),
        date_to=end.isoformat(),
        collectors=collectors,
    )


# ---------------------------------------------------------------------------
# F4.1 — churn
# ---------------------------------------------------------------------------
def compute_churn(
    settings: Settings,
    start: date,
    end: date,
    window: str = "1h",
    collectors: list[str] | None = None,
) -> dict[str, pl.DataFrame]:
    """Annonces, retraits et total par fenêtre, déclinés par préfixe et par AS d'origine."""
    every = _window(window)
    lazy = _elements(settings, start, end, collectors).filter(pl.col("elem_type") != "R")

    by_prefix = (
        lazy.sort("ts")
        .group_by_dynamic("ts", every=every, group_by=["collector", "prefix"])
        .agg(
            announcements=(pl.col("elem_type") == "A").sum(),
            withdrawals=(pl.col("elem_type") == "W").sum(),
            updates_total=pl.len(),
            distinct_peers=pl.col("peer_asn").n_unique(),
            distinct_origins=pl.col("origin_asn").n_unique(),
        )
        .rename({"ts": "window_start"})
        .with_columns(pl.lit(window).alias("window"))
        .collect(engine="streaming")
    )

    by_asn = (
        lazy.filter(pl.col("origin_asn").is_not_null())
        .sort("ts")
        .group_by_dynamic("ts", every=every, group_by=["collector", "origin_asn"])
        .agg(
            announcements=(pl.col("elem_type") == "A").sum(),
            withdrawals=(pl.col("elem_type") == "W").sum(),
            updates_total=pl.len(),
            distinct_prefixes=pl.col("prefix").n_unique(),
        )
        .rename({"ts": "window_start"})
        .with_columns(pl.lit(window).alias("window"))
        .collect(engine="streaming")
    )
    return {"metric_churn_prefix": by_prefix, "metric_churn_asn": by_asn}


# ---------------------------------------------------------------------------
# F4.2 — visibilité
# ---------------------------------------------------------------------------
def compute_visibility(
    settings: Settings, start: date, end: date, collectors: list[str] | None = None
) -> pl.DataFrame:
    """Proportion de peers voyant chaque préfixe, ventilée local / extérieur.

    La ventilation est le point important : une chute de visibilité vue depuis
    l'extérieur mais pas depuis l'Afrique ne raconte pas la même histoire qu'une
    chute vue partout.
    """
    lazy = read_partitions(
        settings.curated_dir,
        "rib_snapshots",
        date_from=start.isoformat(),
        date_to=end.isoformat(),
        collectors=collectors,
    )
    roles = {c.name: c.role for c in settings.collectors}

    peers_per_snapshot = lazy.group_by(["snapshot_ts", "collector"]).agg(
        peers_total=pl.col("peer_asn").n_unique()
    )

    # Comptage au niveau (collecteur, peer) : un ASN present sur deux collecteurs
    # compte pour deux points de vue, ce qui est bien la realite de la mesure.
    seen = lazy.group_by(["snapshot_ts", "collector", "prefix"]).agg(
        peers_seeing=pl.col("peer_asn").n_unique(),
        origin_asn=pl.col("origin_asn").mode().first(),
        median_path_len=pl.col("as_path_len").median(),
    )

    joined = (
        seen.join(peers_per_snapshot, on=["snapshot_ts", "collector"], how="left")
        .with_columns(
            (pl.col("peers_seeing") / pl.col("peers_total")).alias("visibility_ratio"),
            pl.col("collector")
            .replace_strict(roles, default="local", return_dtype=pl.Utf8)
            .alias("collector_role"),
        )
        .collect(engine="streaming")
    )

    return (
        joined.group_by(["snapshot_ts", "prefix"])
        .agg(
            peers_seeing=pl.col("peers_seeing").sum(),
            peers_total=pl.col("peers_total").sum(),
            collectors_seeing=pl.col("collector").n_unique(),
            origin_asn=pl.col("origin_asn").mode().first(),
            median_path_len=pl.col("median_path_len").median(),
            visibility_local=pl.col("visibility_ratio")
            .filter(pl.col("collector_role") == "local")
            .mean(),
            visibility_external=pl.col("visibility_ratio")
            .filter(pl.col("collector_role") == "external")
            .mean(),
        )
        .with_columns((pl.col("peers_seeing") / pl.col("peers_total")).alias("visibility_ratio"))
        .sort(["snapshot_ts", "prefix"])
    )


# ---------------------------------------------------------------------------
# F4.3 — évolution des AS-paths
# ---------------------------------------------------------------------------
def compute_aspath(
    settings: Settings,
    start: date,
    end: date,
    window: str = "1h",
    collectors: list[str] | None = None,
) -> pl.DataFrame:
    every = _window(window)
    return (
        _elements(settings, start, end, collectors)
        .filter((pl.col("elem_type") == "A") & pl.col("origin_asn").is_not_null())
        .with_columns(
            pl.col("as_path_dedup").cast(pl.List(pl.Utf8)).list.join(" ").alias("path_str")
        )
        .sort("ts")
        .group_by_dynamic("ts", every=every, group_by=["prefix"])
        .agg(
            distinct_paths=pl.col("path_str").n_unique(),
            distinct_origins=pl.col("origin_asn").n_unique(),
            origins=pl.col("origin_asn").unique(),
            median_path_len=pl.col("as_path_len").median(),
            max_path_len=pl.col("as_path_len").max(),
            has_as_set=pl.col("has_as_set").any(),
            announcements=pl.len(),
            peers=pl.col("peer_asn").n_unique(),
        )
        .rename({"ts": "window_start"})
        .with_columns(pl.lit(window).alias("window"))
        .collect(engine="streaming")
    )


# ---------------------------------------------------------------------------
# F4.4 / F4.6 — upstreams et concentration
# ---------------------------------------------------------------------------
def compute_upstream(
    settings: Settings,
    start: date,
    end: date,
    window: str = "1h",
    collectors: list[str] | None = None,
) -> pl.DataFrame:
    """Suit l'AS immédiatement en amont de chaque AS d'origine.

    ``hhi_transit`` est l'indice de Herfindahl sur la répartition des upstreams :
    proche de 1, l'AS dépend d'un transitaire unique — une fragilité structurelle
    fréquente sur le continent.
    """
    every = _window(window)
    lazy = (
        _elements(settings, start, end, collectors)
        .filter((pl.col("elem_type") == "A") & (pl.col("as_path_len") >= 2))
        .with_columns(pl.col("as_path_dedup").list.get(-2, null_on_oob=True).alias("upstream_asn"))
        .filter(pl.col("upstream_asn").is_not_null())
    )

    per_upstream = (
        lazy.sort("ts")
        .group_by_dynamic("ts", every=every, group_by=["origin_asn", "upstream_asn"])
        .agg(observations=pl.len(), peers=pl.col("peer_asn").n_unique())
        .rename({"ts": "window_start"})
        .collect(engine="streaming")
    )
    if per_upstream.is_empty():
        return per_upstream

    return (
        per_upstream.with_columns(
            (
                pl.col("observations")
                / pl.col("observations").sum().over(["window_start", "origin_asn"])
            ).alias("share")
        )
        .group_by(["window_start", "origin_asn"])
        .agg(
            upstreams=pl.col("upstream_asn").unique(),
            upstream_count=pl.col("upstream_asn").n_unique(),
            primary_upstream=pl.col("upstream_asn")
            .sort_by("observations", descending=True)
            .first(),
            hhi_transit=(pl.col("share") ** 2).sum(),
            observations=pl.col("observations").sum(),
        )
        .with_columns(pl.lit(window).alias("window"))
        .sort(["window_start", "origin_asn"])
    )


# ---------------------------------------------------------------------------
# F4.5 — indicateurs par pays
# ---------------------------------------------------------------------------
def compute_country(
    settings: Settings,
    upstream: pl.DataFrame,
    visibility: pl.DataFrame,
    ref_asn: pl.DataFrame,
    coverage: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Agrège par pays : dépendance au transit et concentration.

    ``transit_dependency_ratio`` mesure la part des observations dont l'upstream
    immédiat n'est pas un AS africain — autrement dit, la part du routage qui
    sort du continent dès le premier saut.

    ``coverage_ratio`` (L2) est jointe ici plutôt que laissée dans sa seule
    table dédiée : c'est la valeur qui accompagne chaque chiffre pays dans
    l'interface, pour qu'un indicateur ne s'affiche jamais sans son propre
    degré de confiance.
    """
    if upstream.is_empty() or ref_asn.is_empty():
        return pl.DataFrame()

    african = ref_asn.filter(pl.col("is_african")).select(
        pl.col("asn").cast(pl.UInt32), pl.col("country_iso2")
    )
    african_set = set(african.get_column("asn").to_list())

    enriched = (
        upstream.with_columns(pl.col("origin_asn").cast(pl.UInt32))
        .join(african, left_on="origin_asn", right_on="asn", how="inner")
        .with_columns(pl.col("primary_upstream").is_in(african_set).alias("upstream_is_african"))
    )
    if enriched.is_empty():
        return pl.DataFrame()

    result = (
        enriched.group_by(["window_start", "country_iso2"])
        .agg(
            asns_observed=pl.col("origin_asn").n_unique(),
            avg_hhi_transit=pl.col("hhi_transit").mean(),
            avg_upstream_count=pl.col("upstream_count").mean(),
            transit_dependency_ratio=1 - pl.col("upstream_is_african").mean(),
        )
        .join(
            _visibility_by_country(visibility, african),
            on=["country_iso2"],
            how="left",
        )
        .sort(["window_start", "country_iso2"])
    )
    if coverage is not None and not coverage.is_empty():
        # Jointure par pays seul : la couverture est évaluée sur toute la
        # fenêtre calculée, pas heure par heure — elle ne varie pas assez vite
        # pour qu'un découpage plus fin ait un sens.
        result = result.join(
            coverage.select("country_iso2", "coverage_ratio"),
            on="country_iso2",
            how="left",
        )
    else:
        result = result.with_columns(pl.lit(None, dtype=pl.Float64).alias("coverage_ratio"))
    return result


def _visibility_by_country(visibility: pl.DataFrame, african: pl.DataFrame) -> pl.DataFrame:
    if visibility.is_empty():
        return pl.DataFrame({"country_iso2": [], "avg_visibility": []})
    return (
        visibility.with_columns(pl.col("origin_asn").cast(pl.UInt32))
        .join(african, left_on="origin_asn", right_on="asn", how="inner")
        .group_by("country_iso2")
        .agg(
            avg_visibility=pl.col("visibility_ratio").mean(),
            prefixes_visible=pl.col("prefix").n_unique(),
        )
    )


# ---------------------------------------------------------------------------
# L2 — couverture observationnelle par pays
# ---------------------------------------------------------------------------
def compute_coverage(
    settings: Settings,
    start: date,
    end: date,
    ref_asn: pl.DataFrame,
    collectors: list[str] | None = None,
) -> pl.DataFrame:
    """Part des AS alloués à un pays effectivement vus depuis les collecteurs.

    La remédiation à une vue partielle n'est pas de prétendre la combler, mais
    de la mesurer et de la publier — voir ``docs/limites-et-remediations.md``
    (L2). Un pays à 8 % de couverture doit voir ses indicateurs marqués comme
    peu fiables, pas traités à égalité avec un pays à 90 %.
    """
    if ref_asn.is_empty():
        return pl.DataFrame(schema=METRIC_COVERAGE_SCHEMA)

    african = ref_asn.filter(pl.col("is_african")).select(
        pl.col("asn").cast(pl.UInt32), pl.col("country_iso2")
    )
    if african.is_empty():
        return pl.DataFrame(schema=METRIC_COVERAGE_SCHEMA)

    allocated = african.group_by("country_iso2").agg(asns_allocated=pl.col("asn").n_unique())

    observed = (
        _elements(settings, start, end, collectors)
        .filter(pl.col("origin_asn").is_not_null())
        .select(pl.col("origin_asn").cast(pl.UInt32).alias("asn"))
        .unique()
        .join(african.lazy(), on="asn", how="inner")
        .group_by("country_iso2")
        .agg(asns_observed=pl.col("asn").n_unique())
        .collect(engine="streaming")
    )

    window_start = datetime.combine(start, datetime.min.time())
    return (
        allocated.join(observed, on="country_iso2", how="left")
        .with_columns(pl.col("asns_observed").fill_null(0))
        .with_columns(
            (pl.col("asns_observed") / pl.col("asns_allocated")).alias("coverage_ratio"),
            pl.lit(window_start).alias("window_start"),
        )
        .select(list(METRIC_COVERAGE_SCHEMA))
        .sort("country_iso2")
    )


# ---------------------------------------------------------------------------
# L4b — couverture ROA par pays
# ---------------------------------------------------------------------------
def compute_rpki_coverage(
    settings: Settings,
    start: date,
    end: date,
    ref_roa: pl.DataFrame,
    ref_asn: pl.DataFrame,
    collectors: list[str] | None = None,
) -> pl.DataFrame:
    """Part des préfixes annoncés couverte par un ROA valide, par pays.

    ``not-found`` est le statut RPKI majoritaire dans la zone AFRINIC : plutôt
    que de le subir comme un angle mort, cette métrique le mesure et le suit
    dans le temps. C'est une donnée que les opérateurs et régulateurs de la
    région n'ont, aujourd'hui, nulle part où consulter facilement (L4b).
    """
    if ref_asn.is_empty():
        return pl.DataFrame(schema=METRIC_RPKI_COVERAGE_SCHEMA)

    african = ref_asn.filter(pl.col("is_african")).select(
        pl.col("asn").cast(pl.UInt32), pl.col("country_iso2")
    )
    if african.is_empty():
        return pl.DataFrame(schema=METRIC_RPKI_COVERAGE_SCHEMA)

    announced = (
        _elements(settings, start, end, collectors)
        .filter((pl.col("elem_type") == "A") & pl.col("origin_asn").is_not_null())
        .select(
            pl.col("prefix"),
            pl.col("origin_asn").cast(pl.UInt32).alias("asn"),
        )
        .unique()
        .join(african.lazy(), on="asn", how="inner")
        .collect(engine="streaming")
    )
    if announced.is_empty():
        return pl.DataFrame(schema=METRIC_RPKI_COVERAGE_SCHEMA)

    validator = RpkiValidator.from_frame(ref_roa) if not ref_roa.is_empty() else None
    if validator is None:
        statuses = ["not-found"] * announced.height
    else:
        statuses = [
            validator.validate(row["prefix"], int(row["asn"])).value
            for row in announced.iter_rows(named=True)
        ]

    window_start = datetime.combine(start, datetime.min.time())
    return (
        announced.with_columns(pl.Series("rpki_status", statuses))
        .group_by("country_iso2")
        .agg(
            prefixes_announced=pl.col("prefix").n_unique(),
            prefixes_valid=pl.col("prefix").filter(pl.col("rpki_status") == "valid").n_unique(),
            prefixes_invalid=pl.col("prefix").filter(pl.col("rpki_status") == "invalid").n_unique(),
            prefixes_not_found=pl.col("prefix")
            .filter(pl.col("rpki_status") == "not-found")
            .n_unique(),
        )
        .with_columns(
            (pl.col("prefixes_valid") / pl.col("prefixes_announced")).alias("rpki_coverage_ratio"),
            pl.lit(window_start).alias("window_start"),
        )
        .select(list(METRIC_RPKI_COVERAGE_SCHEMA))
        .sort("country_iso2")
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def compute_all(
    settings: Settings,
    catalog: Catalog,
    start: date,
    end: date,
    window: str | None = None,
    collectors: list[str] | None = None,
) -> dict[str, int]:
    window = window or settings.analytics.default_window
    written: dict[str, int] = {}

    with RunContext(
        catalog, "analytics.compute", start=str(start), end=str(end), window=window
    ) as run:
        churn = compute_churn(settings, start, end, window, collectors)
        for name, frame in churn.items():
            written[name] = _persist(settings, catalog, name, frame, run.run_id)

        visibility = compute_visibility(settings, start, end, collectors)
        written["metric_visibility"] = _persist(
            settings, catalog, "metric_visibility", visibility, run.run_id
        )

        aspath = compute_aspath(settings, start, end, window, collectors)
        written["metric_aspath"] = _persist(settings, catalog, "metric_aspath", aspath, run.run_id)

        upstream = compute_upstream(settings, start, end, window, collectors)
        written["metric_upstream"] = _persist(
            settings, catalog, "metric_upstream", upstream, run.run_id
        )

        ref_asn = _load_reference(settings, "ref_asn")
        ref_roa = _load_reference(settings, "ref_roa")

        coverage = compute_coverage(settings, start, end, ref_asn, collectors)
        written["metric_coverage"] = _persist(
            settings, catalog, "metric_coverage", coverage, run.run_id
        )

        country = compute_country(settings, upstream, visibility, ref_asn, coverage)
        written["metric_country"] = _persist(
            settings, catalog, "metric_country", country, run.run_id
        )

        rpki_coverage = compute_rpki_coverage(settings, start, end, ref_roa, ref_asn, collectors)
        written["metric_rpki_coverage"] = _persist(
            settings, catalog, "metric_rpki_coverage", rpki_coverage, run.run_id
        )

        run.rows_out = sum(written.values())

    log.info("indicateurs calculés", extra=written)
    return written


def _persist(
    settings: Settings, catalog: Catalog, name: str, frame: pl.DataFrame, run_id: str
) -> int:
    if frame is None or frame.is_empty():
        return 0
    target = settings.analytics_dir / name
    write_frame(frame, target)
    catalog.register_partition(
        name,
        str(target),
        frame.height,
        sum(f.stat().st_size for f in target.glob("*.parquet")),
        run_id,
    )
    return frame.height


def _load_reference(settings: Settings, name: str) -> pl.DataFrame:
    path = settings.reference_dir / name
    files = sorted(path.glob("**/*.parquet")) if path.exists() else []
    return pl.read_parquet(files) if files else pl.DataFrame()


def latest_reference_path(settings: Settings, name: str) -> Path | None:
    path = settings.reference_dir / name
    if not path.exists():
        return None
    return path
