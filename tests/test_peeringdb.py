"""Corroboration multi-source des relations CAIDA (L3)."""

from __future__ import annotations

import httpx
import polars as pl
import pytest

from abrip.reference.irr import RipeDbClient
from abrip.reference.peeringdb import (
    PeeringDbClient,
    build_relationship_evidence,
    corroborate_peer,
    corroborate_provider,
)


def _peeringdb_handler(request: httpx.Request) -> httpx.Response:
    query = dict(pair.split("=") for pair in request.url.query.decode().split("&"))
    if request.url.path.endswith("/net"):
        asn = query.get("asn")
        if asn == "36800":
            return httpx.Response(200, json={"data": [{"asn": 36800, "irr_as_set": "AS-GULFNET"}]})
        return httpx.Response(200, json={"data": [{"asn": int(asn), "irr_as_set": ""}]})
    if request.url.path.endswith("/netixlan"):
        mapping = {"37100": [1, 2], "37200": [2, 3], "99999": []}
        ixs = mapping.get(query.get("asn"), [])
        return httpx.Response(200, json={"data": [{"ix_id": i} for i in ixs]})
    return httpx.Response(404, json={"data": []})


def _irr_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "objects": {
                "object": [
                    {
                        "attributes": {
                            "attribute": [
                                {"name": "as-set", "value": "AS-GULFNET"},
                                {"name": "members", "value": "AS36700"},
                            ]
                        }
                    }
                ]
            }
        },
    )


@pytest.fixture
def peeringdb() -> PeeringDbClient:
    return PeeringDbClient(transport=httpx.MockTransport(_peeringdb_handler))


@pytest.fixture
def irr() -> RipeDbClient:
    return RipeDbClient(transport=httpx.MockTransport(_irr_handler))


class TestCorroboratePeer:
    def test_deux_as_au_meme_point_dechange(self, peeringdb):
        assert corroborate_peer(37100, 37200, peeringdb) is True

    def test_aucun_point_dechange_commun(self, peeringdb):
        assert corroborate_peer(37100, 99999, peeringdb) is False

    def test_as_absent_de_peeringdb(self, peeringdb):
        assert corroborate_peer(99999, 99999, peeringdb) is False


class TestCorroborateProvider:
    def test_client_present_dans_las_set_du_fournisseur(self, peeringdb, irr):
        assert corroborate_provider(36800, 36700, peeringdb, irr) is True

    def test_client_absent_de_las_set(self, peeringdb, irr):
        assert corroborate_provider(36800, 99999, peeringdb, irr) is False

    def test_fournisseur_sans_as_set_declare(self, peeringdb, irr):
        assert corroborate_provider(37100, 36700, peeringdb, irr) is False


class TestBuildRelationshipEvidence:
    def test_liens_corrobores_et_non_corrobores(self, peeringdb, irr):
        caida = pl.DataFrame(
            {
                "as_a": [37100, 36800],
                "as_b": [37200, 36700],
                "relationship": ["p2p", "p2c"],
            }
        )
        evidence = build_relationship_evidence(caida, peeringdb, irr)
        rows = {(r["as_a"], r["as_b"]): set(r["sources"]) for r in evidence.iter_rows(named=True)}
        assert rows[(37100, 37200)] == {"caida", "peeringdb"}
        assert rows[(36800, 36700)] == {"caida", "irr"}

    def test_relations_vides(self, peeringdb, irr):
        evidence = build_relationship_evidence(pl.DataFrame(), peeringdb, irr)
        assert evidence.is_empty()

    def test_source_defaillante_ne_bloque_pas_les_autres_liens(self, irr):
        def broken(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("réseau indisponible", request=request)

        broken_peeringdb = PeeringDbClient(transport=httpx.MockTransport(broken))
        caida = pl.DataFrame({"as_a": [37100], "as_b": [37200], "relationship": ["p2p"]})
        evidence = build_relationship_evidence(caida, broken_peeringdb, irr)
        # La corroboration échoue proprement : le lien CAIDA reste présent,
        # simplement non corroboré, plutôt que de faire échouer tout l'appel.
        assert evidence.height == 1
        assert evidence.row(0, named=True)["sources"] == ["caida"]
