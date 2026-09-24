"""Parseur des relevés PCH (``sh ip bgp``), format texte à largeur fixe (L2)."""

from __future__ import annotations

import gzip

import pytest

from abrip.etl.pch_parser import PchTextDumpParser


def _fixed_width_row(
    status: str, network: str, next_hop: str, metric: str, locprf: str, weight: str, path: str
) -> str:
    return f"{status:<3}{network:<18}{next_hop:<20}{metric:>7}{locprf:>7}{weight:>7} {path}\n"


def _header() -> str:
    return f"{'':3}{'Network':<18}{'Next Hop':<20}{'Metric':>7}{'LocPrf':>7}{'Weight':>7} Path\n"


@pytest.fixture
def sample_file(tmp_path):
    lines = [
        "BGP table version is 0, local router ID is 204.61.1.100\n",
        "Status codes: s suppressed, d damped, h history, * valid, > best, i - internal\n",
        "Origin codes: i - IGP, e - EGP, ? - incomplete\n",
        "\n",
        _header(),
        _fixed_width_row("*>", "196.60.0.0/18", "196.60.1.1", "0", "", "0", "3320 37400 i"),
        # LocPrf vide : le cas piégeux que le comptage de jetons confondrait.
        _fixed_width_row("*>", "197.155.64.0/22", "196.60.1.5", "", "", "0", "6939 37100 i"),
        # Ligne de continuation (préfixe omis, deuxième chemin de la même route).
        _fixed_width_row("*", "", "196.60.1.9", "", "", "", "174 45090 i"),
        _fixed_width_row("*>", "102.64.0.0/12", "196.60.1.20", "", "", "", "174 36700 i"),
    ]
    path = tmp_path / "route-collector.jnb1.pch.net-ipv4_bgp_routes.2026.08.24.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("".join(lines))
    return path


class TestPchTextDumpParser:
    def test_toujours_disponible(self):
        assert PchTextDumpParser().available() is True

    def test_lit_toutes_les_routes(self, sample_file):
        records = list(PchTextDumpParser().parse(sample_file, "route-collector.jnb1.pch.net"))
        assert len(records) == 4

    def test_chemin_correct_malgre_locprf_vide(self, sample_file):
        records = {
            r["prefix"]: r
            for r in PchTextDumpParser().parse(sample_file, "c")
            if r["prefix"] != "197.155.64.0/22"
        }
        assert records["196.60.0.0/18"]["as_path_dedup"] == [3320, 37400]
        assert records["196.60.0.0/18"]["origin_asn"] == 37400
        assert records["102.64.0.0/12"]["as_path_dedup"] == [174, 36700]

    def test_ligne_de_continuation_reutilise_le_prefixe_precedent(self, sample_file):
        records = [
            r
            for r in PchTextDumpParser().parse(sample_file, "c")
            if r["prefix"] == "197.155.64.0/22"
        ]
        assert len(records) == 2
        origins = {r["origin_asn"] for r in records}
        assert origins == {37100, 45090}

    def test_tous_les_enregistrements_sont_des_rib(self, sample_file):
        records = list(PchTextDumpParser().parse(sample_file, "c"))
        assert all(r["elem_type"] == "R" for r in records)

    def test_horodatage_extrait_du_nom_de_fichier(self, sample_file):
        records = list(PchTextDumpParser().parse(sample_file, "c"))
        assert all(r["ts"].isoformat().startswith("2026-08-24") for r in records)

    def test_peer_asn_est_le_premier_saut_du_chemin(self, sample_file):
        records = {
            r["prefix"]: r
            for r in PchTextDumpParser().parse(sample_file, "c")
            if r["prefix"] == "102.64.0.0/12"
        }
        assert records["102.64.0.0/12"]["peer_asn"] == 174

    def test_fichier_sans_en_tete_ne_leve_pas(self, tmp_path):
        path = tmp_path / "sans-entete.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write("contenu inattendu, pas de table BGP\n")
        assert list(PchTextDumpParser().parse(path, "c")) == []

    def test_next_hop_correctement_isole(self, sample_file):
        records = {
            r["prefix"]: r
            for r in PchTextDumpParser().parse(sample_file, "c")
            if r["prefix"] == "196.60.0.0/18"
        }
        assert records["196.60.0.0/18"]["next_hop"] == "196.60.1.1"
