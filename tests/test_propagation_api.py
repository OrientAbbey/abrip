"""API du graphe de propagation d'un préfixe (ADR 0004) et de son rejeu.

Tests portés de la branche dev_cl5, adaptés au jeu de démonstration de dev_cl.
"""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient

from abrip.api.main import create_app
from abrip.config import get_settings

pytestmark = pytest.mark.skipif(
    not (get_settings().curated_dir / "bgp_elements").exists(),
    reason="jeu de démonstration absent — lancer `abrip demo bootstrap`",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


class TestPropagation:
    def test_graphe_propagation_reduit_aux_as_observes(self, client):
        # 197.155.64.0/22 : MOAS planté (deux origines, 37100 et 45090,
        # voir demo/generator.py::PLANTED) — un bon cas pour vérifier
        # l'agrégation de plusieurs chemins en un graphe.
        body = client.get("/api/prefixes/197.155.64.0%2F22/propagation").json()
        assert body["nodes"] and body["edges"]
        node_asns = {n["asn"] for n in body["nodes"]}
        assert {37100, 45090} <= node_asns
        for node in body["nodes"]:
            assert {"asn", "as_name", "country_iso2", "paths", "hidden_paths"} <= set(node)
            for path in node["paths"]:
                assert node["asn"] in path
        for edge in body["edges"]:
            assert {"source", "target", "relation"} <= set(edge)
            assert edge["relation"] in {"providers", "customers", "peerings", "unspecified"}

    def test_graphe_propagation_filtre_par_origine(self, client):
        tout = client.get("/api/prefixes/197.155.64.0%2F22/propagation").json()
        origine = client.get(
            "/api/prefixes/197.155.64.0%2F22/propagation", params={"asn": 37100}
        ).json()
        assert {n["asn"] for n in origine["nodes"]} <= {n["asn"] for n in tout["nodes"]}
        assert 45090 not in {n["asn"] for n in origine["nodes"]}

    def test_rejeu_propagation_apparition_et_fin_de_l_hijack(self, client):
        # MOAS planté le jour 3 à 09:00 pour 4 h (demo/generator.py::PLANTED) :
        # l'origine 45090 est absente avant, présente pendant, absente après.
        body = client.get(
            "/api/prefixes/197.155.64.0%2F22/propagation/replay",
            params={
                "asn": 45090,
                "from": "2026-08-27T08:00:00Z",
                "to": "2026-08-27T15:00:00Z",
                "step": 30,
            },
        ).json()
        counts = {f["ts"][11:16]: f["path_count"] for f in body["frames"]}
        assert counts["08:30"] == 0
        assert counts["10:00"] > 0
        assert counts["14:00"] == 0
        assert {"nodes", "edges", "frames", "step_minutes", "clamped"} <= set(body)
        for frame in body["frames"]:
            assert {"ts", "announcements", "withdrawals", "path_count", "nodes", "edges"} <= set(
                frame
            )
            assert all(0 <= i < len(body["edges"]) for i in frame["edges"])

    def test_rejeu_propagation_elargit_le_pas_pour_rester_sous_le_maximum(self, client):
        body = client.get(
            "/api/prefixes/197.155.64.0%2F22/propagation/replay", params={"max_frames": 50}
        ).json()
        assert len(body["frames"]) <= 51  # tranche initiale incluse
        assert body["step_minutes"] > 15

    def test_rejeu_propagation_prefixe_inconnu(self, client):
        body = client.get("/api/prefixes/1.2.3.0%2F24/propagation/replay").json()
        assert body["frames"] == [] and body["nodes"] == []

    def test_graphe_propagation_tronque_aux_cibles(self, client):
        # Chaque chemin doit s'arrêter à la première cible rencontrée depuis
        # l'origine (37100 -> 3320/6939, tous deux dans `targets`).
        body = client.get(
            "/api/prefixes/197.155.64.0%2F22/propagation",
            params={"asn": 37100, "targets": "3320,6939"},
        ).json()
        assert {n["asn"] for n in body["nodes"]} == {37100, 3320, 6939}
        for node in body["nodes"]:
            for path in node["paths"]:
                assert path[-1] in {37100, 3320, 6939}


class TestErreurs:
    def test_graphe_propagation_noms_court_et_complet(self, client):
        # Étiquette de nœud = nom court ; infobulle = nom complet de l'organisation.
        body = client.get("/api/prefixes/197.155.64.0%2F22/propagation").json()
        nodes = {n["asn"]: n for n in body["nodes"]}
        assert nodes[174]["as_name"] == "COGENT-174"
        assert "org_name" in nodes[174]
        assert nodes[174]["org_name"]


class TestPoidsEtSeuil:
    """Observations par lien et par nœud, seuil de bruit, liste des chemins."""

    URL = "/api/prefixes/197.155.64.0%2F22/propagation"

    def test_liens_et_noeuds_portent_leurs_observations(self, client):
        body = client.get(self.URL).json()
        assert body["max_observations"] == max(e["observations"] for e in body["edges"])
        assert all(e["observations"] > 0 for e in body["edges"])
        assert all(n["observations"] > 0 for n in body["nodes"])
        # Un nœud porte au moins autant d'observations que n'importe lequel de ses liens.
        for node in body["nodes"]:
            touching = [
                e["observations"]
                for e in body["edges"]
                if node["asn"] in (e["source"], e["target"])
            ]
            assert node["observations"] >= max(touching)

    def test_liste_complete_des_chemins_pour_l_export(self, client):
        body = client.get(self.URL).json()
        assert body["paths_total"] == len(body["paths"]) > 0
        observations = [p["observations"] for p in body["paths"]]
        assert observations == sorted(observations, reverse=True)
        assert all(len(p["path"]) >= 1 for p in body["paths"])

    def test_seuil_ecarte_les_chemins_rares_et_reduit_le_graphe(self, client):
        tout = client.get(self.URL).json()
        seuil = client.get(self.URL, params={"min_observations": 25}).json()
        assert seuil["paths_total"] == tout["paths_total"]
        assert seuil["paths_hidden"] > 0
        assert len(seuil["paths"]) == tout["paths_total"] - seuil["paths_hidden"]
        assert all(p["observations"] >= 25 for p in seuil["paths"])
        assert len(seuil["nodes"]) < len(tout["nodes"])

    def test_seuil_trop_haut_donne_un_graphe_vide_et_le_dit(self, client):
        body = client.get(self.URL, params={"min_observations": 100000}).json()
        assert body["nodes"] == [] and body["edges"] == []
        assert body["paths_hidden"] == body["paths_total"] > 0

    def test_seuil_invalide_refuse(self, client):
        assert client.get(self.URL, params={"min_observations": 0}).status_code == 422


class TestSurcouchesDAnomalie:
    """Statut RPKI des origines et liens qui violent le modèle valley-free."""

    def test_origine_detournee_est_rpki_invalide(self, client):
        body = client.get("/api/prefixes/197.155.64.0%2F22/propagation").json()
        origines = {n["asn"]: n["rpki"] for n in body["nodes"] if n["rpki"]}
        assert origines == {37100: "valid", 45090: "invalid"}
        assert body["moas"] is True
        # Un AS de transit n'a pas de statut RPKI : il n'est pas origine du préfixe.
        assert next(n for n in body["nodes"] if n["asn"] == 3320)["rpki"] is None

    def test_une_seule_origine_n_est_pas_un_moas(self, client):
        body = client.get(
            "/api/prefixes/197.155.64.0%2F22/propagation", params={"asn": 37100}
        ).json()
        assert body["moas"] is False

    def test_fuite_valley_free_marque_le_lien_fautif(self, client):
        body = client.get("/api/prefixes/102.64.0.0%2F12/propagation").json()
        fautifs = [e for e in body["edges"] if e["violation_observations"] > 0]
        # Même verdict que le détecteur : AS36800 réannonce vers AS174 une route apprise d'un autre fournisseur.
        assert [(e["source"], e["target"]) for e in fautifs] == [(174, 36800)]
        violants = [p for p in body["paths"] if p["valley_violation"]]
        assert violants and all(36800 in p["path"] for p in violants)
        assert fautifs[0]["violation_observations"] == sum(p["observations"] for p in violants)

    def test_prefixe_sans_fuite_n_a_aucun_lien_fautif(self, client):
        body = client.get("/api/prefixes/197.155.64.0%2F22/propagation").json()
        assert all(e["violation_observations"] == 0 for e in body["edges"])
        assert not any(p["valley_violation"] for p in body["paths"])

    def test_le_rejeu_porte_les_memes_surcouches(self, client):
        rejeu = client.get("/api/prefixes/197.155.64.0%2F22/propagation/replay").json()
        assert {n["asn"]: n["rpki"] for n in rejeu["nodes"] if n["rpki"]} == {
            37100: "valid",
            45090: "invalid",
        }
        fuite = client.get("/api/prefixes/102.64.0.0%2F12/propagation/replay").json()
        assert [
            (e["source"], e["target"]) for e in fuite["edges"] if e["violation_observations"]
        ] == [(174, 36800)]


class TestFournisseursAmont:
    """Pairs qui voient le préfixe via chaque fournisseur amont, par tranche."""

    URL = "/api/prefixes/197.155.64.0%2F22/upstreams"

    def test_fournisseurs_et_tranches_contigues(self, client):
        body = client.get(self.URL).json()
        assert {u["asn"] for u in body["upstreams"]} == {3320, 4809, 6939}
        pas = body["bucket_hours"]
        assert pas == 6  # durée de la démo (7 jours) : tranches de 6 h
        instants = [datetime.fromisoformat(p["ts"]) for p in body["points"]]
        assert all((b - a).total_seconds() == pas * 3600 for a, b in pairwise(instants))
        # Chaque tranche porte tous les fournisseurs, zéro compris.
        assert all(set(p["values"]) == {"as3320", "as4809", "as6939"} for p in body["points"])

    def test_pic_par_fournisseur_coherent_avec_les_tranches(self, client):
        body = client.get(self.URL).json()
        for u in body["upstreams"]:
            assert u["peak_peers"] == max(p["values"][f"as{u['asn']}"] for p in body["points"])
        # Triés du plus présent au moins présent.
        pics = [u["peak_peers"] for u in body["upstreams"]]
        assert pics == sorted(pics, reverse=True)

    def test_le_detournement_passe_par_un_autre_fournisseur(self, client):
        legitime = client.get(self.URL, params={"asn": 37100}).json()
        assert {u["asn"] for u in legitime["upstreams"]} == {3320, 6939}
        detourne = client.get(self.URL, params={"asn": 45090}).json()
        assert [u["asn"] for u in detourne["upstreams"]] == [4809]
        actives = [p["ts"][:10] for p in detourne["points"] if p["values"]["as4809"] > 0]
        assert actives and set(actives) == {"2026-08-27"}  # le jour du MOAS planté

    def test_pas_force_et_valide(self, client):
        quotidien = client.get(self.URL, params={"bucket_hours": 24}).json()
        assert quotidien["bucket_hours"] == 24 and len(quotidien["points"]) == 7
        assert client.get(self.URL, params={"bucket_hours": 0}).status_code == 422

    def test_prefixe_inconnu_donne_une_reponse_vide(self, client):
        body = client.get("/api/prefixes/10.0.0.0%2F8/upstreams").json()
        assert body["upstreams"] == [] and body["points"] == []

    @pytest.mark.parametrize("pas", [1, 3, 6, 12, 24, 168])
    def test_meme_resultat_que_l_agregation_duckdb(self, client, pas):
        """L'agrégation par tranche est faite en Python pour ne parcourir les données
        qu'une fois ; elle doit coïncider avec `time_bucket` et `count(DISTINCT …)`."""
        from abrip.api.deps import get_data_access

        data = get_data_access()
        attendu = {
            (row["bucket"].isoformat() + "+00:00", f"as{row['upstream']}"): row["peers"]
            for row in data.query(
                f"""SELECT time_bucket(to_hours(?), ts) AS bucket, as_path_dedup[-2] AS upstream,
                           count(DISTINCT (collector, peer_ip)) AS peers
                    FROM {data.table("bgp_elements")}
                    WHERE prefix = '197.155.64.0/22' AND elem_type = 'A' AND len(as_path_dedup) >= 2
                    GROUP BY 1, 2""",
                [pas],
            )
        }
        body = client.get(self.URL, params={"bucket_hours": pas}).json()
        obtenu = {
            (p["ts"], cle): n for p in body["points"] for cle, n in p["values"].items() if n > 0
        }
        assert obtenu == attendu


class TestCheminsDuRejeu:
    """Liste des chemins distincts et, par tranche, les indices des chemins actifs."""

    URL = "/api/prefixes/197.155.64.0%2F22/propagation/replay"

    def test_chemins_et_indices_coherents(self, client):
        body = client.get(self.URL).json()
        assert body["paths"] and all(len(p) >= 1 for p in body["paths"])
        for frame in body["frames"]:
            ids = frame["path_ids"]
            assert len(ids) == frame["path_count"] == len(set(ids))
            assert all(0 <= i < len(body["paths"]) for i in ids)
            # Les nœuds et liens d'une tranche sont exactement ceux de ses chemins actifs.
            assert frame["nodes"] == sorted({a for i in ids for a in body["paths"][i]})
            liens = {
                (body["edges"][e]["source"], body["edges"][e]["target"]) for e in frame["edges"]
            }
            assert liens == {pair for i in ids for pair in pairwise(body["paths"][i])}

    def test_liste_omise_au_dela_de_la_borne(self, client, monkeypatch):
        from abrip.api.routers import propagation

        monkeypatch.setattr(propagation, "REPLAY_MAX_PATHS", 2)
        body = client.get(self.URL).json()
        assert body["paths"] is None
        assert all("path_ids" not in f for f in body["frames"])
        assert body["nodes"] and body["edges"]  # le reste de la réponse est intact
