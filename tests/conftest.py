from __future__ import annotations

from _demo import STATE


def pytest_report_header(config) -> str:
    """Une ligne en tête de rapport : sur quelles données les tests d'API vont tourner."""
    extra = len(STATE["foreign"]) + len(STATE["missing"])  # type: ignore[arg-type]
    suffix = f" ({extra} fichier(s) en trop ou manquant(s) : `abrip demo check`)" if extra else ""
    return f"données de démonstration : {STATE['state']}{suffix}"
