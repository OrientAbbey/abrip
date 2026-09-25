"""Référentiels : validation RPKI et relations inter-AS.

Ce sont les deux briques qui transforment une heuristique en preuve. Elles
méritent donc des tests sur les cas limites, pas seulement sur le cas nominal.
"""

from __future__ import annotations

import polars as pl
import pytest

from abrip.models import Relationship, RpkiStatus
from abrip.reference.history import diff_entities
from abrip.reference.relationships import (
    RelationshipIndex,
    classify_path,
    valley_free_violation,
)
from abrip.reference.rpki import RpkiValidator, parse_roa_payload
from abrip.storage.parquet import write_frame


@pytest.fixture
def validator() -> RpkiValidator:
    payload = {
        "roas": [
            {"prefix": "197.155.64.0/22", "maxLength": 24, "asn": "AS37100", "ta": "afrinic"},
            {"prefix": "102.64.0.0/12", "maxLength": 12, "asn": "AS36800", "ta": "afrinic"},
        ]
    }
    return RpkiValidator(parse_roa_payload(payload))


class TestRpki:
    def test_annonce_conforme(self, validator):
        assert validator.validate("197.155.64.0/22", 37100) is RpkiStatus.VALID

    def test_origine_non_autorisee(self, validator):
        assert validator.validate("197.155.64.0/22", 45090) is RpkiStatus.INVALID

    def test_sous_prefixe_dans_la_longueur_max(self, validator):
        assert validator.validate("197.155.64.0/24", 37100) is RpkiStatus.VALID

    def test_sous_prefixe_trop_specifique(self, validator):
        # /25 dépasse le maxLength de 24 : invalide même avec la bonne origine.
        assert validator.validate("197.155.64.0/25", 37100) is RpkiStatus.INVALID

    def test_prefixe_sans_roa(self, validator):
        # Cas majoritaire dans la zone AFRINIC : ni preuve à charge ni à décharge.
        assert validator.validate("196.60.0.0/18", 37400) is RpkiStatus.NOT_FOUND

    def test_origine_absente(self, validator):
        assert validator.validate("197.155.64.0/22", None) is RpkiStatus.NOT_FOUND

    def test_asn_sous_forme_entiere(self):
        entries = parse_roa_payload(
            {"roas": [{"prefix": "10.0.0.0/8", "maxLength": 8, "asn": 64512}]}
        )
        assert entries[0].asn == 64512

    def test_validation_par_trame(self, validator):
        frame = pl.DataFrame(
            {
                "prefix": ["197.155.64.0/22", "197.155.64.0/22", "196.60.0.0/18"],
                "origin_asn": [37100, 45090, 37400],
            }
        )
        out = validator.validate_frame(frame)
        statuses = out["rpki_status"].to_list()
        assert statuses == ["valid", "invalid", "not-found"]


@pytest.fixture
def index() -> RelationshipIndex:
    # 174 et 3320 sont fournisseurs de 36800 et 36700 ; 174 et 3320 sont pairs.
    frame = pl.DataFrame(
        {
            # Convention CAIDA serial-2 : as_a est fournisseur de as_b pour p2c.
            "as_a": [174, 3320, 174, 3320, 174],
            "as_b": [36800, 36800, 36700, 36700, 3320],
            "relationship": ["p2c", "p2c", "p2c", "p2c", "p2p"],
        }
    )
    return RelationshipIndex(frame)


class TestValleyFree:
    def test_chemin_conforme(self, index):
        # Montée vers un fournisseur puis descente : structure attendue.
        assert valley_free_violation([174, 36800], index) is None

    def test_fuite_de_routes(self, index):
        # 36800 est client de 3320 et de 174 ; réannoncer 174 vers ses pairs
        # revient à offrir du transit gratuit : c'est une fuite.
        path = [3320, 36800, 174, 36700]
        position = valley_free_violation(path, index)
        # La fonction retourne l'indice du lien fautif ; l'AS fuiteur est celui
        # qui ouvre ce lien.
        assert position is not None
        assert path[position] == 36800

    def test_chemin_trop_court(self, index):
        assert valley_free_violation([37100], index) is None

    def test_relations_inconnues_ne_declenchent_rien(self, index):
        # Sans relation connue, on ne conclut pas : l'absence de donnée n'est
        # pas une preuve de violation.
        assert valley_free_violation([64500, 64501, 64502], index) is None

    def test_classification_de_chemin(self, index):
        relations = classify_path([174, 36800], index)
        assert relations == [Relationship.P2C]

    def test_fournisseurs_connus(self, index):
        assert index.providers_of(36800) == {174, 3320}


class TestHistory:
    """Diff de référentiel historisé — voir reference/history.py."""

    def _write_day(self, reference_dir, table, day, rows):
        schema = {"prefix": pl.Utf8, "asn": pl.UInt32, "snapshot_date": pl.Utf8}
        frame = pl.DataFrame(
            [{**r, "snapshot_date": day} for r in rows], schema=schema, strict=False
        )
        write_frame(frame, reference_dir / "history" / table / f"date={day}")

    def test_classement_new_left_unstable_stable(self, tmp_path):
        days = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
        stable = {"prefix": "STABLE/24", "asn": 9}
        new = {"prefix": "NEW/24", "asn": 2}
        left = {"prefix": "LEFT/24", "asn": 3}
        unstable = {"prefix": "UNSTABLE/24", "asn": 1}

        # stable : les 4 jours. new : jours 3-4 seulement. left : jours 1-2
        # seulement. unstable : présente, absente, présente, présente (un
        # aller-retour au jour 2->3).
        rows_by_day = {
            days[0]: [stable, left, unstable],
            days[1]: [stable, left],
            days[2]: [stable, new],
            days[3]: [stable, new, unstable],
        }
        for day in days:
            self._write_day(tmp_path, "ref_roa", day, rows_by_day[day])

        result = {
            (r["prefix"], r["asn"]): r["change"]
            for r in diff_entities(tmp_path, "ref_roa", ["prefix", "asn"], days[0], days[-1])
        }
        assert result[("STABLE/24", 9)] == "stable"
        assert result[("NEW/24", 2)] == "new"
        assert result[("LEFT/24", 3)] == "left"
        assert result[("UNSTABLE/24", 1)] == "unstable"

    def test_fenetre_sans_historique_renvoie_vide(self, tmp_path):
        assert (
            diff_entities(tmp_path, "ref_roa", ["prefix", "asn"], "2026-01-01", "2026-01-04") == []
        )
