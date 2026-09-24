"""Filtre anycast : catalogue public + divergence de chemin (L6, filtre 3)."""

from __future__ import annotations

import httpx

from abrip.reference.anycast import (
    fetch_anycast_reference,
    is_anycast_candidate,
    is_known_anycast,
    parse_anycatch_csv,
)

SAMPLE_CSV = "1.1.1.0/24,1.1.1.1\n8.8.8.0/24,8.8.8.8\nligne-invalide-ignoree\n"


class TestParseAnycatchCsv:
    def test_extrait_les_prefixes(self):
        assert parse_anycatch_csv(SAMPLE_CSV) == {"1.1.1.0/24", "8.8.8.0/24"}

    def test_ignore_les_lignes_invalides(self):
        assert "ligne-invalide-ignoree" not in parse_anycatch_csv(SAMPLE_CSV)

    def test_texte_vide(self):
        assert parse_anycatch_csv("") == set()


class TestIsKnownAnycast:
    def test_prefixe_exact(self):
        assert is_known_anycast("1.1.1.0/24", frozenset({"1.1.1.0/24"})) is True

    def test_sous_prefixe_couvert(self):
        assert is_known_anycast("1.1.1.0/25", frozenset({"1.1.1.0/24"})) is True

    def test_prefixe_inconnu(self):
        assert is_known_anycast("9.9.9.0/24", frozenset({"1.1.1.0/24"})) is False

    def test_catalogue_vide(self):
        assert is_known_anycast("1.1.1.0/24", frozenset()) is False


class TestIsAnycastCandidate:
    ANYCAST = frozenset({"1.1.1.0/24"})

    def test_connu_et_chemins_divergents_est_filtre(self):
        assert (
            is_anycast_candidate("1.1.1.0/24", [[3320, 64500]], [[6939, 64600]], self.ANYCAST)
            is True
        )

    def test_connu_mais_chemins_quasi_identiques_nest_pas_filtre(self):
        # Deux origines au chemin presque identique ressemblent moins à de
        # l'anycast qu'à un artefact ou un cas à examiner : on ne les
        # supprime pas sur la seule foi du catalogue.
        assert (
            is_anycast_candidate(
                "1.1.1.0/24", [[3320, 6939, 64500]], [[3320, 6939, 64600]], self.ANYCAST
            )
            is False
        )

    def test_prefixe_absent_du_catalogue_nest_jamais_filtre(self):
        assert (
            is_anycast_candidate("9.9.9.0/24", [[3320, 64500]], [[6939, 64600]], self.ANYCAST)
            is False
        )

    def test_sans_chemins_disponibles_reste_prudent(self):
        assert is_anycast_candidate("1.1.1.0/24", None, None, self.ANYCAST) is False
        assert is_anycast_candidate("1.1.1.0/24", [], [], self.ANYCAST) is False

    def test_plusieurs_chemins_par_origine_retient_le_meilleur_recouvrement(self):
        # Si au moins une paire de chemins se recoupe fortement, on ne filtre pas.
        assert (
            is_anycast_candidate(
                "1.1.1.0/24",
                [[3320, 64500], [3320, 6939, 64500]],
                [[3320, 6939, 64600]],
                self.ANYCAST,
            )
            is False
        )


class TestFetchAnycastReference:
    def test_agrege_v4_et_v6(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "v4" in str(request.url):
                return httpx.Response(200, text="1.1.1.0/24,1.1.1.1\n")
            return httpx.Response(200, text="2606:4700::/32,2606:4700::1\n")

        prefixes = fetch_anycast_reference(transport=httpx.MockTransport(handler))
        assert prefixes == {"1.1.1.0/24", "2606:4700::/32"}

    def test_service_indisponible_renvoie_un_ensemble_vide(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        assert fetch_anycast_reference(transport=httpx.MockTransport(handler)) == set()
