"""Détecteur d'incidents sub-horaires : pic court puis retour à la normale."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
from _demo import requires_demo

from abrip.anomaly.base import DetectionContext
from abrip.anomaly.engine import run_detection
from abrip.anomaly.subhour import SubHourWithdrawalDetector
from abrip.config import get_settings
from abrip.storage.catalog import Catalog

JOUR = datetime(2026, 8, 24, tzinfo=UTC).date()
DEBUT = datetime(2026, 8, 24, 12, 0, tzinfo=UTC).replace(tzinfo=None)

CONFIG = {
    "window_minutes": 15,
    "min_peers": 4,
    "ratio": 3.0,
    "max_duration_minutes": 60,
}


def _elements(scenarios: dict[str, list[int]]) -> pl.LazyFrame:
    rows = []
    for prefix, counts in scenarios.items():
        for index, count in enumerate(counts):
            when = DEBUT + timedelta(minutes=15 * index)
            for peer in range(count):
                rows.append(
                    {
                        "ts": when,
                        "prefix": prefix,
                        "origin_asn": 37100,
                        "peer_asn": 1000 + peer,
                        "elem_type": "W",
                        "collector": "rrc19",
                    }
                )
    return pl.DataFrame(rows).lazy()


def _contexte(scenarios: dict[str, list[int]]) -> DetectionContext:
    return DetectionContext(
        start=JOUR,
        end=JOUR,
        elements=_elements(scenarios),
        asn_country={37100: "ZA"},
        run_id="test-subhour",
    )


def test_pic_court_est_detecte_une_seule_fois():
    scenarios = {
        "197.1.0.0/24": [1, 8, 1],  # pic puis retour : signalé
        "197.1.1.0/24": [1, 8, 8],  # pas de retour : ignoré
        "197.1.2.0/24": [1, 2, 1],  # moins de 4 peers : ignoré
    }
    events = SubHourWithdrawalDetector(CONFIG).detect(_contexte(scenarios))
    assert len(events) == 1
    event = events[0]
    assert event.detector == "subhour_withdrawal"
    assert event.prefix == "197.1.0.0/24"
    assert event.asns_involved == [37100]
    assert event.first_seen == DEBUT + timedelta(minutes=15)
    assert event.evidence["duration_minutes"] == 15


def test_sans_retour_dans_la_fenetre_aucun_evenement():
    events = SubHourWithdrawalDetector(CONFIG).detect(_contexte({"197.1.0.0/24": [1, 8, 0]}))
    assert events == []


def test_desactive_par_defaut():
    config = get_settings().detection["detectors"]["subhour_withdrawal"]
    assert config["enabled"] is False
    assert config["window_minutes"] == 15


@requires_demo
def test_integration_dans_le_moteur(tmp_path):
    settings = get_settings().model_copy(deep=True)
    settings.detection["detectors"]["subhour_withdrawal"]["enabled"] = True
    resultat = run_detection(
        settings,
        Catalog(tmp_path / "catalog.duckdb"),
        JOUR,
        JOUR,
        detectors=["subhour_withdrawal"],
    )
    assert "subhour_withdrawal" in resultat["per_detector"]
