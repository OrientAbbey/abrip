"""Alertes d'incidents : sévérité, déduplication, échecs réseau, commande CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from typer.testing import CliRunner

from abrip.alerting import load_recent_incidents, notify_incidents
from abrip.cli import app
from abrip.config import get_settings, reload_settings
from abrip.models import Incident, Severity
from abrip.storage.catalog import Catalog


def incident(incident_id: str, severity: Severity = Severity.CRITICAL) -> Incident:
    now = datetime.now(UTC)
    return Incident(
        incident_id=incident_id,
        prefix="102.22.8.0/22",
        severity=severity,
        score=0.9,
        first_seen=now,
        last_seen=now,
        event_ids=["e1"],
        detectors=["withdrawal_spike"],
        summary="Retraits massifs",
    )


class FauxClient:
    def __init__(self, statut: int = 200) -> None:
        self.statut = statut
        self.appels: list[dict[str, object]] = []

    def post(self, url: str, *, json: dict[str, object], timeout: float):
        self.appels.append({"url": url, "json": json, "timeout": timeout})
        return type("Reponse", (), {"status_code": self.statut})()


@pytest.fixture
def contexte(tmp_path):
    settings = get_settings().model_copy(deep=True)
    settings.data_dir = tmp_path
    settings.alerts.webhook_url = "https://example.test/hook"
    catalog = Catalog(settings.catalog_path)
    return settings, catalog


def test_selection_par_severite(contexte):
    settings, catalog = contexte
    client = FauxClient()
    bilan = notify_incidents(
        settings,
        catalog,
        [
            incident("critique"),
            incident("surveiller", Severity.WATCH),
            incident("info", Severity.INFO),
        ],
        client,
    )
    assert bilan["selected"] == 1
    assert bilan["sent"] == 1
    assert len(client.appels) == 1
    assert "102.22.8.0/22" in client.appels[0]["json"]["text"]


def test_deduplication_par_incident_id(contexte):
    settings, catalog = contexte
    client = FauxClient()
    for _ in range(2):
        notify_incidents(settings, catalog, [incident("meme-incident")], client)
    assert len(client.appels) == 1


def test_echecs_reseau_non_bloquant(contexte):
    settings, catalog = contexte
    client = FauxClient(statut=500)
    bilan = notify_incidents(settings, catalog, [incident("echec")], client)
    assert bilan["failed"] == 1
    assert bilan["sent"] == 0
    assert FauxClient().appels == []
    # Rien n'a été mémorisé : un essai ultérieur peut réussir.
    ok = FauxClient()
    assert notify_incidents(settings, catalog, [incident("echec")], ok)["sent"] == 1
    assert len(ok.appels) == 1


def test_sans_webhook_aucun_envoi(contexte):
    settings, catalog = contexte
    settings.alerts.webhook_url = None
    client = FauxClient()
    bilan = notify_incidents(settings, catalog, [incident("un")], client)
    assert bilan == {"candidates": 1, "skipped": 1}
    assert client.appels == []


def test_chargement_des_incidents_recents(contexte):
    settings, _ = contexte
    root = settings.analytics_dir / "incidents"
    root.mkdir(parents=True, exist_ok=True)
    recent = incident("recent")
    old = incident("ancien")
    old.last_seen = datetime.now(UTC) - timedelta(days=5)
    pl.DataFrame([recent.model_dump(), old.model_dump()], strict=False).write_parquet(
        root / "part-00000.parquet"
    )
    charges = load_recent_incidents(settings, days=1)
    assert [item.incident_id for item in charges] == ["recent"]


def test_commande_detect_alert_sans_webhook(tmp_path, monkeypatch):
    monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / "data"))
    reload_settings()
    try:
        resultat = CliRunner().invoke(app, ["detect", "alert", "--days", "1"])
        assert resultat.exit_code == 0, resultat.output
        assert json.loads(resultat.output)["skipped"] == 0
    finally:
        monkeypatch.undo()
        reload_settings()
