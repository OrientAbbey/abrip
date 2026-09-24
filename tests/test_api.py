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
