"""Validation d'origine RPKI.

C'est le module qui transforme une heuristique en preuve : sans ROA, un MOAS est
une curiosité ; avec un ROA violé, c'est une annonce non autorisée.

Règle de validation (RFC 6811) :
  - **valid**     : un ROA couvre le préfixe, ``prefix_len <= max_len`` et l'ASN correspond ;
  - **invalid**   : au moins un ROA couvre le préfixe, mais aucun ne l'autorise ;
  - **not-found** : aucun ROA ne couvre le préfixe.

L'implémentation utilise un index par longueur de préfixe couvrant : pour un
préfixe /24, on teste ses 25 ancêtres possibles (/0 à /24). C'est O(33) par
requête, sans structure trie à maintenir.
"""

from __future__ import annotations

import ipaddress
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import polars as pl

from abrip.logging_conf import get_logger
from abrip.models import REF_ROA_SCHEMA, RoaEntry, RpkiStatus

log = get_logger(__name__)


def parse_roa_payload(payload: dict | list) -> list[RoaEntry]:
    """Accepte les formats d'export usuels (Cloudflare, RIPE Validator, routinator)."""
    items = payload.get("roas", payload) if isinstance(payload, dict) else payload
    entries: list[RoaEntry] = []
    for item in items:
        prefix = item.get("prefix")
        asn_raw = item.get("asn")
        if prefix is None or asn_raw is None:
            continue
        asn = int(str(asn_raw).upper().removeprefix("AS"))
        max_len = int(item.get("maxLength") or item.get("max_length") or prefix.split("/")[1])
        entries.append(RoaEntry(prefix=prefix, asn=asn, max_len=max_len, ta=item.get("ta", "")))
    return entries


def load_roas(path: Path) -> list[RoaEntry]:
    with path.open(encoding="utf-8") as handle:
        return parse_roa_payload(json.load(handle))


def roas_to_frame(entries: list[RoaEntry], snapshot_date: date | None = None) -> pl.DataFrame:
    stamp = (snapshot_date or date.today()).isoformat()
    if not entries:
        return pl.DataFrame(schema=REF_ROA_SCHEMA)
    return pl.DataFrame(
        [
            {
                "prefix": e.prefix,
                "asn": e.asn,
                "max_len": e.max_len,
                "ta": e.ta,
                "snapshot_date": stamp,
            }
            for e in entries
        ],
        schema=REF_ROA_SCHEMA,
    )


class RpkiValidator:
    """Index de ROA interrogeable. Instancier une fois, réutiliser."""

    def __init__(self, entries: list[RoaEntry]) -> None:
        self._index: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for entry in entries:
            try:
                network = ipaddress.ip_network(entry.prefix, strict=False)
            except ValueError:
                continue
            self._index[str(network)].append((entry.asn, entry.max_len))
        log.info("index RPKI construit", extra={"roas": len(entries), "prefixes": len(self._index)})

    @classmethod
    def from_file(cls, path: Path) -> RpkiValidator:
        return cls(load_roas(path))

    @classmethod
    def from_frame(cls, frame: pl.DataFrame) -> RpkiValidator:
        return cls(
            [
                RoaEntry(prefix=r["prefix"], asn=int(r["asn"]), max_len=int(r["max_len"]))
                for r in frame.iter_rows(named=True)
            ]
        )

    def covering_roas(self, prefix: str) -> list[tuple[str, int, int]]:
        """ROA couvrant le préfixe : liste de (préfixe du ROA, asn, max_len)."""
        try:
            network = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            return []
        found: list[tuple[str, int, int]] = []
        for length in range(network.prefixlen + 1):
            candidate = str(network.supernet(new_prefix=length))
            for asn, max_len in self._index.get(candidate, ()):
                found.append((candidate, asn, max_len))
        return found

    def validate(self, prefix: str, origin_asn: int | None) -> RpkiStatus:
        covering = self.covering_roas(prefix)
        if not covering:
            return RpkiStatus.NOT_FOUND
        # Sans origine (retrait, chemin vide, AS_SET en tête), aucune conclusion
        # n'est possible : déclarer « invalide » accuserait sur une absence.
        if origin_asn is None:
            return RpkiStatus.NOT_FOUND
        try:
            prefix_len = ipaddress.ip_network(prefix, strict=False).prefixlen
        except ValueError:
            return RpkiStatus.NOT_FOUND
        for _, asn, max_len in covering:
            if asn == origin_asn and prefix_len <= max_len:
                return RpkiStatus.VALID
        return RpkiStatus.INVALID

    def authorised_asns(self, prefix: str) -> set[int]:
        return {asn for _, asn, _ in self.covering_roas(prefix)}

    def validate_frame(
        self, frame: pl.DataFrame, prefix_col: str = "prefix", asn_col: str = "origin_asn"
    ) -> pl.DataFrame:
        """Ajoute une colonne ``rpki_status`` à un DataFrame.

        La validation se fait sur les couples distincts puis par jointure : sur
        plusieurs millions de lignes, valider ligne à ligne serait rédhibitoire.
        """
        if frame.is_empty():
            return frame.with_columns(pl.lit(None, dtype=pl.Utf8).alias("rpki_status"))
        pairs = frame.select([prefix_col, asn_col]).unique()
        statuses = [
            self.validate(row[prefix_col], row[asn_col]).value
            for row in pairs.iter_rows(named=True)
        ]
        lookup = pairs.with_columns(pl.Series("rpki_status", statuses))
        return frame.join(lookup, on=[prefix_col, asn_col], how="left")
