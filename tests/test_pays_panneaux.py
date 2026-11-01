"""Panneaux préfixes et voisins de la page pays.

Le périmètre « pays » est l'ensemble des AS que ref_asn rattache à ce pays : les
réponses doivent être exactement ce que donneraient les endpoints par AS, mis bout
à bout. C'est ce qu'on vérifie ici, plus l'équivalence tables journalières / calcul
direct.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abrip.api.main import create_app
from abrip.api.routers import asn_explorer
from abrip.config import get_settings

pytestmark = pytest.mark.skipif(
    not (get_settings().curated_dir / "bgp_elements").exists(),
    reason="jeu de démonstration absent — lancer `abrip demo bootstrap`",
)

PAYS = ["CM", "ZA", "KE", "NG"]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def membres(client, iso: str) -> list[int]:
    items = client.get("/api/asns", params={"country": iso, "african_only": "false", "limit": 500})
    return sorted(i["asn"] for i in items.json()["items"])


def _par(client, monkeypatch, path, **params):
    monkeypatch.setattr(asn_explorer, "_use_summary", lambda *a, **k: True)
    tables = client.get(f"/api{path}", params=params)
    monkeypatch.setattr(asn_explorer, "_use_summary", lambda *a, **k: False)
    direct = client.get(f"/api{path}", params=params)
    monkeypatch.undo()
    assert tables.status_code == direct.status_code == 200
    return tables.json(), direct.json()


class TestPrefixesDuPays:
    @pytest.mark.parametrize("iso", ["CM", "ZA", "KE"])
    def test_egal_a_la_somme_des_as_membres(self, client, iso):
        pays = client.get(f"/api/countries/{iso}/prefixes", params={"limit": 500}).json()
        attendu = []
        for asn in membres(client, iso):
            for ligne in client.get(f"/api/asns/{asn}/prefixes", params={"limit": 500}).json()[
                "items"
            ]:
                attendu.append((asn, ligne["prefix"], ligne["status"], ligne["rpki_status"]))
        obtenu = [
            (i["origin_asn"], i["prefix"], i["status"], i["rpki_status"]) for i in pays["items"]
        ]
        assert sorted(obtenu) == sorted(attendu)
        assert pays["total"] == len(attendu)

    def test_chaque_ligne_designe_son_as_membre(self, client):
        pays = client.get("/api/countries/CM/prefixes", params={"limit": 500}).json()
        assert {i["origin_asn"] for i in pays["items"]} <= set(membres(client, "CM"))
        assert any(i["status"] == "unstable" for i in pays["items"])  # 102.22.16.0/22 (AS37100)

    @pytest.mark.parametrize("statut", ["new", "left", "unstable"])
    def test_filtre_de_statut(self, client, statut):
        pays = client.get("/api/countries/CM/prefixes", params={"status": statut}).json()
        assert all(i["status"] == statut for i in pays["items"])

    def test_pagination(self, client):
        page = client.get("/api/countries/CM/prefixes", params={"limit": 3, "offset": 2}).json()
        tout = client.get("/api/countries/CM/prefixes", params={"limit": 500}).json()
        assert page["total"] == tout["total"] and page["items"] == tout["items"][2:5]

    def test_code_en_minuscules(self, client):
        assert (
            client.get("/api/countries/cm/prefixes").json()
            == client.get("/api/countries/CM/prefixes").json()
        )

    def test_pays_inconnu_vide(self, client):
        corps = client.get("/api/countries/ZZ/prefixes").json()
        assert corps["items"] == [] and corps["total"] == 0
        assert client.get("/api/countries/ZZ/prefixes/timeseries").json()["points"] == []

    @pytest.mark.parametrize("iso", PAYS)
    @pytest.mark.parametrize("plage", [{}, {"from": "2026-08-26", "to": "2026-08-29"}])
    @pytest.mark.parametrize("version", ["all", "4", "6"])
    def test_tables_et_calcul_direct_concordent(self, client, monkeypatch, iso, plage, version):
        for chemin in (f"/countries/{iso}/prefixes", f"/countries/{iso}/prefixes/timeseries"):
            tables, direct = _par(client, monkeypatch, chemin, ip_version=version, **plage)
            assert tables == direct, chemin

    def test_serie_bornee_par_la_somme_des_membres(self, client):
        pays = client.get("/api/countries/CM/prefixes/timeseries").json()["points"]
        par_as = [
            client.get(f"/api/asns/{a}/prefixes/timeseries").json()["points"]
            for a in membres(client, "CM")
        ]
        for i, point in enumerate(pays):
            total = sum(p[i]["values"]["prefixes"] for p in par_as if i < len(p))
            # Un préfixe annoncé par deux AS du pays compte une fois : au plus la somme.
            assert 0 < point["values"]["prefixes"] <= total


class TestVoisinsDuPays:
    @pytest.mark.parametrize("iso", ["CM", "ZA", "KE"])
    def test_egal_aux_voisins_de_chaque_as_membre(self, client, iso):
        pays = client.get(f"/api/countries/{iso}/neighbours").json()
        attendu = []
        for asn in membres(client, iso):
            for ligne in client.get(f"/api/asns/{asn}/neighbours").json()["items"]:
                attendu.append(
                    (
                        asn,
                        ligne["asn"],
                        ligne["type"],
                        ligne["ipv4"],
                        ligne["ipv6"],
                        tuple(ligne["history"]),
                    )
                )
        obtenu = [
            (i["member_asn"], i["asn"], i["type"], i["ipv4"], i["ipv6"], tuple(i["history"]))
            for i in pays["items"]
        ]
        assert sorted(obtenu) == sorted(attendu)

    def test_decompte_par_type(self, client):
        pays = client.get("/api/countries/CM/neighbours").json()
        assert pays["counts"] == {
            t: sum(1 for i in pays["items"] if i["type"] == t)
            for t in ("provider", "customer", "peer", "unspecified")
        }
        assert pays["counts"]["customer"] >= 1  # AS37110, client de AS37100

    def test_filtre_de_type(self, client):
        pays = client.get("/api/countries/CM/neighbours", params={"type": "provider"}).json()
        assert pays["items"] and all(i["type"] == "provider" for i in pays["items"])

    def test_serie_coherente_avec_le_tableau(self, client):
        serie = client.get("/api/countries/CM/neighbours/timeseries").json()["points"]
        tableau = client.get("/api/countries/CM/neighbours").json()
        premier = serie[0]["ts"][:10]
        attendu = {t: 0 for t in ("provider", "customer", "peer", "unspecified")}
        for ligne in tableau["items"]:
            if premier in ligne["history"]:
                attendu[ligne["type"]] += 1
        assert serie[0]["values"] == attendu

    def test_pays_inconnu_vide(self, client):
        corps = client.get("/api/countries/ZZ/neighbours").json()
        assert corps["items"] == [] and corps["days"] == []

    @pytest.mark.parametrize("iso", PAYS)
    @pytest.mark.parametrize("plage", [{}, {"from": "2026-08-26", "to": "2026-08-29"}])
    def test_tables_et_calcul_direct_concordent(self, client, monkeypatch, iso, plage):
        for chemin in (f"/countries/{iso}/neighbours", f"/countries/{iso}/neighbours/timeseries"):
            tables, direct = _par(client, monkeypatch, chemin, **plage)
            assert tables == direct, chemin
