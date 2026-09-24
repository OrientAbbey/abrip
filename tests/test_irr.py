"""Repli IRR (RIPE DB REST) quand RPKI répond `not-found` (L4a)."""

from __future__ import annotations

import httpx
import pytest

from abrip.models import IrrStatus
from abrip.reference.irr import IrrValidator, RipeDbClient, build_irr_reference

ROUTE_RESPONSE = {
    "objects": {
        "object": [
            {
                "source": {"id": "RADB"},
                "attributes": {
                    "attribute": [
                        {"name": "route", "value": "196.60.0.0/18"},
                        {"name": "origin", "value": "AS37400"},
                        {"name": "source", "value": "RADB"},
                    ]
                },
            }
        ]
    }
}

AS_SET_RESPONSE = {
    "objects": {
        "object": [
            {
                "attributes": {
                    "attribute": [
                        {"name": "as-set", "value": "AS-LITTORAL"},
                        {"name": "members", "value": "AS37100"},
                        {"name": "members", "value": "AS37105"},
                    ]
                }
            }
        ]
    }
}


def _handler(request: httpx.Request) -> httpx.Response:
    query = dict(pair.split("=") for pair in request.url.query.decode().split("&"))
    if query.get("type-filter") == "as-set":
        return httpx.Response(200, json=AS_SET_RESPONSE)
    if "196.60" in query.get("query-string", ""):
        return httpx.Response(200, json=ROUTE_RESPONSE)
    return httpx.Response(200, json={"objects": {}})


def _failing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, text="indisponible")


@pytest.fixture
def client() -> RipeDbClient:
    return RipeDbClient(transport=httpx.MockTransport(_handler))


class TestRipeDbClient:
    def test_recherche_objets_route(self, client):
        routes = client.lookup_routes("196.60.0.0/18")
        assert routes == [("196.60.0.0/18", 37400, "RADB")]

    def test_expansion_as_set(self, client):
        assert client.expand_as_set("AS-LITTORAL") == {37100, 37105}

    def test_prefixe_sans_objet(self, client):
        assert client.lookup_routes("9.9.9.0/24") == []

    def test_service_indisponible_ne_leve_pas(self):
        failing = RipeDbClient(transport=httpx.MockTransport(_failing_handler))
        assert failing.lookup_routes("196.60.0.0/18") == []
        assert failing.expand_as_set("AS-X") == set()


class TestIrrValidator:
    def test_origine_conforme(self):
        validator = IrrValidator([("196.60.0.0/18", 37400, "RADB")])
        assert validator.validate("196.60.0.0/18", 37400) is IrrStatus.CONSISTENT

    def test_origine_divergente(self):
        validator = IrrValidator([("196.60.0.0/18", 37400, "RADB")])
        assert validator.validate("196.60.0.0/18", 99999) is IrrStatus.INCONSISTENT

    def test_prefixe_absent(self):
        validator = IrrValidator([("196.60.0.0/18", 37400, "RADB")])
        assert validator.validate("1.2.3.0/24", 1) is IrrStatus.ABSENT

    def test_origine_inconnue(self):
        validator = IrrValidator([("196.60.0.0/18", 37400, "RADB")])
        assert validator.validate("196.60.0.0/18", None) is IrrStatus.ABSENT

    def test_sous_prefixe_couvert(self):
        validator = IrrValidator([("196.60.0.0/18", 37400, "RADB")])
        assert validator.validate("196.60.0.0/20", 37400) is IrrStatus.CONSISTENT

    def test_construction_depuis_une_trame_vide(self):
        import polars as pl

        validator = IrrValidator.from_frame(pl.DataFrame())
        assert validator.validate("196.60.0.0/18", 37400) is IrrStatus.ABSENT


class TestBuildIrrReference:
    def test_agrege_plusieurs_prefixes(self, client):
        frame = build_irr_reference(client, ["196.60.0.0/18", "9.9.9.0/24"])
        assert frame.height == 1
        assert frame.row(0, named=True)["asn"] == 37400

    def test_aucun_resultat_renvoie_un_cadre_vide(self, client):
        frame = build_irr_reference(client, ["9.9.9.0/24"])
        assert frame.is_empty()
