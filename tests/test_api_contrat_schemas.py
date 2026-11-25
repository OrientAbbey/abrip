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
    assert {"PrefixRow", "NeighboursResponse", "RoaHistoryResponse", "PeriodRun"} <= set(schemas)
    assert {"AsnDetail", "PrefixDetail", "EventTimeline"} <= set(schemas)
    assert {"PropagationResponse", "PropagationReplayResponse", "UpstreamsResponse"} <= set(schemas)
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

    def test_lignes_de_prefixes_ont_des_dates_utc(self, client):
        body = client.get("/api/asns/37300/prefixes").json()
        assert body["items"]
        expected = {
            "prefix",
            "origin_asn",
            "ip_version",
            "active",
            "status",
            "first_seen",
            "last_seen",
            "days_active",
            "days_total",
            "rpki_status",
            "irr_status",
        }
        for item in body["items"]:
            assert set(item) == expected
            assert item["first_seen"].endswith("Z")
            assert item["last_seen"].endswith("Z")

    def test_voisins_ont_le_schéma_complet_sans_champ_de_pays(self, client):
        body = client.get("/api/asns/37100/neighbours").json()
        assert body["items"]
        assert set(body) == {"asn", "days", "counts", "status_counts", "items"}
        assert set(body["items"][0]) == {
            "asn",
            "type",
            "ipv4",
            "ipv6",
            "first_seen",
            "last_seen",
            "history",
            "active_now",
            "status",
            "country_iso2",
        }
        assert body["items"][0]["first_seen"].endswith("Z")
        pays = client.get("/api/countries/CM/neighbours").json()
        if pays["items"]:
            assert "member_asn" in pays["items"][0]

    def test_historiques_gardent_leurs_champs_specifiques(self, client):
        roa = client.get("/api/asns/37200/prefixes/196.216.32.0/20/roa-history").json()
        if roa["rows"]:
            assert {"trust_anchor", "max_length"} <= set(roa["rows"][0])
            assert "source" not in roa["rows"][0]
        irr = client.get("/api/asns/37400/prefixes/196.60.0.0/18/route-history").json()
        if irr["rows"]:
            assert "source" in irr["rows"][0]
            assert "max_length" not in irr["rows"][0]

    def test_periodes_avec_et_sans_observations(self, client):
        prefix = client.get("/api/asns/37100/prefixes/102.22.8.0%2F22/history").json()
        if prefix["items"]:
            assert {"first_seen", "last_seen", "days", "observations", "active"} == set(
                prefix["items"][0]
            )
        neighbours = client.get("/api/asns/37100/neighbours/4809/history").json()
        for family in ("ipv4", "ipv6"):
            for run in neighbours[family]:
                assert "observations" not in run
                assert set(run) == {"first_seen", "last_seen", "days", "active"}
        assert all(set(day) == {"day", "ipv4", "ipv6"} for day in neighbours["daily"])

    def test_fiche_as_est_typée_et_en_utc(self, client):
        body = client.get("/api/asns/37100").json()
        assert set(body) == {"asn", "identity", "prefixes", "upstreams", "events"}
        assert set(body["identity"]) == {
            "asn",
            "country_iso2",
            "rir",
            "is_african",
            "allocation_date",
            "snapshot_date",
        }
        for row in body["prefixes"]:
            assert row["first_seen"].endswith("Z")
            assert row["last_seen"].endswith("Z")
        for row in body["events"]:
            assert row["first_seen"].endswith("Z")

    def test_fiche_prefixe_est_typée_et_en_utc(self, client):
        body = client.get("/api/prefixes/102.22.8.0%2F22").json()
        assert set(body) == {"prefix", "origins", "top_paths", "visibility", "roa", "events"}
        for row in body["origins"]:
            assert row["first_seen"].endswith("Z")
            assert row["last_seen"].endswith("Z")
        for row in body["visibility"]:
            assert row["snapshot_ts"].endswith("Z")
        for row in body["events"]:
            assert row["first_seen"].endswith("Z")

    def test_timeline_evenement_est_typée_et_en_utc(self, client):
        events = client.get("/api/events", params={"limit": 1}).json()["items"]
        assert events
        body = client.get(f"/api/events/{events[0]['event_id']}/timeline").json()
        assert set(body) == {"event", "incident", "related_events", "churn", "visibility"}
        assert body["event"]["first_seen"].endswith("Z")
        assert body["event"]["last_seen"].endswith("Z")
        for point in body["churn"]:
            assert point["ts"].endswith("Z")
        for point in body["visibility"]:
            assert point["ts"].endswith("Z")

    def test_graphe_de_propagation_est_typé(self, client):
        body = client.get("/api/prefixes/102.22.8.0%2F22/propagation").json()
        assert set(body) == {
            "prefix",
            "asn",
            "start",
            "end",
            "nodes",
            "edges",
            "paths",
            "paths_total",
            "paths_hidden",
            "max_observations",
            "moas",
        }
        if body["nodes"]:
            assert {
                "asn",
                "as_name",
                "org_name",
                "country_iso2",
                "rpki",
                "paths",
                "hidden_paths",
                "observations",
            } <= set(body["nodes"][0])
        if body["edges"]:
            assert {
                "source",
                "target",
                "relation",
                "observations",
                "violation_observations",
            } <= set(body["edges"][0])

    def test_rejeu_garde_path_ids_conditionnel(self, client):
        body = client.get("/api/prefixes/102.22.8.0%2F22/propagation/replay").json()
        assert set(body) == {
            "prefix",
            "asn",
            "start",
            "end",
            "step_minutes",
            "warmup_hours",
            "clamped",
            "nodes",
            "edges",
            "paths",
            "frames",
        }
        assert body["frames"]
        if body["paths"] is None:
            assert all("path_ids" not in frame for frame in body["frames"])
        else:
            assert all("path_ids" in frame for frame in body["frames"])
        for edge in body["edges"]:
            assert "observations" not in edge

    def test_fournisseurs_amont_gardent_les_cles_dynamiques(self, client):
        body = client.get("/api/prefixes/102.22.8.0%2F22/upstreams").json()
        assert set(body) == {"prefix", "asn", "bucket_hours", "upstreams", "points"}
        for point in body["points"]:
            assert set(point) == {"ts", "values"}
            assert all(key.startswith("as") and key[2:].isdigit() for key in point["values"])
