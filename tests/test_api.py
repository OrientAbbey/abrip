"""Tests d'intégration de l'API, sur le jeu de démonstration.

Ils vérifient le contrat public — codes de statut, forme des réponses, cas
d'erreur — et non le contenu métier, qui dépend des données chargées. Si aucune
donnée n'a été produite, les tests sont ignorés plutôt que rouges : l'API se
comporte alors correctement en renvoyant 503, ce qui est testé à part.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abrip.api.main import create_app
from abrip.config import get_settings


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def has_data() -> bool:
    settings = get_settings()
    return (settings.curated_dir / "bgp_elements").exists()


requires_data = pytest.mark.skipif(
    not (get_settings().curated_dir / "bgp_elements").exists(),
    reason="jeu de démonstration absent — lancer `abrip demo bootstrap`",
)


class TestSante:
    def test_health_repond_toujours(self, client):
        # /health ne doit jamais dépendre des données : c'est la route qu'on
        # interroge justement quand rien ne marche.
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert isinstance(body["layers"], list)

    def test_collecteurs_listes(self, client):
        response = client.get("/api/meta/collectors")
        assert response.status_code == 200
        names = {c["name"] for c in response.json()}
        assert "route-views.napafrica" in names
        roles = {c["role"] for c in response.json()}
        assert roles <= {"local", "external"}

    def test_documentation_disponible(self, client):
        assert client.get("/api/openapi.json").status_code == 200


@requires_data
class TestEvenements:
    def test_liste_paginee(self, client):
        response = client.get("/api/events", params={"limit": 5})
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"items", "total", "limit", "offset"}
        assert len(body["items"]) <= 5

    def test_preuves_desserialisees(self, client):
        items = client.get("/api/events", params={"limit": 1}).json()["items"]
        assert items, "le jeu de démonstration doit contenir au moins un événement"
        # `evidence` est stocké en JSON sérialisé : l'API doit rendre un objet,
        # pas une chaîne à reparser côté client.
        assert isinstance(items[0]["evidence"], dict)
        assert items[0]["explanation"]

    def test_filtre_par_detecteur(self, client):
        facets = client.get("/api/events/facets").json()
        detector = next(iter(facets["detector"]))
        items = client.get("/api/events", params={"detector": detector}).json()["items"]
        assert all(e["detector"] == detector for e in items)

    def test_severite_inconnue_rejetee(self, client):
        response = client.get("/api/events", params={"severity": "catastrophique"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_parameters"

    def test_evenement_inconnu(self, client):
        response = client.get("/api/events/identifiant-inexistant")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_chronologie_complete(self, client):
        event_id = client.get("/api/events", params={"limit": 1}).json()["items"][0]["event_id"]
        body = client.get(f"/api/events/{event_id}/timeline").json()
        assert set(body) >= {"event", "incident", "related_events", "churn", "visibility"}

    def test_horodatages_portent_le_fuseau(self, client):
        # FR1 (revue du 24/09/2026) : un horodatage sans fuseau explicite est
        # réinterprété en heure locale par `new Date(...)` côté navigateur.
        # `first_seen`/`last_seen` doivent porter un offset UTC explicite.
        item = client.get("/api/events", params={"limit": 1}).json()["items"][0]
        for field in ("first_seen", "last_seen"):
            value = item[field]
            assert value.endswith("+00:00") or value.endswith("Z"), (field, value)


@requires_data
class TestMetriques:
    def test_serie_de_churn(self, client):
        body = client.get("/api/metrics/churn").json()
        assert body["metric"] == "churn"
        assert body["points"], "la série ne doit pas être vide sur le jeu de démonstration"
        assert "announcements" in body["points"][0]["values"]

    def test_parametres_exclusifs(self, client):
        response = client.get("/api/metrics/churn", params={"prefix": "10.0.0.0/8", "asn": 1})
        assert response.status_code == 400

    def test_pays_inconnu(self, client):
        response = client.get("/api/metrics/countries", params={"country": "ZZ"})
        assert response.status_code == 404

    def test_visibilite_bornee(self, client):
        points = client.get("/api/metrics/visibility").json()["points"]
        ratios = [
            p["values"]["visibility_ratio"] for p in points if p["values"]["visibility_ratio"]
        ]
        assert all(0.0 <= r <= 1.0 for r in ratios)


@requires_data
class TestExploration:
    def test_liste_des_as(self, client):
        body = client.get("/api/asns", params={"limit": 3}).json()
        assert body["items"]
        assert all(item["asn"] > 0 for item in body["items"])

    def test_fiche_as_inconnu(self, client):
        response = client.get("/api/asns/4294967000")
        assert response.status_code == 404

    def test_fiche_prefixe_avec_barre_oblique(self, client):
        prefix = client.get("/api/prefixes", params={"limit": 1}).json()["items"][0]["prefix"]
        response = client.get(f"/api/prefixes/{prefix}")
        assert response.status_code == 200
        assert response.json()["prefix"] == prefix

    def test_recherche_unifiee(self, client):
        asn = client.get("/api/asns", params={"limit": 1}).json()["items"][0]["asn"]
        hits = client.get("/api/search", params={"q": str(asn)}).json()
        assert any(hit["kind"] in {"asn", "prefix"} for hit in hits)


@requires_data
class TestTopologie:
    """Point 6, lot 2 : onglets Préfixes/Voisins BGP de la fiche ASN."""

    def test_serie_temporelle_prefixes(self, client):
        asn = client.get("/api/asns", params={"limit": 1}).json()["items"][0]["asn"]
        body = client.get(f"/api/asns/{asn}/prefixes/timeseries").json()
        assert body["points"], "au moins un point sur la fenêtre de démonstration"
        assert all({"day", "prefixes"} <= set(p) for p in body["points"])

    def test_serie_temporelle_filtree_par_famille(self, client):
        asn = client.get("/api/asns", params={"limit": 1}).json()["items"][0]["asn"]
        v4 = client.get(f"/api/asns/{asn}/prefixes/timeseries", params={"family": "4"}).json()
        v6 = client.get(f"/api/asns/{asn}/prefixes/timeseries", params={"family": "6"}).json()
        # Les deux familles ne peuvent pas dépasser, ensemble, le total "all".
        total = client.get(f"/api/asns/{asn}/prefixes/timeseries").json()
        by_day = {p["day"]: p["prefixes"] for p in total["points"]}
        for p in v4["points"] + v6["points"]:
            assert p["prefixes"] <= by_day.get(p["day"], 0)

    def test_prefixes_change_new_left_unstable(self, client):
        # Données synthétiques fixes du générateur de démo (voir
        # demo/generator.py::_BGP_PREFIX_CHURN) : AS37200 gagne un nouveau
        # préfixe le jour 4 ("new"), AS37105 cesse d'annoncer le sien après
        # le jour 3 ("left"), AS36900 en a un qui flappe ("unstable").
        new = client.get("/api/asns/37200/prefixes/changes").json()["items"]
        assert new == [
            {
                "prefix": "196.216.32.0/20",
                "active": True,
                "change": "new",
                "first_seen": "2026-08-28",
                "last_seen": "2026-08-30",
                "has_roa": True,
                "has_route_object": True,
            }
        ]

        left = client.get("/api/asns/37105/prefixes/changes").json()["items"]
        assert len(left) == 1
        assert left[0]["change"] == "left"
        assert left[0]["active"] is False

        unstable = client.get("/api/asns/36900/prefixes/changes").json()["items"]
        changes = {item["prefix"]: item["change"] for item in unstable}
        assert changes["105.16.0.0/16"] == "unstable"
        assert changes["196.1.96.0/20"] == "stable"

    def test_changements_prefixes_filtre_par_onglet(self, client):
        asn = client.get("/api/asns", params={"limit": 1}).json()["items"][0]["asn"]
        for tab in ("new", "left", "unstable"):
            body = client.get(f"/api/asns/{asn}/prefixes/changes", params={"tab": tab}).json()
            assert all(item["change"] == tab for item in body["items"])

    def test_voisins_par_relation(self, client):
        # AS37400 (trois fournisseurs synthétiques) a une diversité de
        # relations suffisante pour exercer les quatre onglets.
        allowed = {"all", "providers", "customers", "peerings", "unspecified"}
        tout = client.get("/api/asns/37400/neighbors").json()["items"]
        assert tout, "AS37400 doit avoir au moins un voisin observé"
        seen_relations = set()
        for item in tout:
            assert {
                "asn",
                "relation",
                "active",
                "has_v4",
                "has_v6",
                "first_seen",
                "last_seen",
            } <= set(item)
            seen_relations.add(item["relation"])
        assert seen_relations <= allowed - {"all"}

        providers = client.get(
            "/api/asns/37400/neighbors", params={"relation": "providers"}
        ).json()["items"]
        assert all(item["relation"] == "providers" for item in providers)
        assert {item["asn"] for item in providers} <= {item["asn"] for item in tout}

    def test_historique_roa_dun_prefixe(self, client):
        # 197.32.0.0/13 (AS37500) : ROA présente en début de fenêtre,
        # retirée le jour 4 -> "left".
        body = client.get("/api/prefixes/197.32.0.0%2F13/roa-history").json()
        assert body["items"]
        row = next(r for r in body["items"] if r["asn"] == 37500)
        assert row["change"] == "left"
        assert {"prefix", "asn", "max_len", "ta", "first_seen", "last_seen", "match"} <= set(row)

    def test_historique_objet_route_dun_prefixe(self, client):
        # 105.184.0.0/13 (AS37400) : objet IRR "AFRINIC" retiré le jour 4,
        # l'objet "RADB" de base reste stable — les deux sources coexistent.
        body = client.get("/api/prefixes/105.184.0.0%2F13/route-object-history").json()
        changes = {(r["source"], r["change"]) for r in body["items"]}
        assert ("AFRINIC", "left") in changes
        assert ("RADB", "stable") in changes


class TestErreurs:
    def test_route_api_inconnue(self, client):
        response = client.get("/api/route-qui-nexiste-pas")
        assert response.status_code == 404
        assert "error" in response.json()

    def test_parametre_hors_bornes(self, client):
        response = client.get("/api/events", params={"limit": 0})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_parameters"

    def test_pas_de_lecture_hors_frontend(self, client):
        """C1 — la route SPA ne doit jamais servir un fichier hors de frontend/dist.

        La route catch-all n'existe que si le frontend est compilé : le test est
        ignoré sinon, pour rester vert sur une installation sans `npm run build`.
        """
        settings = get_settings()
        static = settings.project_root / settings.api.static_dir
        if not (static / "index.html").exists():
            pytest.skip("frontend non compilé — lancer `make build`")
        response = client.get("/..%2f..%2fconfigs%2fsettings.yaml")
        assert response.status_code == 200
        assert "data_dir" not in response.text, (
            "un chemin avec `..` ne doit jamais exposer un fichier hors du dossier frontend"
        )
