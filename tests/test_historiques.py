"""Historiques détaillés : périodes d'annonce d'un préfixe par AS, relation entre deux AS.

Le tableau des préfixes ne donne que le premier et le dernier jour vus, ce qui cache
les interruptions d'un préfixe instable ; le tableau des voisins ne dit pas quand une
relation a existé en IPv4 ou en IPv6. Ces deux endpoints rendent ce détail.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

import pytest
from _demo import requires_demo
from fastapi.testclient import TestClient

from abrip.api.main import create_app
from abrip.api.routers import asn_explorer
from abrip.api.routers.asn_explorer import _presence_status, _runs


def d(day: int) -> date:
    return date(2026, 8, day)


class TestPeriodes:
    def test_une_seule_periode_continue(self):
        assert _runs({d(24): 5, d(25): 3}, [d(24), d(25), d(26)]) == [
            {
                "first_seen": "2026-08-24",
                "last_seen": "2026-08-25",
                "days": 2,
                "observations": 8,
                "active": False,
            }
        ]

    def test_un_trou_coupe_la_periode(self):
        runs = _runs({d(24): 1, d(27): 1, d(28): 1}, [d(24), d(25), d(26), d(27), d(28)])
        assert [(r["first_seen"], r["last_seen"], r["days"]) for r in runs] == [
            ("2026-08-24", "2026-08-24", 1),
            ("2026-08-27", "2026-08-28", 2),
        ]
        assert [r["active"] for r in runs] == [False, True]

    def test_jour_sans_collecte_ne_coupe_pas(self):
        """Le 26 n'a aucune donnée : ce n'est pas une absence du préfixe."""
        runs = _runs({d(25): 1, d(27): 1}, [d(25), d(27)])
        assert len(runs) == 1 and runs[0]["days"] == 2

    def test_jamais_vu(self):
        assert _runs({}, [d(24), d(25)]) == []

    def test_aucun_jour(self):
        assert _runs({}, []) == []


class TestStatutDeLEvolution:
    """New / Left / Unstable pour les voisins : même règle que les préfixes."""

    JOURS: ClassVar[list[date]] = [d(24), d(25), d(26), d(27)]

    def test_stable_present_a_chaque_jour(self):
        assert _presence_status({d(24), d(25), d(26), d(27)}, self.JOURS) == "stable"

    def test_new_absent_au_debut_present_a_la_fin(self):
        assert _presence_status({d(26), d(27)}, self.JOURS) == "new"

    def test_left_present_au_debut_absent_a_la_fin(self):
        assert _presence_status({d(24), d(25)}, self.JOURS) == "left"

    def test_unstable_avec_un_trou(self):
        assert _presence_status({d(24), d(27)}, self.JOURS) == "unstable"

    def test_unstable_apparu_et_disparu_a_l_interieur(self):
        assert _presence_status({d(25), d(26)}, self.JOURS) == "unstable"

    def test_sans_jour_de_collecte(self):
        assert _presence_status(set(), []) == "stable"

    def test_jamais_present(self):
        assert _presence_status(set(), self.JOURS) == "unstable"


pytestmark_data = requires_demo


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _par(client, monkeypatch, path, **params):
    """Réponse depuis les tables journalières et par calcul direct."""
    monkeypatch.setattr(asn_explorer, "_use_summary", lambda *a, **k: True)
    tables = client.get(f"/api{path}", params=params)
    monkeypatch.setattr(asn_explorer, "_use_summary", lambda *a, **k: False)
    direct = client.get(f"/api{path}", params=params)
    monkeypatch.undo()
    assert tables.status_code == direct.status_code == 200
    return tables.json(), direct.json()


@pytestmark_data
class TestHistoriqueDUnPrefixe:
    URL = "/api/asns/37100/prefixes/102.22.16.0%2F22/history"

    def test_prefixe_instable_trois_periodes(self, client):
        body = client.get(self.URL).json()
        assert [(r["first_seen"], r["last_seen"]) for r in body["items"]] == [
            ("2026-08-24", "2026-08-25"),
            ("2026-08-27", "2026-08-27"),
            ("2026-08-29", "2026-08-30"),
        ]
        assert [r["active"] for r in body["items"]] == [False, False, True]

    def test_total_des_observations_coherent_avec_la_frise(self, client):
        body = client.get(self.URL).json()
        assert sum(r["observations"] for r in body["items"]) == sum(
            x["observations"] for x in body["daily"]
        )
        assert body["daily"][0]["day"] == body["start"]
        assert body["daily"][-1]["day"] == body["end"]

    def test_prefixe_stable_une_periode(self, client):
        body = client.get("/api/asns/37100/prefixes/102.22.8.0%2F22/history").json()
        assert len(body["items"]) == 1 and body["items"][0]["days"] == 7

    def test_plage_restreinte(self, client):
        body = client.get(self.URL, params={"from": "2026-08-26", "to": "2026-08-28"}).json()
        assert (body["start"], body["end"]) == ("2026-08-26", "2026-08-28")
        assert [(r["first_seen"], r["last_seen"]) for r in body["items"]] == [
            ("2026-08-27", "2026-08-27")
        ]

    def test_autre_as_ne_voit_pas_ce_prefixe(self, client):
        assert client.get("/api/asns/37300/prefixes/102.22.16.0%2F22/history").json()["items"] == []

    def test_prefixe_inconnu(self, client):
        body = client.get("/api/asns/37100/prefixes/10.0.0.0%2F8/history").json()
        assert body["items"] == [] and body["daily"]  # la frise garde ses jours, à zéro

    @pytest.mark.parametrize(
        "prefixe", ["102.22.16.0%2F22", "102.22.8.0%2F22", "197.155.64.0%2F22"]
    )
    @pytest.mark.parametrize("asn", [37100, 37200, 45090])
    @pytest.mark.parametrize("plage", [{}, {"from": "2026-08-26", "to": "2026-08-29"}])
    def test_tables_et_calcul_direct_concordent(self, client, monkeypatch, prefixe, asn, plage):
        tables, direct = _par(
            client, monkeypatch, f"/asns/{asn}/prefixes/{prefixe}/history", **plage
        )
        assert tables == direct


@pytestmark_data
class TestHistoriqueDUneRelation:
    def test_fournisseur_present_toute_la_periode_en_ipv4_et_ipv6(self, client):
        body = client.get("/api/asns/37100/neighbours/3320/history").json()
        assert body["type"] == "provider"
        assert [(r["first_seen"], r["last_seen"], r["active"]) for r in body["ipv4"]] == [
            ("2026-08-24", "2026-08-30", True)
        ]
        assert body["ipv6"] and body["ipv6"][0]["days"] >= 1

    def test_relation_intermittente(self, client):
        body = client.get("/api/asns/37100/neighbours/4809/history").json()
        assert body["type"] == "unspecified"
        assert [(r["first_seen"], r["last_seen"]) for r in body["ipv4"]] == [
            ("2026-08-27", "2026-08-27"),
            ("2026-08-29", "2026-08-29"),
        ]
        assert body["ipv6"] == []

    def test_client_ipv4_seulement(self, client):
        body = client.get("/api/asns/37100/neighbours/37110/history").json()
        assert body["type"] == "customer" and body["ipv4"] and body["ipv6"] == []

    def test_frise_quotidienne_alignee_sur_les_periodes(self, client):
        body = client.get("/api/asns/37100/neighbours/4809/history").json()
        actifs = [x["day"] for x in body["daily"] if x["ipv4"]]
        assert actifs == ["2026-08-27", "2026-08-29"]
        assert all("observations" not in r for r in body["ipv4"])

    def test_voisin_jamais_vu(self, client):
        body = client.get("/api/asns/37100/neighbours/64500/history").json()
        assert body["ipv4"] == [] and body["ipv6"] == [] and body["type"] == "unspecified"

    @pytest.mark.parametrize("voisin", [3320, 6939, 4809, 37110, 174, 64500])
    @pytest.mark.parametrize("plage", [{}, {"from": "2026-08-26", "to": "2026-08-29"}])
    def test_tables_et_calcul_direct_concordent(self, client, monkeypatch, voisin, plage):
        tables, direct = _par(
            client, monkeypatch, f"/asns/37100/neighbours/{voisin}/history", **plage
        )
        assert tables == direct

    def test_coherent_avec_le_tableau_des_voisins(self, client):
        """La frise du tableau et l'historique détaillé racontent la même chose."""
        tableau = client.get("/api/asns/37100/neighbours").json()
        ligne = next(r for r in tableau["items"] if r["asn"] == 4809)
        detail = client.get("/api/asns/37100/neighbours/4809/history").json()
        jours = {x["day"] for x in detail["daily"] if x["ipv4"] or x["ipv6"]}
        assert jours == {d[:10] for d in ligne["history"]}
        assert detail["type"] == ligne["type"]


@pytestmark_data
class TestStatutDesVoisins:
    def _statuts(self, client, **params):
        corps = client.get("/api/asns/37100/neighbours", params=params).json()
        return {i["asn"]: i["status"] for i in corps["items"]}, corps

    def test_relation_intermittente_est_instable(self, client):
        statuts, corps = self._statuts(client)
        assert statuts[4809] == "unstable"
        assert all(v == "stable" for k, v in statuts.items() if k != 4809)
        assert corps["status_counts"] == {"stable": 4, "new": 0, "left": 0, "unstable": 1}

    @pytest.mark.parametrize(
        ("plage", "attendu"),
        [
            ({"from": "2026-08-28", "to": "2026-08-29"}, "new"),
            ({"from": "2026-08-29", "to": "2026-08-30"}, "left"),
            ({"from": "2026-08-27", "to": "2026-08-29"}, "unstable"),
        ],
    )
    def test_le_statut_suit_la_plage(self, client, plage, attendu):
        statuts, _ = self._statuts(client, **plage)
        assert statuts[4809] == attendu

    def test_decomptes_egaux_aux_lignes(self, client):
        _, corps = self._statuts(client)
        for statut, n in corps["status_counts"].items():
            assert n == sum(1 for i in corps["items"] if i["status"] == statut)

    def test_coherent_avec_l_historique_detaille(self, client):
        """Une relation en plusieurs périodes est instable ; en une seule sur toute la plage, stable."""
        for voisin in (3320, 4809, 37110):
            statut = next(
                i["status"]
                for i in client.get("/api/asns/37100/neighbours").json()["items"]
                if i["asn"] == voisin
            )
            detail = client.get(f"/api/asns/37100/neighbours/{voisin}/history").json()
            periodes = detail["ipv4"] if detail["ipv4"] else detail["ipv6"]
            assert (statut == "unstable") == (len(periodes) > 1)

    def test_pays_somme_des_statuts_des_as(self, client):
        pays = client.get("/api/countries/CM/neighbours").json()
        total = {"stable": 0, "new": 0, "left": 0, "unstable": 0}
        for asn in (37100, 37105, 37110, 37200):
            for statut, n in (
                client.get(f"/api/asns/{asn}/neighbours").json()["status_counts"].items()
            ):
                total[statut] += n
        assert pays["status_counts"] == total
