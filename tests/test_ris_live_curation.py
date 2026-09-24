"""Curation d'une fenêtre RIS Live capturée en direct (L7, granularité).

Le flux RIS Live lui-même (WebSocket) n'est pas accessible depuis cet
environnement de test — ce n'est pas ce qui est vérifié ici. Ce qui compte et
qui est testé : une fenêtre déjà capturée (fichier JSONL, tel que
``ingestion.ris_live.capture`` l'écrit) est correctement intégrée à la couche
curée, et cette intégration est idempotente.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from abrip.config import reload_settings
from abrip.etl.curate import curate_ris_live_window
from abrip.storage.catalog import Catalog
from abrip.storage.parquet import partition_path


@pytest.fixture
def settings(tmp_path):
    os.environ["ABRIP_DATA_DIR"] = str(tmp_path)
    s = reload_settings()
    s.ensure_dirs()
    yield s
    del os.environ["ABRIP_DATA_DIR"]
    reload_settings()


@pytest.fixture
def catalog(settings):
    return Catalog(settings.catalog_path)


def _write_jsonl(settings, moment: datetime, messages: list[dict]):
    directory = settings.raw_dir / "ris-live" / "stream" / f"date={moment:%Y-%m-%d}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"ris-live.{moment:%Y%m%d.%H%M}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for message in messages:
            handle.write(json.dumps(message) + "\n")
    return path


def _sample_messages(base_ts: float) -> list[dict]:
    return [
        {
            "timestamp": base_ts,
            "peer": "196.60.1.5",
            "peer_asn": "6939",
            "path": [6939, 37100],
            "host": "rrc19",
            "announcements": [{"next_hop": "196.60.1.5", "prefixes": ["197.155.99.0/24"]}],
        },
        {
            "timestamp": base_ts + 1,
            "peer": "196.60.1.9",
            "peer_asn": "174",
            "path": [174, 37100],
            "host": "rrc19",
            "announcements": [{"next_hop": "196.60.1.9", "prefixes": ["197.155.99.0/24"]}],
        },
        {
            "timestamp": base_ts + 2,
            "peer": "196.60.1.20",
            "peer_asn": "3320",
            "path": [3320, 45090],
            "host": "rrc19",
            "withdrawals": ["197.155.64.0/22"],
        },
    ]


class TestCurateRisLiveWindow:
    def test_curation_dune_fenetre(self, settings, catalog):
        now = datetime.now(UTC)
        jsonl = _write_jsonl(settings, now, _sample_messages(now.timestamp()))

        result = curate_ris_live_window(settings, catalog, jsonl)
        assert result["elements"] == 3

        target = partition_path(
            settings.curated_dir,
            "bgp_elements",
            date=str(now.date()),
            collector="ris-live.rrc19",
        )
        frame = pl.read_parquet(sorted(target.glob("*.parquet")))
        assert frame.height == 3
        assert set(frame["elem_type"].to_list()) == {"A", "W"}

    def test_idempotent_sur_rejeu(self, settings, catalog):
        now = datetime.now(UTC)
        jsonl = _write_jsonl(settings, now, _sample_messages(now.timestamp()))

        curate_ris_live_window(settings, catalog, jsonl)
        target = partition_path(
            settings.curated_dir,
            "bgp_elements",
            date=str(now.date()),
            collector="ris-live.rrc19",
        )
        first = pl.read_parquet(sorted(target.glob("*.parquet"))).height

        curate_ris_live_window(settings, catalog, jsonl)
        second = pl.read_parquet(sorted(target.glob("*.parquet"))).height
        assert second == first == 3

    def test_fusion_avec_une_partition_existante(self, settings, catalog):
        now = datetime.now(UTC)
        first_window = _write_jsonl(settings, now, _sample_messages(now.timestamp()))
        curate_ris_live_window(settings, catalog, first_window)

        later = now + timedelta(minutes=5)
        second_window = _write_jsonl(
            settings,
            later,
            [
                {
                    "timestamp": later.timestamp(),
                    "peer": "196.60.1.30",
                    "peer_asn": "37400",
                    "path": [37400],
                    "host": "rrc19",
                    "announcements": [{"next_hop": "196.60.1.30", "prefixes": ["196.60.0.0/18"]}],
                }
            ],
        )
        curate_ris_live_window(settings, catalog, second_window)

        target = partition_path(
            settings.curated_dir,
            "bgp_elements",
            date=str(now.date()),
            collector="ris-live.rrc19",
        )
        frame = pl.read_parquet(sorted(target.glob("*.parquet")))
        # Les 3 éléments de la première fenêtre PLUS le nouveau, sans perte :
        # une fusion, pas un remplacement.
        assert frame.height == 4

    def test_fichier_sans_message_exploitable(self, settings, catalog):
        now = datetime.now(UTC)
        directory = settings.raw_dir / "ris-live" / "stream" / f"date={now:%Y-%m-%d}"
        directory.mkdir(parents=True, exist_ok=True)
        empty = directory / "ris-live.vide.jsonl"
        empty.write_text("", encoding="utf-8")
        result = curate_ris_live_window(settings, catalog, empty)
        assert result == {"elements": 0}
