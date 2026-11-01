"""Tri des partitions bgp_elements par (prefix, ts) et compactage des anciennes.

Le tri existe pour la performance (les requêtes par préfixe sautent les groupes
de lignes hors plage, voir docs/performances.md) et ne doit rien changer d'autre :
mêmes lignes, mêmes événements, mêmes incidents. Un premier essai a justement
cassé la détection de chute de visibilité sans bruit : `collector` passait en
texte côté mises à jour et restait `Categorical` côté RIB, et la jointure du
détecteur ne trouvait plus aucune ligne. D'où le test de cohérence des types.
"""

from __future__ import annotations

import duckdb
import polars as pl
import pytest
from typer.testing import CliRunner

from abrip.cli import app
from abrip.config import reload_settings
from abrip.demo.bootstrap import bootstrap, verify
from abrip.etl.curate import compact_bgp_elements
from abrip.models import BGP_ELEMENTS_SCHEMA, RIB_SNAPSHOT_SCHEMA
from abrip.storage.parquet import sort_partition


def _frame(rows: int, *, collector_dtype=pl.String, seed: int = 0) -> pl.DataFrame:
    """Lignes dans le désordre : préfixes et instants mélangés, comme à l'arrivée."""
    import random

    rng = random.Random(seed)
    prefixes = [f"10.{i}.0.0/16" for i in range(40)]
    data = [
        {
            "ts": f"2026-08-24 {rng.randrange(24):02d}:{rng.randrange(60):02d}:{rng.randrange(60):02d}",
            "collector": "rrc19",
            "peer_asn": rng.choice([174, 3320, 6939]),
            "prefix": rng.choice(prefixes),
            "as_path": [174, 37100],
        }
        for _ in range(rows)
    ]
    return pl.DataFrame(data).with_columns(
        pl.col("ts").str.to_datetime(),
        pl.col("collector").cast(collector_dtype),
        pl.col("peer_asn").cast(pl.UInt32),
        pl.col("as_path").cast(pl.List(pl.UInt32)),
    )


def _fragments(directory, frame: pl.DataFrame, parts: int = 3) -> None:
    directory.mkdir(parents=True)
    size = -(-frame.height // parts)
    for i in range(parts):
        frame.slice(i * size, size).write_parquet(directory / f"part-{i:05d}.parquet")


class TestSortPartition:
    def test_fragments_fondus_en_un_fichier_trie(self, tmp_path):
        source = _frame(5000)
        _fragments(tmp_path / "p", source)
        rows = sort_partition(tmp_path / "p", row_group_size=500)

        assert rows == 5000
        assert [f.name for f in (tmp_path / "p").iterdir()] == ["part-00000.parquet"]
        sorted_frame = pl.read_parquet(tmp_path / "p" / "part-00000.parquet")
        ordre = sorted_frame.select(["prefix", "ts"])
        assert ordre.equals(ordre.sort(["prefix", "ts"]))

    def test_memes_lignes_qu_avant(self, tmp_path):
        source = _frame(3000)
        _fragments(tmp_path / "p", source)
        sort_partition(tmp_path / "p")
        apres = pl.read_parquet(tmp_path / "p" / "part-00000.parquet")
        colonnes = source.columns
        assert apres.select(colonnes).sort(colonnes).equals(source.sort(colonnes))

    def test_types_conserves(self, tmp_path):
        source = _frame(500)
        _fragments(tmp_path / "p", source)
        sort_partition(tmp_path / "p")
        schema = pl.read_parquet_schema(tmp_path / "p" / "part-00000.parquet")
        assert schema["peer_asn"] == pl.UInt32 and schema["as_path"] == pl.List(pl.UInt32)
        assert schema["ts"] == pl.Datetime("us") and schema["collector"] == pl.String

    def test_idempotent(self, tmp_path):
        _fragments(tmp_path / "p", _frame(800))
        sort_partition(tmp_path / "p")
        premier = pl.read_parquet(tmp_path / "p" / "part-00000.parquet")
        assert sort_partition(tmp_path / "p") == 800
        assert pl.read_parquet(tmp_path / "p" / "part-00000.parquet").equals(premier)

    def test_groupes_de_lignes_disjoints_pour_le_prefixe(self, tmp_path):
        """C'est le but du tri : les statistiques min/max permettent d'écarter des groupes."""
        _fragments(tmp_path / "p", _frame(20_000))
        sort_partition(tmp_path / "p", row_group_size=2000)
        meta = duckdb.sql(
            f"""SELECT row_group_id, min(stats_min) AS lo, min(stats_max) AS hi
                FROM parquet_metadata('{(tmp_path / "p" / "part-00000.parquet").as_posix()}')
                WHERE path_in_schema = 'prefix' GROUP BY 1 ORDER BY 1"""
        ).fetchall()
        assert len(meta) == 10
        # Un préfixe donné n'est présent que dans peu de groupes (ici 40 préfixes sur 10).
        cible = "10.7.0.0/16"
        touches = [g for g in meta if g[1] <= cible <= g[2]]
        assert 1 <= len(touches) <= 3

    def test_repertoire_vide(self, tmp_path):
        (tmp_path / "vide").mkdir()
        assert sort_partition(tmp_path / "vide") == 0

    def test_pas_de_residu_apres_tri(self, tmp_path):
        _fragments(tmp_path / "p", _frame(300))
        sort_partition(tmp_path / "p")
        assert not [p for p in (tmp_path / "p").iterdir() if p.name.startswith(".")]


class TestCompactage:
    def test_anciennes_partitions_categorical_uniformisees(self, monkeypatch, tmp_path):
        """Une installation antérieure au tri a `collector` en Categorical : polars
        refuserait de lire ensemble ces fichiers et les nouveaux (en texte)."""
        monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / "data"))
        settings = reload_settings()
        racine = settings.curated_dir / "bgp_elements"
        _fragments(
            racine / "date=2026-08-24" / "collector=rrc19",
            _frame(1000, collector_dtype=pl.Categorical),
            parts=2,
        )
        recent = racine / "date=2026-08-25" / "collector=rrc19"
        _fragments(recent, _frame(1000, seed=1), parts=1)
        fichiers = sorted(racine.glob("**/*.parquet"))
        with pytest.raises(pl.exceptions.SchemaError):
            pl.read_parquet(fichiers)

        bilan = compact_bgp_elements(settings)

        assert bilan == {"partitions": 2, "rows": 2000}
        lu = pl.read_parquet(sorted(racine.glob("**/*.parquet")))
        assert lu.height == 2000 and lu.schema["collector"] == pl.String
        monkeypatch.undo()
        reload_settings()

    def test_commande_etl_compact(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / "data"))
        settings = reload_settings()
        _fragments(
            settings.curated_dir / "bgp_elements" / "date=2026-08-24" / "collector=rrc19",
            _frame(400),
        )
        resultat = CliRunner().invoke(app, ["etl", "compact"])
        assert resultat.exit_code == 0, resultat.output
        assert '"partitions": 1' in resultat.output and '"rows": 400' in resultat.output
        monkeypatch.undo()
        reload_settings()


class TestCoherenceDesTypes:
    def test_collector_meme_type_dans_toutes_les_tables_curees(self):
        """Les détecteurs joignent la RIB aux mises à jour sur `collector` : deux types
        différents donnent une jointure vide, sans erreur (chute de visibilité muette)."""
        assert BGP_ELEMENTS_SCHEMA["collector"] == RIB_SNAPSHOT_SCHEMA["collector"] == pl.String


@pytest.fixture
def donnees(monkeypatch, tmp_path):
    def _faire(sous_dossier: str, tri: bool):
        monkeypatch.setenv("ABRIP_DATA_DIR", str(tmp_path / sous_dossier))
        monkeypatch.setenv("ABRIP_ETL__SORT_PARTITIONS", "true" if tri else "false")
        return reload_settings()

    yield _faire
    monkeypatch.undo()
    reload_settings()


def _bilan(settings):
    lire = lambda nom: pl.read_parquet(sorted((settings.analytics_dir / nom).glob("**/*.parquet")))  # noqa: E731
    return {
        "evenements": sorted(lire("events")["event_id"].to_list()),
        "incidents": lire("incidents").height,
        "verify": verify(settings),
    }


class TestLeTriNeChangeAucunResultat:
    def test_demo_identique_triee_ou_non(self, donnees):
        sans = donnees("sans-tri", tri=False)
        bootstrap(sans)
        reference = _bilan(sans)

        avec = donnees("avec-tri", tri=True)
        bootstrap(avec)
        triee = _bilan(avec)

        # Invariants de la démonstration (README) : 16 événements, 8 incidents, rappel 1.0.
        assert len(triee["evenements"]) == 16 and triee["incidents"] == 8
        assert triee["verify"]["recall"] == 1.0 and len(triee["verify"]["matched"]) == 5
        # Et exactement les mêmes événements : le tri ne déplace aucun verdict.
        assert triee["evenements"] == reference["evenements"]
        assert triee["incidents"] == reference["incidents"]

        # Les partitions sont bien triées et d'un seul fichier.
        for repertoire in (avec.curated_dir / "bgp_elements").glob("date=*/collector=*"):
            fichiers = list(repertoire.glob("*.parquet"))
            assert len(fichiers) == 1
            ordre = pl.read_parquet(fichiers[0]).select(["prefix", "ts"])
            assert ordre.equals(ordre.sort(["prefix", "ts"]))
