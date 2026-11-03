"""Explorateurs d'un AS : préfixes (New/Left/Unstable, IPv4/IPv6), historique
ROA / objets route, voisins BGP par type, relations agrégées d'un pays.

Ces tests s'appuient sur le jeu de démonstration, dont le générateur plante
volontairement un exemple de chaque cas (voir ``SCHEDULED_PREFIXES`` et
``historical_reference_snapshots`` dans ``demo/generator.py``). Ils sont
ignorés — pas en échec — si le pipeline n'a pas encore tourné.
"""

from __future__ import annotations

import pytest
from _demo import requires_demo
from fastapi.testclient import TestClient

from abrip.api.main import create_app

pytestmark = requires_demo


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _statuses(client: TestClient, asn: int, **params) -> dict[str, str]:
    body = client.get(f"/api/asns/{asn}/prefixes", params=params).json()
    return {item["prefix"]: item["status"] for item in body["items"]}


class TestPrefixTable:
    def test_new_left_stable_sur_un_meme_as(self, client):
        statuses = _statuses(client, 37300)
        assert statuses["105.20.0.0/22"] == "new"
        assert statuses["105.20.4.0/22"] == "left"
        assert statuses["197.248.0.0/16"] == "stable"

    def test_unstable_va_et_vient(self, client):
        assert _statuses(client, 37100)["102.22.16.0/22"] == "unstable"

    @pytest.mark.parametrize(
        "status,expected",
        [("new", {"105.20.0.0/22"}), ("left", {"105.20.4.0/22"}), ("unstable", set())],
    )
    def test_onglet_filtre_le_tableau(self, client, status, expected):
        assert set(_statuses(client, 37300, status=status)) == expected

    def test_actif_signifie_present_le_dernier_jour(self, client):
        items = client.get("/api/asns/37300/prefixes").json()["items"]
        active = {i["prefix"]: i["active"] for i in items}
        assert active["105.20.0.0/22"] is True  # new : présent à la fin
        assert active["105.20.4.0/22"] is False  # left : absent à la fin

    def test_onglet_ipv6_ne_montre_que_de_lipv6(self, client):
        items = client.get("/api/asns/37100/prefixes", params={"ip_version": 6}).json()["items"]
        assert items and all(i["ip_version"] == 6 for i in items)

    def test_statut_rpki_par_prefixe(self, client):
        items = client.get("/api/asns/37300/prefixes").json()["items"]
        assert {i["rpki_status"] for i in items} == {"valid"}

    def test_plage_de_dates_restreinte(self, client):
        # Sur les deux premiers jours seulement, 105.20.0.0/22 (actif dès le
        # jour 3) n'existe pas encore.
        statuses = _statuses(
            client, 37300, **{"from": "2026-08-24T00:00:00", "to": "2026-08-25T23:59:59"}
        )
        assert "105.20.0.0/22" not in statuses
        assert "105.20.4.0/22" in statuses

    def test_statut_inconnu_rejete(self, client):
        assert client.get("/api/asns/37300/prefixes", params={"status": "zzz"}).status_code == 422


class TestPrefixSeries:
    def test_ipv4_et_ipv6_different(self, client):
        def counts(version: str) -> list[int]:
            body = client.get(
                "/api/asns/37100/prefixes/timeseries", params={"ip_version": version}
            ).json()
            return [p["values"]["prefixes"] for p in body["points"]]

        v4, v6 = counts("4"), counts("6")
        allv = counts("all")
        assert v4 and v6
        assert allv == [a + b for a, b in zip(v4, v6, strict=True)]

    def test_courbe_reflete_les_apparitions(self, client):
        body = client.get("/api/asns/37300/prefixes/timeseries").json()
        values = [p["values"]["prefixes"] for p in body["points"]]
        # 1 stable + 1 « left » actif jours 0-3, + 1 « new » actif jours 3-6.
        assert values[0] == 2 and values[3] == 3 and values[-1] == 2


class TestHistory:
    def test_historique_roa_montre_le_resserrement(self, client):
        body = client.get("/api/asns/37200/prefixes/196.216.32.0/20/roa-history").json()
        assert body["prefix"] == "196.216.32.0/20" and body["specified_asn"] == 37200
        max_lengths = [row["max_length"] for row in body["rows"]]
        assert max_lengths == [24, 22]
        assert all(row["match"] for row in body["rows"])

    def test_match_faux_pour_un_autre_as(self, client):
        body = client.get("/api/asns/99999/prefixes/196.216.32.0/20/roa-history").json()
        assert body["rows"] and not any(row["match"] for row in body["rows"])

    def test_historique_objet_route(self, client):
        body = client.get("/api/asns/37400/prefixes/196.60.0.0/18/route-history").json()
        assert len(body["rows"]) == 1
        row = body["rows"][0]
        assert row["source"] == "RADB" and row["match"] is True
        assert row["first_seen"] < row["last_seen"]

    def test_prefixe_sans_objet(self, client):
        body = client.get("/api/asns/37100/prefixes/197.155.64.0/22/route-history").json()
        assert body["rows"] == []


class TestNeighbours:
    def test_types_et_compteurs(self, client):
        body = client.get("/api/asns/37100/neighbours").json()
        types = {item["asn"]: item["type"] for item in body["items"]}
        assert types[3320] == types[6939] == "provider"
        assert types[37110] == "customer"
        assert types[174] == "unspecified"
        assert body["counts"]["provider"] == 2 and body["counts"]["customer"] == 1

    @pytest.mark.parametrize(
        "kind,expected",
        [("provider", {3320, 6939}), ("customer", {37110}), ("peer", set())],
    )
    def test_onglet_filtre_le_tableau(self, client, kind, expected):
        body = client.get("/api/asns/37100/neighbours", params={"type": kind}).json()
        assert {item["asn"] for item in body["items"]} == expected

    def test_voisin_intermittent_a_un_historique_partiel(self, client):
        body = client.get("/api/asns/37100/neighbours").json()
        partial = next(i for i in body["items"] if i["asn"] == 4809)
        assert 0 < len(partial["history"]) < len(body["days"])
        assert partial["active_now"] is False

    def test_pays_et_familles_ip(self, client):
        body = client.get("/api/asns/37100/neighbours").json()
        provider = next(i for i in body["items"] if i["asn"] == 3320)
        assert provider["country_iso2"] == "US" and provider["ipv4"] and provider["ipv6"]

    def test_courbe_par_type(self, client):
        body = client.get("/api/asns/37100/neighbours/timeseries").json()
        assert body["points"]
        assert set(body["points"][0]["values"]) == {"provider", "customer", "peer", "unspecified"}

    def test_type_inconnu_rejete(self, client):
        assert client.get("/api/asns/37100/neighbours", params={"type": "zzz"}).status_code == 422


class TestCountryRelationships:
    def test_liste_les_as_du_pays_et_ses_fournisseurs(self, client):
        body = client.get("/api/countries/CM/relationships").json()
        assert body["country_iso2"] == "CM"
        assert {37100, 37105, 37110, 37200} <= set(body["asns"])
        providers = {p["asn"]: p for p in body["providers"]}
        assert set(providers) == {3320, 6939}
        # 3320 dessert plus d'AS camerounais que 6939 : le tri le reflète.
        assert body["providers"][0]["asn"] == 3320
        assert len(providers[3320]["local_asns"]) > len(providers[6939]["local_asns"])

    def test_casse_du_code_pays_ignoree(self, client):
        assert client.get("/api/countries/cm/relationships").json()["asns"]

    def test_pays_inconnu_renvoie_des_listes_vides(self, client):
        body = client.get("/api/countries/ZZ/relationships").json()
        assert body["asns"] == [] and body["providers"] == []
