"""Accès unifié aux fichiers MRT.

Décision d'architecture centrale du projet (voir ``docs/adr/0001``) : aucun
module en aval ne sait quelle bibliothèque a lu le fichier. Trois
implémentations interchangeables, sélectionnées par configuration :

  - ``bgpkit``   : binding Rust, rapide, installation légère — choix par défaut ;
  - ``mrtparse`` : pur Python, plus lent, aucune dépendance native — repli sûr ;
  - ``synthetic``: générateur de données réalistes, pour la démo et les tests.

``auto`` prend la première implémentation réellement disponible.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from abrip.etl.normalize import to_element_dict
from abrip.logging_conf import get_logger

log = get_logger(__name__)


class MRTParser(abc.ABC):
    """Interface commune. Une implémentation produit des dictionnaires normalisés."""

    name: str = "abstract"

    @abc.abstractmethod
    def available(self) -> bool:
        """La bibliothèque sous-jacente est-elle importable ?"""

    @abc.abstractmethod
    def parse(self, path: Path, collector: str) -> Iterator[dict[str, Any]]:
        """Itère sur les éléments BGP du fichier, sans le charger entièrement."""


class BgpkitParser(MRTParser):
    name = "bgpkit"

    def available(self) -> bool:
        try:
            import pybgpkit_parser  # noqa: F401
        except ImportError:
            return False
        return True

    def parse(self, path: Path, collector: str) -> Iterator[dict[str, Any]]:
        from pybgpkit_parser import Parser

        source = str(path)
        for elem in Parser(url=source).parse_iter():
            record = to_element_dict(
                timestamp=elem.get("timestamp"),
                collector=collector,
                peer_asn=elem.get("peer_asn"),
                peer_ip=elem.get("peer_ip", ""),
                elem_type=elem.get("elem_type", "A"),
                prefix=elem.get("prefix", ""),
                as_path=elem.get("as_path"),
                next_hop=elem.get("next_hop"),
                communities=elem.get("communities"),
                med=elem.get("med"),
                local_pref=elem.get("local_pref"),
                source_file=path.name,
            )
            if record is not None:
                yield record


class MrtparseParser(MRTParser):
    """Repli pur Python. Plus lent d'un ordre de grandeur, mais toujours installable."""

    name = "mrtparse"

    def available(self) -> bool:
        try:
            import mrtparse  # noqa: F401
        except ImportError:
            return False
        return True

    def parse(self, path: Path, collector: str) -> Iterator[dict[str, Any]]:
        from mrtparse import Reader

        for entry in Reader(str(path)):
            data = entry.data
            subtype = _first(data.get("subtype", {}))
            timestamp = _first_key(data.get("timestamp", {}))
            if subtype in ("BGP4MP_MESSAGE", "BGP4MP_MESSAGE_AS4"):
                yield from self._parse_update(data, collector, timestamp, path.name)
            elif "rib_entries" in data:
                yield from self._parse_rib(data, collector, timestamp, path.name)

    def _parse_update(
        self, data: dict, collector: str, timestamp: Any, filename: str
    ) -> Iterator[dict[str, Any]]:
        message = data.get("bgp_message", {})
        peer_asn = data.get("peer_as")
        peer_ip = data.get("peer_ip", "")
        attributes = _attributes(message.get("path_attributes", []))

        for withdrawn in message.get("withdrawn_routes", []):
            record = to_element_dict(
                timestamp=timestamp,
                collector=collector,
                peer_asn=peer_asn,
                peer_ip=peer_ip,
                elem_type="W",
                prefix=_cidr(withdrawn),
                source_file=filename,
            )
            if record:
                yield record

        for nlri in message.get("nlri", []):
            record = to_element_dict(
                timestamp=timestamp,
                collector=collector,
                peer_asn=peer_asn,
                peer_ip=peer_ip,
                elem_type="A",
                prefix=_cidr(nlri),
                as_path=attributes.get("as_path"),
                next_hop=attributes.get("next_hop"),
                communities=attributes.get("communities"),
                med=attributes.get("med"),
                source_file=filename,
            )
            if record:
                yield record

    def _parse_rib(
        self, data: dict, collector: str, timestamp: Any, filename: str
    ) -> Iterator[dict[str, Any]]:
        prefix = _cidr(data)
        for entry in data.get("rib_entries", []):
            attributes = _attributes(entry.get("path_attributes", []))
            record = to_element_dict(
                timestamp=entry.get("originated_time", timestamp),
                collector=collector,
                peer_asn=entry.get("peer_index"),
                peer_ip="",
                elem_type="R",
                prefix=prefix,
                as_path=attributes.get("as_path"),
                next_hop=attributes.get("next_hop"),
                communities=attributes.get("communities"),
                source_file=filename,
            )
            if record:
                yield record


class SyntheticParser(MRTParser):
    """Génère un flux BGP réaliste sans aucun fichier.

    Sert à deux choses : permettre à un évaluateur de lancer la plateforme
    immédiatement, et fournir aux tests un jeu contenant des anomalies connues
    (MOAS, fuite de routes, pic de churn) dont on vérifie qu'elles sont bien
    détectées.
    """

    name = "synthetic"

    def available(self) -> bool:
        return True

    def parse(self, path: Path, collector: str) -> Iterator[dict[str, Any]]:
        from abrip.demo.generator import generate_elements

        seed = abs(hash(path.name)) % (2**32)
        yield from generate_elements(collector=collector, seed=seed, source_file=path.name)


_IMPLEMENTATIONS: dict[str, type[MRTParser]] = {
    "bgpkit": BgpkitParser,
    "mrtparse": MrtparseParser,
    "synthetic": SyntheticParser,
}

_PREFERENCE: tuple[str, ...] = ("bgpkit", "mrtparse", "synthetic")


def get_parser(name: str = "auto") -> MRTParser:
    if name != "auto":
        parser = _IMPLEMENTATIONS[name]()
        if not parser.available():
            raise RuntimeError(
                f"Parseur '{name}' indisponible. Installer l'extra correspondant "
                f"(pip install -e '.[{name}]') ou choisir etl.parser: auto."
            )
        return parser

    for candidate in _PREFERENCE:
        parser = _IMPLEMENTATIONS[candidate]()
        if parser.available():
            if candidate != _PREFERENCE[0]:
                log.warning("repli de parseur", extra={"parser": candidate})
            return parser
    raise RuntimeError("Aucun parseur MRT disponible.")


# --- utilitaires mrtparse -------------------------------------------------
def _first(mapping: dict) -> str:
    return next(iter(mapping.values()), "") if isinstance(mapping, dict) else str(mapping)


def _first_key(mapping: dict) -> Any:
    return next(iter(mapping.keys()), None) if isinstance(mapping, dict) else mapping


def _cidr(item: dict) -> str:
    return f"{item.get('prefix', '')}/{item.get('length', item.get('prefix_length', 0))}"


def _attributes(path_attributes: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for attribute in path_attributes:
        kind = _first(attribute.get("type", {}))
        value = attribute.get("value")
        if kind == "AS_PATH":
            segments: list[str] = []
            for segment in value or []:
                segments.extend(str(v) for v in segment.get("value", []))
            out["as_path"] = segments
        elif kind == "NEXT_HOP":
            out["next_hop"] = value
        elif kind == "COMMUNITY":
            out["communities"] = value
        elif kind == "MULTI_EXIT_DISC":
            out["med"] = value
    return out
