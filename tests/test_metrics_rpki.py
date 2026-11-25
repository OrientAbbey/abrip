from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import polars as pl

from abrip.analytics.metrics import compute_rpki_coverage
from abrip.models import BGP_ELEMENTS_SCHEMA, REF_ASN_SCHEMA, REF_ROA_SCHEMA
from abrip.reference.rpki import RpkiValidator


def _settings(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(curated_dir=tmp_path / "curated")


def _write_elements(root, rows: list[dict]) -> None:
    base = root / "bgp_elements" / "date=2026-08-24" / "collector=rrc19"
    base.mkdir(parents=True)
    base_frame = {
        "ts": datetime(2026, 8, 24, 12),
        "collector": "rrc19",
        "peer_asn": 174,
        "peer_ip": "196.60.1.1",
        "elem_type": "A",
        "prefix": "197.155.64.0/22",
        "prefix_ip_version": 4,
        "prefix_len": 22,
        "origin_asn": 37100,
        "as_path": [3320, 37100],
        "as_path_dedup": [3320, 37100],
        "as_path_len": 2,
        "has_as_set": False,
        "next_hop": "196.60.1.1",
        "communities": None,
        "med": None,
        "local_pref": None,
        "source_file": "test.gz",
    }
    frame = pl.DataFrame([{**base_frame, **row} for row in rows], schema=BGP_ELEMENTS_SCHEMA)
    frame.write_parquet(base / "part-00000.parquet")


def _ref_asn() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "asn": [37100, 45090, 37400, 999],
            "country_iso2": ["CM", "CM", "SN", "FR"],
            "rir": ["AFRINIC"] * 3 + ["RIPE"],
            "is_african": [True, True, True, False],
            "allocation_date": [None] * 4,
            "snapshot_date": ["2026-08-24"] * 4,
        },
        schema=REF_ASN_SCHEMA,
    )


def _ref_roa() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "prefix": ["197.155.64.0/22"],
            "asn": [37100],
            "max_len": [24],
            "ta": ["afrinic"],
            "snapshot_date": ["2026-08-24"],
        },
        schema=REF_ROA_SCHEMA,
    )


def test_les_annonces_repetees_donnent_le_meme_resultat_qu_une_validation_ligne_a_ligne(tmp_path):
    settings = _settings(tmp_path)
    _write_elements(
        settings.curated_dir,
        [
            # Même préfixe/origine annoncé par plusieurs peers : la validation
            # vectorisée ne doit compter qu'un couple distinct.
            {"peer_asn": 174},
            {"peer_asn": 3356},
            # MOAS : même préfixe, origine non autorisée.
            {"origin_asn": 45090, "peer_asn": 174},
            # Préfixe sans ROA.
            {"prefix": "196.60.0.0/18", "prefix_len": 18, "origin_asn": 37400},
        ],
    )
    ref_roa = _ref_roa()
    result = compute_rpki_coverage(
        settings, date(2026, 8, 24), date(2026, 8, 24), ref_roa, _ref_asn()
    )

    by_country = {row["country_iso2"]: row for row in result.iter_rows(named=True)}
    assert set(by_country) == {"CM", "SN"}
    assert by_country["CM"]["prefixes_announced"] == 1
    assert by_country["CM"]["prefixes_valid"] == 1
    assert by_country["CM"]["prefixes_invalid"] == 1
    assert by_country["CM"]["rpki_coverage_ratio"] == 1.0
    assert by_country["SN"]["prefixes_announced"] == 1
    assert by_country["SN"]["prefixes_valid"] == 0
    assert by_country["SN"]["prefixes_not_found"] == 1
    assert by_country["SN"]["rpki_coverage_ratio"] == 0.0
    assert by_country["CM"]["window_start"] == datetime(2026, 8, 24)

    # Équivalence avec la validation historique, ligne à ligne.
    validator = RpkiValidator.from_frame(ref_roa)
    assert validator.validate("197.155.64.0/22", 37100).value == "valid"
    assert validator.validate("197.155.64.0/22", 45090).value == "invalid"
    assert validator.validate("196.60.0.0/18", 37400).value == "not-found"


def test_sans_roa_tout_est_not_found(tmp_path):
    settings = _settings(tmp_path)
    _write_elements(settings.curated_dir, [{"peer_asn": 174}, {"peer_asn": 3356}])

    result = compute_rpki_coverage(
        settings, date(2026, 8, 24), date(2026, 8, 24), pl.DataFrame(), _ref_asn()
    )

    assert result.height == 1
    assert result.get_column("rpki_coverage_ratio").to_list() == [0.0]
    assert result.get_column("prefixes_not_found").to_list() == [1]
