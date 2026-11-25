"""Contrat public des endpoints récemment typés.

Ces tests sont volontairement axés sur la *forme* de la réponse : clés présentes,
types et suffixe UTC des horodatages. Le contenu métier reste couvert par les
tests d'intégration existants.
"""

from __future__ import annotations

import pytest
from _demo import requires_demo
from fastapi.testclient import TestClient

from abrip.api.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_schemas_exposes_dans_openapi(client):
    schemas = client.get("/api/openapi.json").json()["components"]["schemas"]
    assert "EventFacets" in schemas
    assert "CountryIndicator" in schemas
    assert "IncidentOut" in schemas
    assert "CountryRelationships" in schemas
    assert "AsnNames" in schemas
    assert set(schemas["EventFacets"]["properties"]) == {
        "detector",
        "severity",
        "country_iso2",
        "confidence",
    }


@requires_demo
class TestContratAvecDonnees:
    def test_facets_sont_des_cardinalites(self, client):
        body = client.get("/api/events/facets").json()
        assert set(body) == {"detector", "severity", "country_iso2", "confidence"}
        assert all(isinstance(n, int) for group in body.values() for n in group.values())

    def test_indicateurs_pays_sont_complets(self, client):
        rows = client.get("/api/countries").json()
        assert rows
        expected = {
            "country_iso2",
            "transit_dependency_ratio",
            "hhi_transit",
            "avg_upstream_count",
            "asns_observed",
            "avg_visibility",
            "prefixes_visible",
            "coverage_ratio",
            "rpki_coverage_ratio",
        }
        assert all(set(row) == expected for row in rows)

    def test_table_des_noms_est_plate(self, client):
        body = client.get("/api/asns/names").json()
        assert body
        assert all(asn.isdigit() and isinstance(name, str) for asn, name in body.items())

    def test_incidents_ont_des_dates_utc(self, client):
        body = client.get("/api/incidents").json()
        assert body["items"]
        for item in body["items"]:
            assert set(item) == {
                "incident_id",
                "prefix",
                "severity",
                "score",
                "first_seen",
                "last_seen",
                "event_ids",
                "detectors",
                "summary",
            }
            assert item["first_seen"].endswith("Z")
            assert item["last_seen"].endswith("Z")

    def test_relations_dun_pays_sont_typées(self, client):
        body = client.get("/api/countries/CM/relationships").json()
        assert set(body) == {"country_iso2", "asns", "providers", "customers", "peers"}
        assert body["country_iso2"] == "CM"
        for bucket in ("providers", "customers", "peers"):
            for relation in body[bucket]:
                assert set(relation) == {"asn", "country_iso2", "local_asns"}
                assert isinstance(relation["asn"], int)
                assert all(isinstance(asn, int) for asn in relation["local_asns"])
