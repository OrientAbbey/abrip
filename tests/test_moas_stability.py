"""Filtre de stabilité historique du détecteur MOAS (L6, filtre 2).

Contrairement au filtre « même organisation » (voir ``test_detection.py`` et le
scénario jumeau du générateur de démonstration), ce filtre a besoin de données
*antérieures* à la fenêtre de détection — precisément ce que le jeu de
démonstration standard ne fournit pas (une seule fenêtre de 7 jours, sans
historique avant). Ce fichier construit donc son propre historique minimal
plutôt que de s'appuyer sur ``abrip demo bootstrap``.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import polars as pl
import pytest

from abrip.anomaly.engine import _compute_stable_pairs, build_context
from abrip.config import reload_settings
from abrip.models import BGP_ELEMENTS_SCHEMA
from abrip.storage.parquet import partition_path, write_frame

DETECTION_START = datetime(2026, 9, 1).date()
LOOKBACK_DAY = DETECTION_START - timedelta(days=5)


def _rows_for_day(day, prefix: str, origin: int, peer_count: int) -> list[dict]:
    base = datetime.combine(day, datetime.min.time())
    return [
        {
            "ts": base + timedelta(hours=h),
            "collector": "rrc19",
            "peer_asn": 3320 + peer,
            "peer_ip": f"196.60.1.{peer}",
            "elem_type": "A",
            "prefix": prefix,
            "prefix_ip_version": 4,
            "prefix_len": int(prefix.split("/")[1]),
            "origin_asn": origin,
            "as_path": [3320 + peer, origin],
            "as_path_dedup": [3320 + peer, origin],
            "as_path_len": 2,
            "has_as_set": False,
            "next_hop": f"196.60.1.{peer}",
            "communities": [],
            "med": None,
            "local_pref": None,
            "source_file": "test",
        }
        for h in range(3)
        for peer in range(peer_count)
    ]


@pytest.fixture
def settings(tmp_path):
    os.environ["ABRIP_DATA_DIR"] = str(tmp_path)
    s = reload_settings()
    s.ensure_dirs()
    yield s
    del os.environ["ABRIP_DATA_DIR"]
    reload_settings()


def _write_day(settings, day, *entries: tuple[str, int, int]) -> None:
    """Écrit la partition ``(jour, rrc19)`` en une seule fois.

    ``write_frame`` remplace tout le contenu du répertoire à chaque appel
    (partition idempotente, voir ``storage.parquet``) : plusieurs appels pour
    le même jour s'écraseraient l'un l'autre au lieu de s'accumuler. Chaque
    tuple ``entries`` est ``(prefix, origin, peer_count)``.
    """
    rows: list[dict] = []
    for prefix, origin, peer_count in entries:
        rows.extend(_rows_for_day(day, prefix, origin, peer_count))
    frame = pl.DataFrame(rows, schema=BGP_ELEMENTS_SCHEMA, strict=False)
    target = partition_path(settings.curated_dir, "bgp_elements", date=str(day), collector="rrc19")
    write_frame(frame, target)


class TestComputeStablePairs:
    def test_couple_present_plusieurs_jours_est_stable(self, settings):
        for offset in (5, 4, 3):
            _write_day(
                settings, DETECTION_START - timedelta(days=offset), ("10.0.0.0/22", 64500, 3)
            )
        config = {
            "ignore_stable_origins": True,
            "stability_lookback_days": 14,
            "stability_min_days_seen": 3,
        }
        pairs = _compute_stable_pairs(settings, DETECTION_START, config, None)
        assert ("10.0.0.0/22", 64500) in pairs

    def test_couple_vu_une_seule_fois_nest_pas_stable(self, settings):
        _write_day(settings, DETECTION_START - timedelta(days=2), ("10.0.0.0/22", 64500, 3))
        config = {
            "ignore_stable_origins": True,
            "stability_lookback_days": 14,
            "stability_min_days_seen": 3,
        }
        pairs = _compute_stable_pairs(settings, DETECTION_START, config, None)
        assert ("10.0.0.0/22", 64500) not in pairs

    def test_absence_totale_dhistorique(self, settings):
        config = {
            "ignore_stable_origins": True,
            "stability_lookback_days": 14,
            "stability_min_days_seen": 3,
        }
        assert _compute_stable_pairs(settings, DETECTION_START, config, None) == frozenset()

    def test_filtre_desactive_ne_calcule_rien(self, settings):
        for offset in (5, 4, 3):
            _write_day(
                settings, DETECTION_START - timedelta(days=offset), ("10.0.0.0/22", 64500, 3)
            )
        config = {"ignore_stable_origins": False}
        assert _compute_stable_pairs(settings, DETECTION_START, config, None) == frozenset()

    def test_premier_deploiement_sans_historique_ne_leve_pas(self, settings):
        # Aucune partition curee du tout : ni la couche curee elle-meme.
        config = {
            "ignore_stable_origins": True,
            "stability_lookback_days": 14,
            "stability_min_days_seen": 3,
        }
        assert _compute_stable_pairs(settings, DETECTION_START, config, None) == frozenset()


class TestMoasStabiliteDeBoutEnBout:
    """Le scénario complet : un challenger stable depuis plusieurs jours ne
    doit produire aucun événement MOAS, même sans donnée AS2Org ni relation
    CAIDA connue — les deux autres filtres du détecteur seraient ici inopérants."""

    def test_challenger_stable_nest_pas_signale(self, settings):
        prefix = "196.201.0.0/22"
        incumbent, challenger = 36900, 64777

        # Historique : le challenger est déjà présent depuis 4 jours avant la
        # fenêtre de détection — un multihoming ancien, pas une apparition.
        for offset in (4, 3, 2, 1):
            day = DETECTION_START - timedelta(days=offset)
            _write_day(settings, day, (prefix, incumbent, 3), (prefix, challenger, 3))

        # Fenêtre de détection : les deux origines continuent d'annoncer.
        _write_day(settings, DETECTION_START, (prefix, incumbent, 3), (prefix, challenger, 3))

        context = build_context(settings, DETECTION_START, DETECTION_START, collectors=["rrc19"])
        assert context.is_stable_origin(prefix, challenger)

        from abrip.anomaly.detectors import MoasDetector

        detector = MoasDetector({"min_peers_per_origin": 2, "ignore_stable_origins": True})
        events = detector.detect(context)
        assert events == []

    def test_challenger_recent_est_signale(self, settings):
        # Contre-épreuve : sans historique préalable, le même scénario doit
        # produire un événement — sinon le test précédent ne prouverait rien.
        prefix = "196.201.4.0/22"
        incumbent, challenger = 36900, 64778
        _write_day(settings, DETECTION_START, (prefix, incumbent, 3), (prefix, challenger, 3))

        context = build_context(settings, DETECTION_START, DETECTION_START, collectors=["rrc19"])
        assert not context.is_stable_origin(prefix, challenger)

        from abrip.anomaly.detectors import MoasDetector

        detector = MoasDetector({"min_peers_per_origin": 2, "ignore_stable_origins": True})
        events = detector.detect(context)
        matching = [e for e in events if e.prefix == prefix]
        assert len(matching) == 1
