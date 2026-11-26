"""Qualification humaine L5 : verdicts, précision et exemptions versionnées."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import yaml
from typer.testing import CliRunner

from abrip.alerting import notify_incidents
from abrip.cli import app
from abrip.config import get_settings, reload_settings
from abrip.models import Incident, Severity
from abrip.qualification import (
    Allowlist,
    AllowlistEntry,
    is_allowed,
    load_allowlist,
    precision_by_detector,
)
from abrip.storage.catalog import Catalog


def _json_sortie(sortie: str):
    """La sortie CLI peut contenir des lignes de log JSON avant le résultat."""
    lignes = [ligne for ligne in sortie.splitlines() if not ligne.startswith('{"ts":')]
    return json.loads("\n".join(lignes))


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    yield Catalog(settings.catalog_path)
    monkeypatch.undo()
    reload_settings()


def test_verdicts_persistes(catalogue):
    catalogue.record_feedback(
        event_id="e1", verdict="legitimate", author="alice", note="multi-homing connu"
    )
    catalogue.record_feedback(event_id="e2", verdict="malicious", author="bob")
    rows = {row["event_id"]: row for row in catalogue.all_feedback()}
    assert rows["e1"]["verdict"] == "legitimate"
    assert rows["e1"]["note"] == "multi-homing connu"
    assert rows["e2"]["author"] == "bob"
    with pytest.raises(ValueError, match="Verdict inconnu"):
        catalogue.record_feedback(event_id="e3", verdict="peut-etre", author="alice")


def test_precision_par_detecteur():
    events = [
        {"event_id": "e1", "detector": "moas"},
        {"event_id": "e2", "detector": "moas"},
        {"event_id": "e3", "detector": "withdrawal"},
        {"event_id": "e4", "detector": "withdrawal"},
    ]
    feedback = [
        {"event_id": "e1", "verdict": "legitimate"},
        {"event_id": "e2", "verdict": "malicious"},
        {"event_id": "e3", "verdict": "unknown"},
    ]
    result = {row["detector"]: row for row in precision_by_detector(events, feedback)}
    assert result["moas"]["qualified"] == 2
    assert result["moas"]["false_positive_rate"] == 0.5
    assert result["moas"]["precision"] == 0.5
    assert "withdrawal" not in result  # unknown exclu du dénominateur


def test_allowlist_chargee_depuis_yaml(tmp_path):
    path = tmp_path / "allowlist.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {"asn": 37100, "detector": "moas", "reason": "multi-homing"},
                    {"prefix": "102.22.8.0/22", "reason": "test"},
                ]
            }
        ),
        encoding="utf-8",
    )
    allowlist = load_allowlist(path)
    assert len(allowlist.entries) == 2
    assert is_allowed(allowlist, prefix="192.0.2.0/24", asns=[37100], detectors=["moas"])
    assert not is_allowed(allowlist, prefix="192.0.2.0/24", asns=[37100], detectors=["withdrawal"])
    assert is_allowed(allowlist, prefix="102.22.8.0/22", asns=[64500], detectors=["moas"])
    assert not is_allowed(allowlist, prefix=None, asns=[], detectors=["moas"])


def test_allowlist_absente(catalogue, tmp_path):
    assert load_allowlist(tmp_path / "absent.yaml").entries == []


def test_commandes_label_et_precision(catalogue):
    resultat = CliRunner().invoke(
        app,
        ["detect", "label", "e1", "--verdict", "legitimate", "--author", "alice", "--note", "ok"],
    )
    assert resultat.exit_code == 0, resultat.output
    assert _json_sortie(resultat.output)["verdict"] == "legitimate"
    assert catalogue.all_feedback()[0]["event_id"] == "e1"

    resultat = CliRunner().invoke(app, ["detect", "precision"])
    assert resultat.exit_code == 0, resultat.output
    assert _json_sortie(resultat.output) == []


def test_commande_allowlist(catalogue):
    resultat = CliRunner().invoke(app, ["detect", "allowlist"])
    assert resultat.exit_code == 0, resultat.output
    assert isinstance(_json_sortie(resultat.output), list)


def test_allowlist_tais_une_alerte(catalogue, monkeypatch):
    import abrip.qualification as qualification

    monkeypatch.setattr(
        qualification,
        "load_allowlist",
        lambda: Allowlist(entries=[AllowlistEntry(prefix="102.22.8.0/22", reason="connu")]),
    )

    class Client:
        def __init__(self) -> None:
            self.appels = 0

        def post(self, url, *, json, timeout):
            self.appels += 1
            return type("Reponse", (), {"status_code": 200})()

    settings = get_settings().model_copy(deep=True)
    settings.alerts.webhook_url = "https://example.test/hook"
    now = datetime.now(UTC)
    incident = Incident(
        incident_id="un",
        prefix="102.22.8.0/22",
        severity=Severity.CRITICAL,
        score=0.9,
        first_seen=now,
        last_seen=now,
        event_ids=[],
        detectors=["moas"],
        summary="test",
    )
    client = Client()
    bilan = notify_incidents(settings, catalogue, [incident], client)
    assert bilan["selected"] == 0
    assert client.appels == 0
