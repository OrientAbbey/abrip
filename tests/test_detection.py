"""Détection : comportement unitaire et non-régression de bout en bout.

Le test qui compte vraiment est `test_rappel_sur_verite_terrain` : le générateur
de démonstration plante des anomalies connues, le pipeline doit les retrouver
toutes. C'est ce qui empêche un réglage de seuil « qui améliore les chiffres »
de casser silencieusement la détection.
"""

from __future__ import annotations

import polars as pl
import pytest

from abrip.anomaly.base import confidence_from_peers, robust_zscore, severity_from_score
from abrip.config import get_settings
from abrip.models import Confidence, Severity


class TestScoreRobuste:
    def test_pic_isole_detecte(self):
        # Série calme avec un pic : le pic doit ressortir nettement.
        series = pl.Series([10.0, 11.0, 9.0, 10.0, 12.0, 10.0, 11.0, 300.0])
        scores = robust_zscore(series)
        assert scores[-1] > 10
        assert all(abs(s) < 5 for s in scores[:-1])

    def test_serie_constante_ne_produit_pas_de_pic(self):
        # Écart nul : une division naïve exploserait, la fonction doit rendre 0.
        scores = robust_zscore(pl.Series([7.0] * 10))
        assert all(s == 0.0 for s in scores)

    def test_resistance_aux_valeurs_extremes(self):
        # Avec un écart-type classique, le premier pic gonflerait la dispersion
        # et masquerait le second. Le MAD, lui, reste sur le bruit de fond.
        series = pl.Series([10.0, 12.0, 9.0, 11.0, 10.0, 13.0, 9.0, 12.0, 500.0, 10.0, 11.0, 260.0])
        scores = robust_zscore(series)
        assert scores[8] > 20 and scores[11] > 20
        assert all(abs(scores[i]) < 3 for i in (0, 1, 2, 3, 4, 5, 6, 7, 9, 10))

    def test_serie_vide(self):
        assert len(robust_zscore(pl.Series([], dtype=pl.Float64))) == 0


class TestSeverite:
    @pytest.mark.parametrize(
        "score,attendu",
        [
            (0.9, Severity.CRITICAL),
            (0.65, Severity.CRITICAL),
            (0.5, Severity.WATCH),
            (0.1, Severity.INFO),
        ],
    )
    def test_seuils_par_defaut(self, score, attendu):
        assert severity_from_score(score) is attendu

    def test_seuils_configurables(self):
        config = {"correlation": {"severity_thresholds": {"critical": 0.9, "watch": 0.8}}}
        assert severity_from_score(0.85, config) is Severity.WATCH
        assert severity_from_score(0.95, config) is Severity.CRITICAL


class TestConfiance:
    def test_signal_isole(self):
        # Un seul point de vue : peut être un artefact de session.
        assert confidence_from_peers(1, 1) is Confidence.LOW

    def test_plusieurs_peers_un_collecteur(self):
        assert confidence_from_peers(4, 1) is Confidence.MEDIUM

    def test_corroboration_multi_collecteurs(self):
        assert confidence_from_peers(8, 3) is Confidence.HIGH

    def test_deux_collecteurs_suffisent_pour_moyenne(self):
        assert confidence_from_peers(1, 2) is Confidence.MEDIUM


def _analytics_ready() -> bool:
    return (get_settings().analytics_dir / "events").exists()


requires_pipeline = pytest.mark.skipif(
    not _analytics_ready(), reason="pipeline non exécuté — lancer `abrip demo bootstrap`"
)


@requires_pipeline
class TestNonRegression:
    def test_rappel_sur_verite_terrain(self):
        """Toutes les anomalies plantées doivent être retrouvées.

        Le rappel est exigé à 100 % parce que le jeu est synthétique et que les
        anomalies y sont franches : en manquer une signale une régression, pas
        une difficulté intrinsèque.
        """
        from abrip.demo.bootstrap import verify

        report = verify(get_settings())
        assert report["recall"] == 1.0, f"anomalies manquées : {report.get('missed')}"

    def test_identifiants_deterministes(self):
        from datetime import datetime

        from abrip.models import Event

        window = datetime(2026, 8, 27, 9, 0)
        first = Event.make_id("moas", "197.155.64.0/22", [37100, 45090], window)
        second = Event.make_id("moas", "197.155.64.0/22", [45090, 37100], window)
        third = Event.make_id(
            "moas", "197.155.64.0/22", [37100, 45090], datetime(2026, 8, 27, 10, 0)
        )
        # L'ordre des AS ne doit pas changer l'identifiant : c'est le même
        # événement qu'on le décrive dans un sens ou dans l'autre.
        assert first == second
        assert first != third

    def test_evenements_lies_a_des_as_africains(self):
        settings = get_settings()
        events = pl.read_parquet(settings.analytics_dir / "events" / "*.parquet")
        # Le filtre africain est le cœur du périmètre : un événement sans aucun
        # AS impliqué ne devrait jamais être conservé.
        assert events.height > 0
        assert events["asns_involved"].list.len().min() > 0

    def test_scores_bornes(self):
        settings = get_settings()
        events = pl.read_parquet(settings.analytics_dir / "events" / "*.parquet")
        assert events["score"].min() >= 0.0
        assert events["score"].max() <= 1.0

    def test_incidents_referencent_des_evenements_existants(self):
        settings = get_settings()
        events = pl.read_parquet(settings.analytics_dir / "events" / "*.parquet")
        incidents_path = settings.analytics_dir / "incidents"
        if not incidents_path.exists():
            pytest.skip("aucun incident produit")
        incidents = pl.read_parquet(incidents_path / "*.parquet")
        known = set(events["event_id"].to_list())
        for row in incidents.iter_rows(named=True):
            assert set(row["event_ids"]) <= known
