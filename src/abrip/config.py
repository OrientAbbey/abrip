"""Chargement typé de la configuration.

Ordre de priorité croissant :
  1. valeurs par défaut des modèles Pydantic
  2. fichiers YAML de ``configs/``
  3. variables d'environnement préfixées ``ABRIP_`` (délimiteur imbriqué ``__``)

Aucun autre module ne lit l'environnement ni un YAML directement : ils appellent
``get_settings()``.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _detect_project_root() -> Path:
    """Racine du projet, d'où sont résolus `configs/`, `data/` et `frontend/dist`.

    Trois situations à couvrir, dans cet ordre :

    1. ``ABRIP_PROJECT_ROOT`` est posée — un déploiement peut ainsi tout placer
       où il veut sans supposition sur la mise en page du disque ;
    2. installation éditable depuis le dépôt : ``src/abrip/config.py`` remonte
       de deux niveaux jusqu'à la racine ;
    3. paquet installé dans ``site-packages`` (image Docker) : remonter de deux
       niveaux mène dans la bibliothèque standard, pas au projet. On retient
       alors le répertoire de travail, où les fichiers de configuration ont été
       copiés.
    """
    from_env = os.environ.get("ABRIP_PROJECT_ROOT")
    if from_env:
        return Path(from_env).resolve()

    from_source = Path(__file__).resolve().parents[2]
    if (from_source / "configs").is_dir():
        return from_source

    cwd = Path.cwd()
    if (cwd / "configs").is_dir():
        return cwd

    return from_source


PROJECT_ROOT = _detect_project_root()
CONFIG_DIR = PROJECT_ROOT / "configs"

CollectorRole = Literal["local", "external"]
ParserName = Literal["auto", "bgpkit", "mrtparse"]


class Collector(BaseModel):
    name: str
    project: Literal["routeviews", "riperis", "pch"]
    location: str = ""
    role: CollectorRole = "local"
    enabled: bool = True


class IngestionSettings(BaseModel):
    broker_url: str = "https://api.bgpkit.com/v3/broker/search"
    user_agent: str = "abrip/0.1"
    max_retries: int = 3
    backoff_seconds: float = 2.0
    concurrency: int = 3
    raw_retention_days: int = 30
    request_timeout: int = 120

    # Racine d'archive par projet — un projet change rarement d'URL, mais
    # quand ça arrive (migration d'hébergement, nouveau miroir), c'est ici
    # que ça se corrige, sans toucher au code. Voir ingestion.broker.
    archive_root: dict[str, str] = Field(
        default_factory=lambda: {
            "routeviews": "https://archive.routeviews.org",
            "riperis": "https://data.ris.ripe.net",
            "pch": "https://downloads.pch.net/files/Routing_Data/IPv4_daily_snapshots",
        }
    )
    # Cadence de publication par projet, en minutes.
    cadence: dict[str, dict[str, int]] = Field(
        default_factory=lambda: {
            "routeviews": {"rib": 120, "updates": 15},
            "riperis": {"rib": 480, "updates": 5},
            "pch": {"rib": 1440, "updates": 1440},
        }
    )
    ris_live_url: str = "wss://ris-live.ripe.net/v1/ws/?client=abrip"


class EtlSettings(BaseModel):
    parser: ParserName = "auto"
    batch_rows: int = 500_000
    compression: str = "zstd"
    keep_communities: bool = True
    drop_ipv6: bool = False
    # Tri des partitions bgp_elements par (prefix, ts) : les statistiques des groupes
    # de lignes Parquet permettent alors aux requêtes par préfixe de n'en lire qu'une
    # petite partie (3 à 4 fois plus rapide à 10 M de lignes, voir docs/performances.md).
    sort_partitions: bool = True
    row_group_size: int = 100_000
    sort_memory_limit: str = "1GB"  # le tri déborde sur disque au-delà
    # Rétention des couches curées et analytiques. Doit rester supérieure à
    # ingestion.raw_retention_days : les MRT disparaissent avant les Parquet
    # qu'ils ont produits. La purge n'est jamais automatique (voir `etl purge`).
    retention_days: int = 90


class ReferenceSettings(BaseModel):
    afrinic_delegated_url: str = ""
    rir_delegated_urls: dict[str, str] = Field(default_factory=dict)
    rpki_url: str = ""
    caida_as_rel_base: str = ""
    caida_as_org_base: str = ""
    extra_african_asns: list[int] = Field(default_factory=list)
    # L6 (filtre 3) — catalogue public d'anycast (bgp.tools/anycatch).
    anycast_v4_url: str = "https://raw.githubusercontent.com/bgptools/anycast-prefixes/master/anycatch-v4-prefixes.csv"
    anycast_v6_url: str = "https://raw.githubusercontent.com/bgptools/anycast-prefixes/master/anycatch-v6-prefixes.csv"


class AnalyticsSettings(BaseModel):
    windows: list[str] = Field(default_factory=lambda: ["5m", "1h", "24h"])
    default_window: str = "1h"
    min_peers_for_metric: int = 2


class ApiSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    api_key: str | None = None
    cache_ttl_seconds: int = 60
    max_page_size: int = 500
    # Nombre de processus uvicorn. Un seul par défaut : le préchauffage et le
    # cache en mémoire sont alors partagés par toutes les requêtes. Au-delà,
    # chaque processus a son propre cache et ses propres compteurs Prometheus.
    workers: int = 1
    # Requêtes par minute et par adresse, 0 = aucune limite. Limite locale à
    # chaque worker ; la supervision (/health, /metrics) en est exemptée.
    rate_limit_per_minute: int = 0
    # Pré-remplit le cache de la vue d'ensemble au démarrage (un worker = un
    # cache) : évite le pic de latence du premier appel, au prix d'un démarrage
    # un peu plus long.
    prewarm: bool = False
    static_dir: str = "frontend/dist"


class AlertSettings(BaseModel):
    """Alertes sur incidents : webhook au format Slack, déduplication persistée.

    Aucune alerte n'est envoyée tant que `webhook_url` est vide : le pipeline
    reste muet par défaut, y compris en démonstration.
    """

    webhook_url: str | None = None
    min_severity: Literal["info", "watch", "critical"] = "critical"
    dedupe_days: int = 7
    timeout_seconds: float = 10.0


class EnrichmentSettings(BaseModel):
    """Sources externes de corroboration — remédiations L1, L3 et L4a.

    Chaque appel réseau échoue en douceur (verdict ``inconclusive`` ou statut
    ``absent``, jamais une exception qui interromprait la détection) : ces
    sources ajoutent de la confiance quand elles répondent, mais leur absence
    ne doit jamais bloquer le pipeline. C'est pourquoi elles sont activées par
    défaut plutôt que traitées comme un mode dégradé optionnel.
    """

    request_timeout: float = 15.0

    # L1 — confirmation par le plan de données (IODA, RIPE Atlas probes).
    dataplane_enabled: bool = True
    dataplane_min_severity: str = "watch"  # ne pas dépenser d'appels réseau sur des `info`
    ioda_base_url: str = "https://api.ioda.inetintel.cc.gatech.edu/v2"
    ripe_atlas_base_url: str = "https://atlas.ripe.net/api/v2"
    # Seuils de lecture des deux sources (0 = normalité, 1 = coupure totale
    # pour IODA ; en dessous du plancher, RIPE Atlas est jugé corroborer un
    # problème plutôt qu'une fluctuation normale).
    ioda_outage_threshold: float = 0.5
    atlas_connected_floor: float = 0.6
    # Cloudflare Radar : seule source de L1 à exiger une clé. Optionnelle par
    # nature — non configurée, elle se désactive proprement (voir
    # CloudflareRadarClient). Créer un jeton : dashboard.cloudflare.com →
    # My Profile → API Tokens.
    cloudflare_radar_base_url: str = "https://api.cloudflare.com/client/v4"
    cloudflare_radar_token: str | None = None

    # L3 — corroboration multi-source des relations CAIDA.
    peeringdb_base_url: str = "https://www.peeringdb.com/api"
    relationship_min_sources_for_critical: int = 2

    # L4a — référentiel IRR de repli quand RPKI répond `not-found`.
    ripedb_base_url: str = "https://rest.db.ripe.net"
    irr_sources: list[str] = Field(default_factory=lambda: ["RADB", "RIPE", "APNIC", "ARIN"])


class Settings(BaseSettings):
    """Configuration racine de la plateforme."""

    model_config = SettingsConfigDict(
        env_prefix="ABRIP_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    data_dir: Path = PROJECT_ROOT / "data"
    log_level: str = "INFO"
    # Chemin relatif à data_dir (sauf si absolu). Rotation par taille : au-delà
    # de log_max_bytes, le fichier courant devient .1, jusqu'à log_backup_count.
    log_file: str = "logs/abrip.log"
    log_max_bytes: int = 10_000_000
    log_backup_count: int = 5

    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    etl: EtlSettings = Field(default_factory=EtlSettings)
    reference: ReferenceSettings = Field(default_factory=ReferenceSettings)
    analytics: AnalyticsSettings = Field(default_factory=AnalyticsSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    alerts: AlertSettings = Field(default_factory=AlertSettings)
    enrichment: EnrichmentSettings = Field(default_factory=EnrichmentSettings)

    collectors: list[Collector] = Field(default_factory=list)
    detection: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data_dir", mode="after")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    # --- chemins dérivés -------------------------------------------------
    @property
    def project_root(self) -> Path:
        """Racine du dépôt : sert à résoudre les chemins relatifs de la
        configuration (le répertoire du frontend compilé, par exemple)."""
        return PROJECT_ROOT

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def curated_dir(self) -> Path:
        return self.data_dir / "curated"

    @property
    def analytics_dir(self) -> Path:
        return self.data_dir / "analytics"

    @property
    def reference_dir(self) -> Path:
        return self.data_dir / "reference"

    @property
    def catalog_path(self) -> Path:
        return self.data_dir / "catalog.duckdb"

    @property
    def log_path(self) -> Path:
        path = Path(self.log_file)
        return path if path.is_absolute() else self.data_dir / path

    def enabled_collectors(self, role: CollectorRole | None = None) -> list[Collector]:
        out = [c for c in self.collectors if c.enabled]
        return [c for c in out if role is None or c.role == role]

    def collector(self, name: str) -> Collector | None:
        return next((c for c in self.collectors if c.name == name), None)

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.raw_dir,
            self.curated_dir,
            self.analytics_dir,
            self.reference_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _env_overrides(key: str) -> bool:
    """Une variable d'environnement couvre-t-elle cette clé de configuration ?

    Pydantic donne la priorité aux arguments passés au constructeur sur les
    variables d'environnement. Comme le YAML arrive justement par le
    constructeur, il faut retirer les clés couvertes par l'environnement pour
    respecter la précédence annoncée : défauts → YAML → environnement.
    """
    prefix = f"ABRIP_{key.upper()}"
    return any(name == prefix or name.startswith(f"{prefix}__") for name in os.environ)


@functools.lru_cache(maxsize=1)
def get_settings(config_dir: Path | None = None) -> Settings:
    """Charge la configuration une seule fois par processus."""
    directory = config_dir or CONFIG_DIR
    payload: dict[str, Any] = _read_yaml(directory / "settings.yaml")
    payload["collectors"] = _read_yaml(directory / "collectors.yaml").get("collectors", [])
    payload["detection"] = _read_yaml(directory / "detection.yaml")
    payload = {key: value for key, value in payload.items() if not _env_overrides(key)}
    return Settings(**payload)


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
