"""Identifiant de requ├¬te corr├®l├® aux logs et exposition Prometheus."""

from __future__ import annotations

import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from abrip.api.main import create_app
from abrip.api.metrics import BUCKETS
from abrip.logging_conf import JsonFormatter, current_request_id


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


class TestIdentifiantDeRequete:
    def test_identifiant_genere(self, client):
        response = client.get("/api/health")
        assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])

    def test_identifiant_fourni_est_echoe(self, client):
        response = client.get("/api/health", headers={"x-request-id": "req-123"})
        assert response.headers["x-request-id"] == "req-123"

    def test_identifiant_invalide_est_remplace(self, client):
        response = client.get("/api/health", headers={"x-request-id": "x" * 200})
        assert response.headers["x-request-id"] != "x" * 200
        assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])

    def test_formatteur_json_inclut_l_identifiant(self):
        token = current_request_id.set("req-abc")
        try:
            record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
            payload = json.loads(JsonFormatter().format(record))
        finally:
            current_request_id.reset(token)
        assert payload["request_id"] == "req-abc"


class TestPrometheus:
    def test_format_et_compteurs(self, client):
        client.get("/api/meta/collectors")
        client.get("/api/metrics")  # le scrape ne se compte qu'├á la r├®ponse suivante
        response = client.get("/api/metrics")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        body = response.text
        assert "# TYPE abrip_http_requests_total counter" in body
        assert "# TYPE abrip_http_request_duration_seconds histogram" in body
        assert (
            'abrip_http_requests_total{method="GET",path="/api/meta/collectors",status="200"}'
            in body
        )
        assert 'abrip_http_requests_total{method="GET",path="/api/metrics",status="200"}' in body

    def test_seaux_sont_cumulatifs(self, client):
        client.get("/api/health")
        body = client.get("/api/metrics").text
        values = [
            float(line.rsplit(" ", 1)[1])
            for line in body.splitlines()
            if line.startswith(
                'abrip_http_request_duration_seconds_bucket{method="GET",path="/api/health",status="200"'
            )
        ]
        assert len(values) == len(BUCKETS) + 1
        assert values == sorted(values)
        assert values[-1] >= 1

    def test_jauges_de_couches(self, client):
        body = client.get("/api/metrics").text
        for layer in ("raw", "curated", "analytics"):
            assert f'abrip_data_files{{layer="{layer}"}}' in body
            assert f'abrip_data_bytes{{layer="{layer}"}}' in body
            assert f'abrip_data_age_days{{layer="{layer}"}}' in body

    def test_les_routes_sont_des_modeles_pas_des_urls(self, client):
        client.get("/api/asns/37100/prefixes")
        body = client.get("/api/metrics").text
        assert 'path="/api/asns/{asn}/prefixes"' in body
        assert 'path="/api/asns/37100/prefixes"' not in body
