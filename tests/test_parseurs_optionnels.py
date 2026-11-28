"""Test des parseurs optionnels sur un vrai fichier MRT.

Le fichier est fourni par le workflow `parsers.yml` via `ABRIP_TEST_MRT_PATH`.
Sans ce fichier, le test est ignoré : la CI habituelle ne dépend pas du réseau.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from abrip.etl.mrt_parser import BgpkitParser, MrtparseParser


@pytest.fixture(scope="module")
def mrt_path() -> Path:
    value = os.environ.get("ABRIP_TEST_MRT_PATH")
    if not value or not Path(value).is_file():
        pytest.skip("ABRIP_TEST_MRT_PATH absent : test réservé au workflow parseurs")
    return Path(value)


@pytest.mark.parametrize("classe", [BgpkitParser, MrtparseParser])
def test_parseur_reel(mrt_path: Path, classe):
    parseur = classe()
    if not parseur.available():
        pytest.skip(f"{parseur.name} n'est pas installé")
    enregistrements = list(parseur.parse(mrt_path, "rrc19"))
    assert enregistrements, f"{parseur.name} n'a produit aucune ligne normalisée"
    for record in enregistrements[:50]:
        assert record["prefix"]
        assert record["collector"] == "rrc19"
        assert record["elem_type"] in {"A", "W", "R"}
