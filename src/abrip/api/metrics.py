"""Observabilité minimale de l'API, sans dépendance supplémentaire.

Les compteurs sont agrégés par **modèle de route** (`/api/asns/{asn}`) et non
par URL réelle, pour garder une cardinalité bornée même avec des milliers de
préfixes. Le format texte est celui de Prometheus ; il n'y a pas de serveur
d'exposition séparé, c'est l'API qui sert `/api/metrics`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from abrip.config import Settings

# Limites des seaux du histogramme, en secondes. Au-delà, seul le total compte.
BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@dataclass
class _Timing:
    count: int = 0
    total: float = 0.0
    buckets: list[int] = field(default_factory=lambda: [0] * len(BUCKETS))


_lock = threading.Lock()
_timings: dict[tuple[str, str, int], _Timing] = {}


def observe(method: str, path: str, status: int, seconds: float) -> None:
    """Enregistre une réponse HTTP."""
    key = (method, path, status)
    with _lock:
        timing = _timings.setdefault(key, _Timing())
        timing.count += 1
        timing.total += seconds
        # Un seul seau par observation : le premier dont la borne contient la
        # durée. Le rendu additionne ensuite les seaux pour obtenir les
        # compteurs cumulatifs attendus par Prometheus.
        for index, bound in enumerate(BUCKETS):
            if seconds <= bound:
                timing.buckets[index] += 1
                break


def _labels(method: str, path: str, status: int) -> str:
    safe_path = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'method="{method}",path="{safe_path}",status="{status}"'


def render_http() -> str:
    """Expose compteur et histogramme au format Prometheus."""
    lines = [
        "# HELP abrip_http_requests_total Nombre de réponses HTTP.",
        "# TYPE abrip_http_requests_total counter",
        "# HELP abrip_http_request_duration_seconds Durée des réponses HTTP.",
        "# TYPE abrip_http_request_duration_seconds histogram",
    ]
    with _lock:
        snapshot = sorted(
            (key, value.count, value.total, tuple(value.buckets)) for key, value in _timings.items()
        )
    for (method, path, status), count, total, buckets in snapshot:
        labels = _labels(method, path, status)
        lines.append(f"abrip_http_requests_total{{{labels}}} {count}")
        cumulative = 0
        for bound, value in zip(BUCKETS, buckets, strict=True):
            cumulative += value
            lines.append(
                f'abrip_http_request_duration_seconds_bucket{{{labels},le="{bound:g}"}} {cumulative}'
            )
        lines.append(f'abrip_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {count}')
        lines.append(f"abrip_http_request_duration_seconds_sum{{{labels}}} {total:.6f}")
        lines.append(f"abrip_http_request_duration_seconds_count{{{labels}}} {count}")
    return "\n".join(lines) + "\n"


def _layer_stats(root: Path, today: date) -> tuple[int, int, int]:
    files = 0
    size = 0
    newest: date | None = None
    if not root.is_dir():
        return 0, 0, -1
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("date="):
            try:
                day = date.fromisoformat(entry.name.removeprefix("date="))
            except ValueError:
                day = None
            if day and (newest is None or day > newest):
                newest = day
        for path in entry.rglob("*.parquet"):
            try:
                files += 1
                size += path.stat().st_size
            except OSError:
                continue
    age = (today - newest).days if newest else -1
    return files, size, age


def render_data(settings: Settings) -> str:
    """Taille et fraîcheur des couches stockées (âge en jours, -1 si absente)."""
    lines = [
        "# HELP abrip_data_files Nombre de fichiers Parquet par couche.",
        "# TYPE abrip_data_files gauge",
        "# HELP abrip_data_bytes Octets Parquet par couche.",
        "# TYPE abrip_data_bytes gauge",
        "# HELP abrip_data_age_days Âge en jours de la partition la plus récente.",
        "# TYPE abrip_data_age_days gauge",
    ]
    today = datetime.now(UTC).date()
    for layer, root in (
        ("raw", settings.raw_dir),
        ("curated", settings.curated_dir),
        ("analytics", settings.analytics_dir),
    ):
        files, size, age = _layer_stats(root, today)
        lines.append(f'abrip_data_files{{layer="{layer}"}} {files}')
        lines.append(f'abrip_data_bytes{{layer="{layer}"}} {size}')
        lines.append(f'abrip_data_age_days{{layer="{layer}"}} {age}')
    return "\n".join(lines) + "\n"


def render(settings: Settings) -> str:
    return render_http() + render_data(settings)
