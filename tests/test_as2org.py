"""AS2Org : donnée réelle consommée par le filtre « même organisation » (L6)."""

from __future__ import annotations

import gzip

import pytest

from abrip.reference.as2org import parse_as2org, sibling_asns

SAMPLE = """# format:aut|changed|aut_name|org_id|opaque_id|source
37100|20120224|LITTORAL-TELECOM|LITTORAL-AFRINIC|abc|AFRINIC
37105|20120224|LITTORAL-TELECOM-2|LITTORAL-AFRINIC|abc|AFRINIC
174|20120224|COGENT-174|COGENT-ARIN|xyz|ARIN
# format:org_id|changed|org_name|country|source
LITTORAL-AFRINIC|20120224|Littoral Telecom SA|CM|AFRINIC
COGENT-ARIN|20120224|Cogent Communications|US|ARIN
"""


@pytest.fixture
def as2org_file(tmp_path):
    path = tmp_path / "20260101.as-org2info.txt.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(SAMPLE)
    return path


class TestParseAs2Org:
    def test_associe_asn_et_organisation(self, as2org_file):
        frame = parse_as2org(as2org_file)
        assert frame.height == 3
        row = frame.filter(frame["asn"] == 37100).row(0, named=True)
        assert row["org_id"] == "LITTORAL-AFRINIC"
        assert row["org_name"] == "Littoral Telecom SA"

    def test_organisation_sans_nom_reste_nulle(self, tmp_path):
        path = tmp_path / "partiel.txt.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(
                "# format:aut|changed|aut_name|org_id|opaque_id|source\n64500|1|X|ORG-X|a|TEST\n"
            )
        frame = parse_as2org(path)
        assert frame.height == 1
        assert frame.row(0, named=True)["org_name"] is None

    def test_fichier_vide_renvoie_un_cadre_vide(self, tmp_path):
        path = tmp_path / "vide.txt.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write("# rien ici\n")
        frame = parse_as2org(path)
        assert frame.is_empty()


class TestSiblingAsns:
    def test_asn_partageant_une_organisation(self, as2org_file):
        frame = parse_as2org(as2org_file)
        assert sibling_asns(frame, 37100) == {37105}
        assert sibling_asns(frame, 37105) == {37100}

    def test_asn_isole(self, as2org_file):
        frame = parse_as2org(as2org_file)
        assert sibling_asns(frame, 174) == set()

    def test_asn_absent_du_referentiel(self, as2org_file):
        frame = parse_as2org(as2org_file)
        assert sibling_asns(frame, 999999) == set()
