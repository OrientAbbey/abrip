"""Tables journalières (analytics/daily.py) : même réponse que le calcul direct.

Les endpoints par AS et la liste des préfixes répondent depuis de petites tables
journalières quand elles sont à jour, et relisent bgp_elements sinon. Les deux
chemins doivent donner exactement le même résultat : on les compare sur la
démonstration, plages de dates, versions IP et filtres compris.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from types import SimpleNamespace

import polars as pl
import pytest
from fastapi.testclient import TestClient

from abrip.analytics.daily import (
    ADJACENCY,
    PREFIX_ORIGIN,
    compute_daily_summaries,
    summary_is_current,
)
from abrip.api.main import create_app
from abrip.api.routers import asn_explorer, explore
from abrip.config import get_settings


def _frame(rows: list[dict]) -> pl.DataFrame:
    base = {
        "collector": "rrc19",
        "peer_asn": 174,
        "peer_ip": "1.1.1.1",
        "prefix_ip_version": 4,
        "prefix_len": 22,
        "next_hop": "0.0.0.0",
        "source_file": "test",
    }
    frame = pl.DataFrame([{**base, **row} for row in rows])
    return frame.with_columns(
        pl.col("ts").str.to_datetime().dt.cast_time_unit("us"),
        pl.col("origin_asn").cast(pl.UInt32),
        pl.col("as_path_dedup").cast(pl.List(pl.UInt32)),
        pl.col("prefix_ip_version").cast(pl.UInt8),
    )


def _curated(tmp_path, rows: list[dict], day: str = "2026-08-24"):
    directory = tmp_path / "curated" / "bgp_elements" / f"date={day}" / "collector=rrc19"
    directory.mkdir(parents=True)
    _frame(rows).write_parquet(directory / "part-00000.parquet")
    return SimpleNamespace(
        curated_dir=tmp_path / "curated",
        analytics_dir=tmp_path / "analytics",
        etl=SimpleNamespace(sort_memory_limit="256MB"),
    )


def _lire(settings, name: str, day: str = "2026-08-24") -> pl.DataFrame:
    return pl.read_parquet(settings.analytics_dir / name / f"date={day}" / "part-00000.parquet")


class TestCalculDesTables:
    def test_prefixe_par_origine_et_par_jour(self, tmp_path):
        settings = _curated(
            tmp_path,
            [
                {
                    "ts": "2026-08-24 01:00:00",
                    "elem_type": "A",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": 37100,
                    "as_path_dedup": [174, 37100],
                },
                {
                    "ts": "2026-08-24 02:00:00",
                    "elem_type": "A",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": 37100,
                    "as_path_dedup": [3320, 37100],
                },
                {
                    "ts": "2026-08-24 03:00:00",
                    "elem_type": "W",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": None,
                    "as_path_dedup": [],
                },
                {
                    "ts": "2026-08-24 04:00:00",
                    "elem_type": "A",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": 45090,
                    "as_path_dedup": [4809, 45090],
                },
            ],
        )
        compute_daily_summaries(settings, None, date(2026, 8, 24), date(2026, 8, 24))
        lignes = {
            r["origin_asn"]: (r["announcements"], r["withdrawals"], r["ribs"])
            for r in _lire(settings, PREFIX_ORIGIN).to_dicts()
        }
        assert lignes == {37100: (2, 0, 0), 45090: (1, 0, 0), None: (0, 1, 0)}

    def test_adjacences_dans_les_deux_sens(self, tmp_path):
        settings = _curated(
            tmp_path,
            [
                {
                    "ts": "2026-08-24 01:00:00",
                    "elem_type": "A",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": 37100,
                    "as_path_dedup": [174, 3320, 37100],
                }
            ],
        )
        compute_daily_summaries(settings, None, date(2026, 8, 24), date(2026, 8, 24))
        paires = {(r["asn"], r["neighbour"]) for r in _lire(settings, ADJACENCY).to_dicts()}
        assert paires == {(174, 3320), (3320, 174), (3320, 37100), (37100, 3320)}

    def test_seule_la_premiere_occurrence_compte(self, tmp_path):
        """Comme `list_position` du calcul direct : un AS qui revient plus loin sur le
        chemin (174 3320 36800 174 36700) n'a que les voisins de sa première position."""
        settings = _curated(
            tmp_path,
            [
                {
                    "ts": "2026-08-24 01:00:00",
                    "elem_type": "A",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": 36700,
                    "as_path_dedup": [174, 3320, 36800, 174, 36700],
                }
            ],
        )
        compute_daily_summaries(settings, None, date(2026, 8, 24), date(2026, 8, 24))
        voisins_174 = {
            r["neighbour"] for r in _lire(settings, ADJACENCY).to_dicts() if r["asn"] == 174
        }
        assert voisins_174 == {3320}  # pas 36700, voisin de la 2e occurrence

    def test_retraits_et_chemins_courts_ignores_pour_les_adjacences(self, tmp_path):
        settings = _curated(
            tmp_path,
            [
                {
                    "ts": "2026-08-24 01:00:00",
                    "elem_type": "A",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": 37100,
                    "as_path_dedup": [37100],
                },
                {
                    "ts": "2026-08-24 02:00:00",
                    "elem_type": "W",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": None,
                    "as_path_dedup": [],
                },
            ],
        )
        compute_daily_summaries(settings, None, date(2026, 8, 24), date(2026, 8, 24))
        assert _lire(settings, ADJACENCY).height == 0

    def test_recalcul_idempotent_et_par_jour(self, tmp_path):
        settings = _curated(
            tmp_path,
            [
                {
                    "ts": "2026-08-24 01:00:00",
                    "elem_type": "A",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": 37100,
                    "as_path_dedup": [174, 37100],
                }
            ],
        )
        compute_daily_summaries(settings, None, date(2026, 8, 24), date(2026, 8, 24))
        premier = _lire(settings, PREFIX_ORIGIN)
        compute_daily_summaries(settings, None, date(2026, 8, 24), date(2026, 8, 25))
        assert _lire(settings, PREFIX_ORIGIN).equals(premier)
        assert not (settings.analytics_dir / PREFIX_ORIGIN / "date=2026-08-25").exists()


class TestFraicheur:
    def _pret(self, tmp_path):
        settings = _curated(
            tmp_path,
            [
                {
                    "ts": "2026-08-24 01:00:00",
                    "elem_type": "A",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": 37100,
                    "as_path_dedup": [174, 37100],
                }
            ],
        )
        compute_daily_summaries(settings, None, date(2026, 8, 24), date(2026, 8, 24))
        return settings

    def test_a_jour_apres_calcul(self, tmp_path):
        settings = self._pret(tmp_path)
        assert summary_is_current(settings, PREFIX_ORIGIN) and summary_is_current(
            settings, ADJACENCY
        )

    def test_absente_donc_pas_utilisable(self, tmp_path):
        settings = _curated(
            tmp_path,
            [
                {
                    "ts": "2026-08-24 01:00:00",
                    "elem_type": "A",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": 37100,
                    "as_path_dedup": [174, 37100],
                }
            ],
        )
        assert not summary_is_current(settings, PREFIX_ORIGIN)

    def test_perimee_si_la_partition_curee_est_reecrite_apres(self, tmp_path):
        settings = self._pret(tmp_path)
        fichier = next(settings.curated_dir.rglob("*.parquet"))
        futur = datetime.now(UTC).timestamp() + 60
        os.utime(fichier, (futur, futur))
        assert not summary_is_current(settings, PREFIX_ORIGIN)

    def test_jour_non_couvert(self, tmp_path):
        settings = self._pret(tmp_path)
        autre = settings.curated_dir / "bgp_elements" / "date=2026-08-25" / "collector=rrc19"
        autre.mkdir(parents=True)
        _frame(
            [
                {
                    "ts": "2026-08-25 01:00:00",
                    "elem_type": "A",
                    "prefix": "10.0.0.0/22",
                    "origin_asn": 37100,
                    "as_path_dedup": [174, 37100],
                }
            ]
        ).write_parquet(autre / "part-00000.parquet")
        assert summary_is_current(settings, PREFIX_ORIGIN, ["2026-08-24"])
        assert not summary_is_current(settings, PREFIX_ORIGIN, ["2026-08-24", "2026-08-25"])
        assert not summary_is_current(settings, PREFIX_ORIGIN)  # tous les jours curés

    def test_aucun_jour_cure(self, tmp_path):
        settings = SimpleNamespace(curated_dir=tmp_path / "c", analytics_dir=tmp_path / "a")
        assert not summary_is_current(settings, PREFIX_ORIGIN)


# --- équivalence sur la démonstration ---------------------------------------
pytestmark_data = pytest.mark.skipif(
    not (get_settings().curated_dir / "bgp_elements").exists(),
    reason="jeu de démonstration absent — lancer `abrip demo bootstrap`",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def comparer(client, monkeypatch):
    """Renvoie (depuis les tables, par calcul direct) pour une même requête."""

    def _comparer(path: str, **params):
        monkeypatch.setattr(asn_explorer, "_use_summary", lambda *a, **k: True)
        monkeypatch.setattr(explore, "summary_is_current", lambda *a, **k: True)
        tables = client.get(f"/api{path}", params=params)
        monkeypatch.setattr(asn_explorer, "_use_summary", lambda *a, **k: False)
        monkeypatch.setattr(explore, "summary_is_current", lambda *a, **k: False)
        direct = client.get(f"/api{path}", params=params)
        monkeypatch.undo()
        assert tables.status_code == direct.status_code == 200, (path, params)
        return tables.json(), direct.json()

    return _comparer


PLAGES = [
    {},
    {"from": "2026-08-25", "to": "2026-08-28"},
    {"from": "2026-08-27", "to": "2026-08-27"},
    # En milieu de journée : les endpoints raisonnent en jours UTC entiers.
    {"from": "2026-08-25T13:30:00", "to": "2026-08-28T05:10:00"},
]
ASNS = [37100, 37200, 37300, 37400, 36800, 174, 3320, 45090, 4809]


@pytestmark_data
class TestEquivalenceSurLaDemo:
    @pytest.mark.parametrize("asn", ASNS)
    @pytest.mark.parametrize("plage", PLAGES)
    def test_voisins_et_serie(self, comparer, asn, plage):
        for chemin in (f"/asns/{asn}/neighbours", f"/asns/{asn}/neighbours/timeseries"):
            tables, direct = comparer(chemin, **plage)
            assert tables == direct, chemin

    @pytest.mark.parametrize("kind", ["provider", "customer", "peer", "unspecified"])
    def test_voisins_par_type(self, comparer, kind):
        tables, direct = comparer("/asns/37100/neighbours", type=kind)
        assert tables == direct

    @pytest.mark.parametrize("asn", ASNS)
    @pytest.mark.parametrize("plage", PLAGES)
    @pytest.mark.parametrize("version", ["all", "4", "6"])
    def test_serie_de_prefixes(self, comparer, asn, plage, version):
        tables, direct = comparer(f"/asns/{asn}/prefixes/timeseries", ip_version=version, **plage)
        assert tables == direct

    @pytest.mark.parametrize("asn", ASNS)
    @pytest.mark.parametrize("plage", PLAGES)
    @pytest.mark.parametrize("statut", ["all", "new", "left", "unstable"])
    def test_tableau_de_prefixes(self, comparer, asn, plage, statut):
        tables, direct = comparer(f"/asns/{asn}/prefixes", status=statut, limit=500, **plage)
        assert tables == direct

    @pytest.mark.parametrize(
        "requete",
        [
            {},
            {"q": "102."},
            {"q": "197."},
            {"origin_asn": 37100},
            {"origin_asn": 45090},
            {"limit": 5, "offset": 5},
        ],
    )
    def test_liste_des_prefixes(self, comparer, requete):
        tables, direct = comparer("/prefixes", **requete)
        assert tables == direct

    @pytest.mark.parametrize(
        "requete",
        [
            {},
            {"african_only": "false"},
            {"country": "CM"},
            {"q": "37"},
            {"limit": 4, "offset": 3, "african_only": "false"},
        ],
    )
    def test_liste_des_as(self, comparer, requete):
        tables, direct = comparer("/asns", **requete)
        assert tables["total"] > 0
        assert tables == direct

    def test_milieu_de_journee_egal_journee_entiere(self, comparer):
        """La sémantique documentée : une plage commencée à 13 h couvre le jour entier."""
        partiel, _ = comparer(
            "/asns/37100/prefixes", **{"from": "2026-08-25T13:30:00", "to": "2026-08-28T05:10:00"}
        )
        entier, _ = comparer("/asns/37100/prefixes", **{"from": "2026-08-25", "to": "2026-08-28"})
        assert partiel == entier

    def test_les_donnees_de_la_demo_sont_a_jour(self):
        settings = get_settings()
        assert summary_is_current(settings, PREFIX_ORIGIN) and summary_is_current(
            settings, ADJACENCY
        )

    def test_les_tables_ne_sont_pas_vides(self, client):
        assert client.get("/api/asns/37100/neighbours").json()["items"]
        assert client.get("/api/asns/37100/prefixes").json()["total"] > 0
