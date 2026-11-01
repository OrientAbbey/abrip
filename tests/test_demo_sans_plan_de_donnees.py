"""La démonstration n'interroge jamais IODA, RIPE Atlas ni Cloudflare Radar.

Le jeu de démonstration porte des AS et des incidents fictifs : interroger ces
sources à leur sujet n'a pas de sens, que le réseau soit joignable ou non
(correction 4). Le réglage par défaut (activé) reste valable pour les vraies
données, et doit être restitué à la fin du bootstrap.
"""

from __future__ import annotations

import pytest

from abrip.config import reload_settings
from abrip.demo.bootstrap import bootstrap, verify
from abrip.enrichment import dataplane


@pytest.fixture
def settings_isolee(monkeypatch, tmp_path):
    monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    yield settings
    monkeypatch.undo()
    reload_settings()


def test_bootstrap_sans_appel_plan_de_donnees(settings_isolee, monkeypatch):
    appels: list[str] = []

    def _interdit(nom: str):
        def _appel(*args, **kwargs):
            appels.append(nom)
            raise AssertionError(f"{nom} ne doit pas être appelé en démonstration")

        return _appel

    monkeypatch.setattr(dataplane.IodaClient, "outage_summary", _interdit("ioda.outage_summary"))
    monkeypatch.setattr(dataplane.IodaClient, "worst_score", _interdit("ioda.worst_score"))
    monkeypatch.setattr(
        dataplane.RipeAtlasClient, "connectivity_ratio", _interdit("atlas.connectivity_ratio")
    )
    monkeypatch.setattr(dataplane.CloudflareRadarClient, "outages", _interdit("radar.outages"))
    monkeypatch.setattr(
        dataplane.CloudflareRadarClient, "has_outage", _interdit("radar.has_outage")
    )
    assert settings_isolee.enrichment.dataplane_enabled is True

    bootstrap(settings_isolee)

    assert appels == []
    # Le réglage par défaut est restitué : seule cette exécution est désactivée.
    assert settings_isolee.enrichment.dataplane_enabled is True
    # Et les invariants de la démonstration tiennent toujours.
    bilan = verify(settings_isolee)
    assert bilan["status"] == "ok" and bilan["recall"] == 1.0
    assert bilan["planted"] == 5 and len(bilan["matched"]) == 5 and bilan["missed"] == []
