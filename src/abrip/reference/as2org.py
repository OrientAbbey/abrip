"""CAIDA AS2Org : associe chaque AS à son organisation déclarante.

C'est la donnée qui manquait pour que le filtre « même organisation » du
détecteur MOAS (``ignore_same_organisation``, déjà présent dans le code) fasse
autre chose que consulter un dictionnaire vide. Sans ce module, deux AS
appartenant à la même entité étaient traités comme des origines concurrentes
indépendantes — un faux positif systématique pour tout opérateur multi-AS.

Format CAIDA (fichier ``YYYYMMDD.as-org2info.txt.gz``, deux tables
concaténées, séparées par des lignes de commentaire) :

    # format:aut|changed|aut_name|org_id|opaque_id|source
    174|20120224|COGENT-174|COGENT-ARIN|...|ARIN
    # format:org_id|changed|org_name|country|source
    COGENT-ARIN|20120224|Cogent Communications|US|ARIN

La première table (``aut|...``) associe un ASN à un ``org_id`` ; la seconde
(``org_id|...``) donne le nom lisible de l'organisation. On n'a besoin que de
la première pour le filtre MOAS, mais la seconde rend les preuves affichées à
l'écran compréhensibles (« Orange Cameroun S.A. » plutôt que « ORG-OC3-AFRINIC »).
"""

from __future__ import annotations

import gzip
from datetime import date
from pathlib import Path

import polars as pl

from abrip.logging_conf import get_logger
from abrip.models import REF_AS_ORG_SCHEMA

log = get_logger(__name__)


def _opener(path: Path):
    return gzip.open if path.suffix == ".gz" else open


def parse_as2org(path: Path, snapshot_date: date | None = None) -> pl.DataFrame:
    """Parse un fichier AS2Org CAIDA en table ``ref_as_org`` (asn, org_id, org_name).

    Le fichier mélange deux tables distinguées par leur ligne d'en-tête
    ``# format:...`` : on bascule de l'une à l'autre en la reconnaissant, sans
    dépendre d'un nombre de colonnes fixe qui casserait sur un futur format.
    """
    stamp = (snapshot_date or date.today()).isoformat()
    org_names: dict[str, str] = {}
    asn_org: list[tuple[int, str]] = []
    mode = "aut"

    with _opener(path)(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("# format:aut"):
                mode = "aut"
                continue
            if line.startswith("# format:org_id"):
                mode = "org"
                continue
            if line.startswith("#"):
                continue

            parts = line.split("|")
            if mode == "aut" and len(parts) >= 4:
                try:
                    asn = int(parts[0])
                except ValueError:
                    continue
                org_id = parts[3] or parts[2]
                asn_org.append((asn, org_id))
            elif mode == "org" and len(parts) >= 3:
                org_id, _changed, org_name = parts[0], parts[1], parts[2]
                org_names[org_id] = org_name

    if not asn_org:
        log.warning(
            "aucun couple ASN/organisation extrait du fichier AS2Org", extra={"path": str(path)}
        )
        return pl.DataFrame(schema=REF_AS_ORG_SCHEMA)

    frame = (
        pl.DataFrame(
            {
                "asn": [a for a, _ in asn_org],
                "org_id": [o for _, o in asn_org],
            }
        )
        .with_columns(
            pl.col("org_id")
            .replace_strict(org_names, default=None, return_dtype=pl.Utf8)
            .alias("org_name"),
            pl.lit(stamp).alias("snapshot_date"),
            pl.col("asn").cast(pl.UInt32),
        )
        .select(list(REF_AS_ORG_SCHEMA))
    )

    log.info(
        "AS2Org chargé",
        extra={"asns": frame.height, "organisations": frame["org_id"].n_unique()},
    )
    return frame


def sibling_asns(frame: pl.DataFrame, asn: int) -> set[int]:
    """AS partageant la même organisation que ``asn`` (soi-même exclu).

    Utilitaire pour les preuves affichées côté détecteur : « AS37100 et
    AS37105 appartiennent tous deux à Littoral Telecom ».
    """
    if frame.is_empty():
        return set()
    match = frame.filter(pl.col("asn") == asn)
    if match.is_empty():
        return set()
    org_id = match.get_column("org_id")[0]
    siblings = frame.filter((pl.col("org_id") == org_id) & (pl.col("asn") != asn))
    return set(siblings.get_column("asn").to_list())
