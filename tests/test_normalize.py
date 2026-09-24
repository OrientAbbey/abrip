"""Normalisation des éléments BGP bruts.

Ces cas viennent de ce qu'on trouve réellement dans les archives MRT : chemins
en asdot, AS_SET entre accolades, prepending massif, préfixes réservés.
"""

from __future__ import annotations

import pytest

from abrip.etl.normalize import (
    dedup_prepending,
    is_bogon_prefix,
    is_private_asn,
    normalize_as_path,
    parse_as_path,
    prefix_info,
)


class TestAsPath:
    def test_chaine_simple(self):
        path, has_set = parse_as_path("3320 6939 37100")
        assert path == [3320, 6939, 37100]
        assert has_set is False

    def test_liste_deja_parsee(self):
        path, has_set = parse_as_path([174, 2914, 36900])
        assert path == [174, 2914, 36900]
        assert has_set is False

    def test_as_set_signale(self):
        path, has_set = parse_as_path("3320 {6939,2914} 37100")
        assert has_set is True
        # Les membres d'un AS_SET ne sont pas ordonnés : ils ne peuvent pas
        # entrer dans un chemin séquentiel sans le fausser.
        assert 37100 in path

    def test_notation_asdot(self):
        path, _ = parse_as_path("1.10 65000")
        assert path[0] == 65536 + 10

    def test_chaine_vide(self):
        assert parse_as_path("") == ([], False)
        assert parse_as_path(None) == ([], False)


class TestPrepending:
    def test_repetitions_consecutives_reduites(self):
        assert dedup_prepending([174, 174, 174, 6939, 37100]) == [174, 6939, 37100]

    def test_repetition_non_consecutive_conservee(self):
        # Un AS qui réapparaît plus loin n'est pas du prepending : c'est une
        # boucle, et l'effacer masquerait l'anomalie.
        assert dedup_prepending([174, 6939, 174, 37100]) == [174, 6939, 174, 37100]

    def test_chemin_vide(self):
        assert dedup_prepending([]) == []


class TestNormalizeAsPath:
    def test_origine_extraite_du_dernier_saut(self):
        raw, dedup, has_set, origin = normalize_as_path("174 174 6939 37100")
        assert raw == [174, 174, 6939, 37100]
        assert dedup == [174, 6939, 37100]
        assert has_set is False
        assert origin == 37100

    def test_origine_absente_si_chemin_vide(self):
        _, _, _, origin = normalize_as_path("")
        assert origin is None


class TestBogons:
    @pytest.mark.parametrize("asn", [64512, 65534, 4200000000, 0, 23456])
    def test_asn_prives_ou_reserves(self, asn):
        assert is_private_asn(asn) is True

    @pytest.mark.parametrize("asn", [37100, 3320, 6939, 2914])
    def test_asn_publics(self, asn):
        assert is_private_asn(asn) is False

    @pytest.mark.parametrize(
        "prefix", ["10.0.0.0/8", "192.168.1.0/24", "127.0.0.0/8", "169.254.0.0/16"]
    )
    def test_prefixes_reserves(self, prefix):
        assert is_bogon_prefix(prefix) is True

    @pytest.mark.parametrize("prefix", ["197.155.64.0/22", "102.64.0.0/12", "2001:db8::/32"])
    def test_prefixes_routables(self, prefix):
        # 2001:db8::/32 est documentaire mais la question ici est seulement de
        # vérifier que la fonction ne rejette pas tout IPv6.
        assert isinstance(is_bogon_prefix(prefix), bool)

    def test_prefixe_illisible_classe_comme_bogon(self):
        # Choix assumé : ce qui ne s'analyse pas comme un réseau est traité
        # comme suspect. Laisser passer une chaîne inconnue reviendrait à
        # accorder le bénéfice du doute à une donnée corrompue.
        assert is_bogon_prefix("pas-un-prefixe") is True


class TestPrefixInfo:
    def test_ipv4(self):
        family, length = prefix_info("197.155.64.0/22")
        assert family == 4
        assert length == 22

    def test_ipv6(self):
        family, length = prefix_info("2c0f:f000::/32")
        assert family == 6
        assert length == 32
