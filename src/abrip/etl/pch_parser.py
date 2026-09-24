"""Lecture des relevés PCH (``sh ip bgp``), pour les collecteurs ``project: pch``.

PCH ne distribue pas d'archives MRT mais des relevés quotidiens complets au
format texte Cisco classique (``show ip bgp``), gzippés, un fichier par
collecteur et par jour :

    https://downloads.pch.net/files/Routing_Data/IPv4_daily_snapshots/
        {YYYY}/{MM}/route-collector.{NOM}.pch.net/
        route-collector.{NOM}.pch.net-ipv4_bgp_routes.{YYYY}.{MM}.{DD}.gz

Extrait représentatif (colonnes alignées en largeur fixe ; le préfixe est omis
sur une ligne de continuation quand plusieurs chemins existent pour la même
route, et la colonne LocPrf est très souvent vide en pratique — un pair eBGP
ordinaire ne la renseigne pas) :

        Network          Next Hop            Metric LocPrf Weight Path
     *> 196.60.0.0/18    196.60.1.1               0             0 3320 37400 i
     *> 197.155.64.0/22  196.60.1.5                            0 6939 37100 i
     *                   196.60.1.9                             174 45090 i

**Repérage par position de colonne, pas par comptage de jetons.** Une colonne
LocPrf vide rend le nombre de jetons numériques avant le chemin variable (2 ou
3 selon les lignes) : un découpage par simple ``split()`` confondrait alors le
début du chemin d'AS avec Metric/LocPrf/Weight. La correction retenue ici —
repérer la position de caractère de chaque colonne sur la ligne d'en-tête, puis
découper les lignes de données à ces mêmes positions — est celle qu'utilisent
les parseurs réels de ce format (voir le parseur Rust de ``bgpkit-parser`` pour
les relevés texte Cisco, à la source de cette technique).

Limite assumée et documentée plutôt que dissimulée : ce format ne nomme pas
l'AS du pair émetteur — seule son adresse IP (« Next Hop ») est indiquée. La
convention retenue ici, usuelle pour l'exploitation de ces relevés, consiste à
prendre le **premier AS du chemin** comme identité du pair observé : correcte
quand le collecteur ne s'ajoute pas lui-même au chemin (le cas normal d'un
collecteur passif), approximative sinon.
"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from abrip.etl.mrt_parser import MRTParser
from abrip.logging_conf import get_logger

log = get_logger(__name__)

_PREFIX_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}")
_NEXT_HOP_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
_TRAILING_ORIGIN = re.compile(r"\s+[ie?]\s*$")


def _opener(path: Path):
    return gzip.open if path.suffix == ".gz" else open


class _Columns:
    """Positions de caractère des colonnes Next Hop / Path, lues sur l'en-tête."""

    __slots__ = ("next_hop", "path")

    def __init__(self, header: str) -> None:
        self.next_hop = header.find("Next Hop")
        self.path = header.find("Path")

    @property
    def valid(self) -> bool:
        return self.next_hop >= 0 and self.path > self.next_hop

    @staticmethod
    def find(lines: list[str]) -> _Columns | None:
        for line in lines:
            if "Next Hop" in line and "Path" in line:
                columns = _Columns(line)
                if columns.valid:
                    return columns
        return None


def _as_path_tokens(path_field: str) -> list[int] | None:
    text = _TRAILING_ORIGIN.sub("", path_field.strip())
    if not text:
        return None
    tokens: list[int] = []
    for raw in text.replace("{", " ").replace("}", " ").replace(",", " ").split():
        if raw.isdigit():
            tokens.append(int(raw))
        else:
            return None  # jeton inattendu (as-set exotique, artefact) : ligne écartée
    return tokens or None


def _dedup_consecutive(path: list[int]) -> list[int]:
    out: list[int] = []
    for asn in path:
        if not out or out[-1] != asn:
            out.append(asn)
    return out


def _snapshot_from_filename(name: str) -> datetime:
    """Extrait l'horodatage du nom de fichier (``...-ipv4_bgp_routes.YYYY.MM.DD.gz``).

    Repli sur l'heure courante si le nom ne suit pas le format attendu : un
    fichier mal nommé ne doit pas faire échouer tout le lot de curation, juste
    porter un horodatage moins précis.
    """
    match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", name)
    if not match:
        log.warning(
            "horodatage introuvable dans le nom de fichier PCH", extra={"pch_filename": name}
        )
        return datetime.now(UTC).replace(tzinfo=None)
    year, month, day = (int(g) for g in match.groups())
    return datetime(year, month, day)


class PchTextDumpParser(MRTParser):
    """Parseur des relevés texte PCH, conforme à l'interface ``MRTParser``.

    Produit exclusivement des enregistrements RIB (``elem_type="R"``) : un
    relevé PCH est un instantané complet à un instant donné, pas un flux
    d'annonces/retraits — il alimente donc ``rib_snapshots`` plus naturellement
    que ``bgp_elements`` (voir ``etl.curate``).
    """

    name = "pch"

    def available(self) -> bool:
        return True  # aucune dépendance externe : lecture de texte pur

    def parse(self, path: Path, collector: str) -> Iterator[dict[str, Any]]:
        snapshot_ts = _snapshot_from_filename(path.name)

        with _opener(path)(path, "rt", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()

        columns = _Columns.find(lines[:20])
        if columns is None:
            log.warning("en-tête de colonnes introuvable, relevé ignoré", extra={"path": str(path)})
            return

        current_prefix: str | None = None
        count = 0
        for line in lines:
            if len(line) <= columns.next_hop:
                continue
            network_field = line[: columns.next_hop]
            prefix_match = _PREFIX_RE.search(network_field)
            if prefix_match:
                current_prefix = prefix_match.group(0)
            prefix = current_prefix
            if not prefix:
                continue  # aucune route encore vue : en-tête, ligne vide, préambule

            next_hop_match = _NEXT_HOP_RE.search(line[columns.next_hop : columns.path])
            if not next_hop_match:
                continue
            next_hop = next_hop_match.group(0)

            as_path = _as_path_tokens(line[columns.path :])
            if not as_path:
                continue

            try:
                prefix_len = int(prefix.split("/", 1)[1])
            except (IndexError, ValueError):
                continue

            origin_asn = as_path[-1]
            peer_asn = as_path[0]  # limite documentée en tête de module
            count += 1
            yield {
                "ts": snapshot_ts,
                "collector": collector,
                "peer_asn": peer_asn,
                "peer_ip": next_hop,
                "elem_type": "R",
                "prefix": prefix,
                "prefix_ip_version": 4,
                "prefix_len": prefix_len,
                "as_path_raw": as_path,
                "as_path_dedup": _dedup_consecutive(as_path),
                "as_path_len": len(as_path),
                "origin_asn": origin_asn,
                "next_hop": next_hop,
                "communities": None,
                "med": None,
                "local_pref": None,
                "source_file": path.name,
            }

        log.info("relevé PCH lu", extra={"path": str(path), "routes": count})
