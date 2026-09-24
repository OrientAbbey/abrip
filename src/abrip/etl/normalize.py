"""Normalisation des données BGP brutes.

Le reste de la plateforme ne manipule que des enregistrements normalisés : c'est
ici que sont absorbées les différences entre bibliothèques de parsing et les
subtilités du protocole (prepending, AS_SET, ASN réservés).
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

# ASN reserves (RFC 6996, 7300, 5398) : ne doivent pas apparaitre en origine publique.
PRIVATE_ASN_RANGES: tuple[tuple[int, int], ...] = (
    (64512, 65534),
    (65535, 65535),
    (4200000000, 4294967294),
    (4294967295, 4294967295),
)
RESERVED_ASNS: frozenset[int] = frozenset({0, 23456})

# Prefixes non routables (RFC 1918, 6598, 5737, 3927, 6890...)
BOGON_V4: tuple[str, ...] = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
)
BOGON_V6: tuple[str, ...] = (
    "::/8",
    "100::/64",
    "2001:db8::/32",
    "fc00::/7",
    "fe80::/10",
    "ff00::/8",
)

_BOGON_NETS = [ipaddress.ip_network(n) for n in BOGON_V4 + BOGON_V6]
_AS_SET_RE = re.compile(r"[{\[]")


def is_private_asn(asn: int) -> bool:
    return asn in RESERVED_ASNS or any(low <= asn <= high for low, high in PRIVATE_ASN_RANGES)


def is_bogon_prefix(prefix: str) -> bool:
    try:
        network = ipaddress.ip_network(prefix, strict=False)
    except ValueError:
        return True
    return any(
        network.version == bogon.version and network.subnet_of(bogon)  # type: ignore[arg-type]
        for bogon in _BOGON_NETS
    )


def prefix_info(prefix: str) -> tuple[int, int]:
    """Retourne (version IP, longueur du masque)."""
    network = ipaddress.ip_network(prefix, strict=False)
    return network.version, network.prefixlen


def parse_as_path(raw: Any) -> tuple[list[int], bool]:
    """Convertit un AS-path en liste d'entiers, en signalant la présence d'un AS_SET.

    Un AS_SET (``{64500,64501}``) ne désigne pas un AS traversé mais un ensemble
    issu d'une agrégation : on le retire du chemin tout en gardant le signal, car
    il rend l'attribution d'origine ambiguë.
    """
    if raw is None:
        return [], False
    tokens = [str(t) for t in raw] if isinstance(raw, (list, tuple)) else str(raw).split()

    has_as_set = any(_AS_SET_RE.search(t) for t in tokens)
    path: list[int] = []
    for token in tokens:
        cleaned = token.strip("{}[](),")
        for piece in cleaned.split(","):
            if piece.isdigit():
                path.append(int(piece))
            elif "." in piece:  # notation asdot 1.10
                try:
                    high, low = piece.split(".")
                    path.append(int(high) * 65536 + int(low))
                except ValueError:
                    continue
    return path, has_as_set


def dedup_prepending(path: list[int]) -> list[int]:
    """Supprime le prepending consécutif en conservant l'ordre du chemin."""
    out: list[int] = []
    for asn in path:
        if not out or out[-1] != asn:
            out.append(asn)
    return out


def normalize_as_path(raw: Any) -> tuple[list[int], list[int], bool, int | None]:
    """Retourne (chemin brut, chemin dédupliqué, présence d'AS_SET, AS d'origine)."""
    path, has_as_set = parse_as_path(raw)
    dedup = dedup_prepending(path)
    origin = dedup[-1] if dedup else None
    return path, dedup, has_as_set, origin


def to_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromtimestamp(float(value), tz=UTC).replace(tzinfo=None)


def to_element_dict(
    *,
    timestamp: Any,
    collector: str,
    peer_asn: Any,
    peer_ip: str,
    elem_type: str,
    prefix: str,
    as_path: Any = None,
    next_hop: str | None = None,
    communities: Iterable[str] | None = None,
    med: Any = None,
    local_pref: Any = None,
    source_file: str = "",
) -> dict[str, Any] | None:
    """Construit un enregistrement conforme à ``BGP_ELEMENTS_SCHEMA``.

    Retourne ``None`` si le préfixe est illisible : on préfère perdre une ligne
    aberrante plutôt que de corrompre la table.
    """
    try:
        version, length = prefix_info(prefix)
    except ValueError:
        return None

    path, dedup, has_as_set, origin = normalize_as_path(as_path)
    kind = (elem_type or "").upper()[:1] or "A"
    if kind == "W":
        origin, path, dedup = None, [], []

    return {
        "ts": to_timestamp(timestamp),
        "collector": collector,
        "peer_asn": int(peer_asn or 0),
        "peer_ip": str(peer_ip or ""),
        "elem_type": kind,
        "prefix": prefix,
        "prefix_ip_version": version,
        "prefix_len": length,
        "origin_asn": origin,
        "as_path": path,
        "as_path_dedup": dedup,
        "as_path_len": len(dedup),
        "has_as_set": has_as_set,
        "next_hop": next_hop,
        "communities": list(communities) if communities else None,
        "med": int(med) if med is not None else None,
        "local_pref": int(local_pref) if local_pref is not None else None,
        "source_file": source_file,
    }
