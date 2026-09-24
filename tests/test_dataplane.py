"""Confirmation d'un événement par le plan de données (L1) : IODA, RIPE Atlas,
Cloudflare Radar."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from abrip.enrichment.dataplane import (
    CloudflareRadarClient,
    IodaClient,
    RipeAtlasClient,
    confirm_event,
    enrich_events,
)
from abrip.models import Confidence, DataplaneVerdict, Event, Severity


def _event(**overrides) -> Event:
    base = dict(
        event_id="evt-1",
        detector="visibility_drop",
        severity=Severity.CRITICAL,
        score=0.8,
        confidence=Confidence.MEDIUM,
        first_seen=datetime(2026, 8, 30, 15, 0),
        last_seen=datetime(2026, 8, 30, 18, 0),
        prefix="197.32.0.0/13",
        asns_involved=[37500],
        country_iso2="CM",
    )
    base.update(overrides)
    return Event(**base)


def _ioda(score: float):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": None, "data": [{"scores": [{"value": score}]}]})

    return IodaClient(transport=httpx.MockTransport(handler))


def _atlas(connected: int, total: int = 10):
    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(pair.split("=") for pair in request.url.query.decode().split("&"))
        count = connected if query.get("status_name") == "Connected" else total
        return httpx.Response(200, json={"count": count})

    return RipeAtlasClient(transport=httpx.MockTransport(handler))


def _radar(outage: bool | None, token: str | None = "fake-token"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {"annotations": [{"eventType": "OUTAGE"}] if outage else []},
            },
        )

    return CloudflareRadarClient(api_token=token, transport=httpx.MockTransport(handler))


class TestIodaClient:
    def test_score_le_plus_severe_retenu(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"error": None, "data": [{"scores": [{"value": 0.2}, {"value": 0.9}]}]},
            )

        client = IodaClient(transport=httpx.MockTransport(handler))
        assert (
            client.worst_score("country", "CM", datetime(2026, 1, 1), datetime(2026, 1, 2)) == 0.9
        )

    def test_service_indisponible_renvoie_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        client = IodaClient(transport=httpx.MockTransport(handler))
        assert (
            client.worst_score("country", "CM", datetime(2026, 1, 1), datetime(2026, 1, 2)) is None
        )

    def test_reponse_en_erreur_ignoree(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "bad request", "data": []})

        client = IodaClient(transport=httpx.MockTransport(handler))
        assert (
            client.worst_score("country", "CM", datetime(2026, 1, 1), datetime(2026, 1, 2)) is None
        )


class TestRipeAtlasClient:
    def test_ratio_de_connectivite(self):
        client = _atlas(connected=3, total=10)
        assert client.connectivity_ratio(country="CM") == pytest.approx(0.3)

    def test_aucun_filtre_renvoie_none(self):
        client = _atlas(connected=3)
        assert client.connectivity_ratio() is None

    def test_aucune_sonde_renvoie_none(self):
        client = _atlas(connected=0, total=0)
        assert client.connectivity_ratio(country="ZZ") is None


class TestCloudflareRadarClient:
    def test_sans_jeton_ne_requete_pas(self):
        client = CloudflareRadarClient(api_token=None)
        assert client.outages(location="CM") == []
        assert client.has_outage(location="CM") is None

    def test_avec_jeton_detecte_une_coupure(self):
        client = _radar(outage=True)
        assert client.has_outage(location="CM") is True

    def test_avec_jeton_aucune_coupure(self):
        client = _radar(outage=False)
        assert client.has_outage(location="CM") is False


class TestConfirmEvent:
    def test_confirme_par_ioda_et_atlas(self):
        report = confirm_event(_event(), _ioda(0.9), _atlas(connected=1, total=10))
        assert report.verdict is DataplaneVerdict.CONFIRMED
        assert report.evidence["ioda_score"] == 0.9

    def test_contredit_quand_tout_est_calme(self):
        report = confirm_event(_event(), _ioda(0.02), _atlas(connected=9, total=10))
        assert report.verdict is DataplaneVerdict.CONTRADICTED

    def test_inconclusif_sans_donnee_exploitable(self):
        event = _event(country_iso2=None, asns_involved=[])
        report = confirm_event(event, _ioda(0.02), _atlas(connected=9, total=10))
        assert report.verdict is DataplaneVerdict.INCONCLUSIVE

    def test_radar_confirme_malgre_les_deux_autres_sources_calmes(self):
        report = confirm_event(
            _event(), _ioda(0.02), _atlas(connected=9, total=10), _radar(outage=True)
        )
        assert report.verdict is DataplaneVerdict.CONFIRMED
        assert report.evidence["radar_outage_reported"] is True

    def test_radar_sans_jeton_naffecte_pas_le_verdict(self):
        with_token_off = confirm_event(
            _event(), _ioda(0.02), _atlas(connected=9, total=10), _radar(outage=True, token=None)
        )
        assert with_token_off.verdict is DataplaneVerdict.CONTRADICTED
        assert "radar_outage_reported" not in with_token_off.evidence


class TestEnrichEvents:
    def test_retrograde_un_critique_contredit(self):
        events = [_event()]
        enriched = enrich_events(events, _ioda(0.02), _atlas(connected=9, total=10))
        assert enriched[0].severity is Severity.WATCH
        assert enriched[0].dataplane_verdict is DataplaneVerdict.CONTRADICTED

    def test_ne_retrograde_pas_si_confirme(self):
        events = [_event()]
        enriched = enrich_events(events, _ioda(0.9), _atlas(connected=1, total=10))
        assert enriched[0].severity is Severity.CRITICAL

    def test_info_non_soumis_a_confirmation(self):
        events = [_event(severity=Severity.INFO, score=0.1)]
        enriched = enrich_events(events, _ioda(0.9), _atlas(connected=1, total=10))
        assert enriched[0].dataplane_verdict is DataplaneVerdict.NOT_ATTEMPTED
