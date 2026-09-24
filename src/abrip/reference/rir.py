"""Référentiel d'attribution : qui détient quel ASN, dans quel pays.

Source d'autorité : les fichiers ``delegated-<rir>-extended-latest`` publiés par
les cinq RIR. Format documenté, texte, stable, gratuit — d'où le choix par
rapport à une base tierce.

Ligne pertinente : ``afrinic|CM|asn|36912|1|20080915|allocated|...``
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from abrip.logging_conf import get_logger
from abrip.models import REF_ASN_SCHEMA

log = get_logger(__name__)

# Codes pays ISO-3166-1 alpha-2 du continent africain (Union africaine + territoires).
AFRICAN_COUNTRIES: frozenset[str] = frozenset(
    [
        "DZ",
        "AO",
        "BJ",
        "BW",
        "BF",
        "BI",
        "CV",
        "CM",
        "CF",
        "TD",
        "KM",
        "CD",
        "CG",
        "CI",
        "DJ",
        "EG",
        "GQ",
        "ER",
        "SZ",
        "ET",
        "GA",
        "GM",
        "GH",
        "GN",
        "GW",
        "KE",
        "LS",
        "LR",
        "LY",
        "MG",
        "MW",
        "ML",
        "MR",
        "MU",
        "YT",
        "MA",
        "MZ",
        "NA",
        "NE",
        "NG",
        "RE",
        "RW",
        "SH",
        "ST",
        "SN",
        "SC",
        "SL",
        "SO",
        "ZA",
        "SS",
        "SD",
        "TZ",
        "TG",
        "TN",
        "UG",
        "EH",
        "ZM",
        "ZW",
    ]
)

CEMAC_COUNTRIES: frozenset[str] = frozenset(["CM", "CF", "CG", "GA", "GQ", "TD"])


def parse_delegated_extended(path: Path, rir: str) -> pl.DataFrame:
    """Parse un fichier delegated-extended et retourne les enregistrements ASN."""
    records: list[dict] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 7 or parts[2] != "asn":
                continue
            country, start, count, alloc_date, status = (
                parts[1],
                parts[3],
                parts[4],
                parts[5],
                parts[6],
            )
            if status not in ("allocated", "assigned"):
                continue
            try:
                first, span = int(start), int(count)
            except ValueError:
                continue
            for asn in range(first, first + span):
                records.append(
                    {
                        "asn": asn,
                        "country_iso2": country or None,
                        "rir": rir,
                        "is_african": country in AFRICAN_COUNTRIES,
                        "allocation_date": alloc_date if alloc_date.isdigit() else None,
                    }
                )
    frame = pl.DataFrame(records) if records else pl.DataFrame(schema=REF_ASN_SCHEMA)
    log.info("delegated parsé", extra={"rir": rir, "asns": frame.height})
    return frame


def build_ref_asn(
    delegated_files: dict[str, Path],
    extra_african_asns: list[int] | None = None,
    snapshot_date: date | None = None,
) -> pl.DataFrame:
    """Assemble ``ref_asn`` à partir des fichiers des cinq RIR.

    ``extra_african_asns`` couvre le cas des opérateurs africains dont l'ASN a
    été attribué par un autre RIR : ils seraient invisibles sans cette liste.
    """
    frames = [parse_delegated_extended(path, rir) for rir, path in delegated_files.items()]
    frames = [f for f in frames if f.height]
    if not frames:
        return pl.DataFrame(schema=REF_ASN_SCHEMA)

    combined = pl.concat(frames, how="vertical_relaxed").unique(subset=["asn"], keep="first")
    if extra_african_asns:
        combined = combined.with_columns(
            pl.when(pl.col("asn").is_in(extra_african_asns))
            .then(True)
            .otherwise(pl.col("is_african"))
            .alias("is_african")
        )
    stamp = (snapshot_date or date.today()).isoformat()
    return combined.with_columns(pl.lit(stamp).alias("snapshot_date")).cast(
        {"asn": pl.UInt32}, strict=False
    )


def african_asn_set(ref_asn: pl.DataFrame) -> set[int]:
    return set(ref_asn.filter(pl.col("is_african")).get_column("asn").to_list())
