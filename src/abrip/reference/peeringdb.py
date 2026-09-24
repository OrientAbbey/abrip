"""Corroboration des relations CAIDA par PeeringDB et l'IRR (L3).

Le détecteur valley-free dépend de relations que CAIDA **infère** à partir des
chemins observés — voir ``docs/adr/0003``. Une relation mal inférée produit une
fausse fuite de routes, ou en masque une vraie. Ce module ajoute deux sources
**déclarées** (l'opérateur les affirme lui-même, il ne les subit pas) :

- **PeeringDB** : la co-présence de deux AS sur le même point d'échange, avec
  une politique de peering ouverte des deux côtés, est un indice réel d'une
  relation ``p2p``. Ce n'est pas la relation elle-même — PeeringDB ne déclare
  jamais explicitement « je suis le client de X » — mais un faisceau
  d'indices cohérent avec elle.
- **IRR** (via ``abrip.reference.irr.RipeDbClient``) : si l'AS-SET publié par
  un fournisseur (champ ``irr_as_set`` de son objet PeeringDB) contient l'AS du
  client, c'est une corroboration d'une relation ``p2c`` — la technique
  qu'utilisent réellement les ingénieurs réseau pour vérifier qui transite pour
  qui.

Une relation confirmée par au moins deux sources indépendantes est jugée fiable
au sens du détecteur valley-free ; une relation CAIDA seule reste utilisable
mais plafonne en sévérité ``watch`` (voir ``configs/detection.yaml``,
``valley_free.min_sources_for_critical``).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import polars as pl

from abrip.logging_conf import get_logger
from abrip.models import REF_AS_REL_EVIDENCE_SCHEMA, Relationship
from abrip.reference.irr import RipeDbClient

log = get_logger(__name__)


class PeeringDbClient:
    """Client minimal de l'API publique PeeringDB (non authentifié, lecture seule)."""

    def __init__(
        self,
        base_url: str = "https://www.peeringdb.com/api",
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PeeringDbClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("requête PeeringDB en échec", extra={"path": path, "error": str(exc)})
            return []
        try:
            return response.json().get("data", [])
        except ValueError:
            return []

    def network(self, asn: int) -> dict[str, Any] | None:
        """Objet ``net`` de PeeringDB pour cet ASN — porte notamment ``irr_as_set``."""
        results = self._get("/net", {"asn": asn})
        return results[0] if results else None

    def ixp_presence(self, asn: int) -> set[int]:
        """Identifiants des points d'échange où l'AS est présent (``netixlan``)."""
        results = self._get("/netixlan", {"asn": asn})
        return {int(r["ix_id"]) for r in results if r.get("ix_id") is not None}


def corroborate_peer(a: int, b: int, peeringdb: PeeringDbClient) -> bool:
    """Deux AS présents au même point d'échange sont des pairs plausibles."""
    ix_a = peeringdb.ixp_presence(a)
    if not ix_a:
        return False
    ix_b = peeringdb.ixp_presence(b)
    return bool(ix_a & ix_b)


def corroborate_provider(
    provider: int, customer: int, peeringdb: PeeringDbClient, irr: RipeDbClient
) -> bool:
    """Le client apparaît-il dans l'AS-SET déclaré par le fournisseur ?"""
    network = peeringdb.network(provider)
    as_set = (network or {}).get("irr_as_set", "") or ""
    as_set = as_set.split("::")[-1].strip()  # forme "AFRINIC::AS-X" possible
    if not as_set or not as_set.upper().startswith("AS-"):
        return False
    members = irr.expand_as_set(as_set)
    return customer in members


def build_relationship_evidence(
    caida: pl.DataFrame,
    peeringdb: PeeringDbClient,
    irr: RipeDbClient,
    snapshot_date: date | None = None,
    max_pairs: int = 200,
) -> pl.DataFrame:
    """Corrobore chaque relation CAIDA connue et produit ``ref_as_rel_evidence``.

    ``max_pairs`` borne le nombre de requêtes réseau : ce module est pensé pour
    être appelé sur les AS impliqués dans le périmètre africain, pas sur
    l'intégralité du graphe CAIDA (plusieurs centaines de milliers de liens).
    """
    stamp = (snapshot_date or date.today()).isoformat()
    if caida.is_empty():
        return pl.DataFrame(schema=REF_AS_REL_EVIDENCE_SCHEMA)

    pairs = caida.unique(subset=["as_a", "as_b"]).head(max_pairs)
    rows: list[dict[str, Any]] = []
    for row in pairs.iter_rows(named=True):
        a, b = int(row["as_a"]), int(row["as_b"])
        relationship = row["relationship"]
        sources = ["caida"]
        try:
            if relationship == Relationship.P2P.value:
                if corroborate_peer(a, b, peeringdb):
                    sources.append("peeringdb")
            elif relationship == Relationship.P2C.value and corroborate_provider(
                a, b, peeringdb, irr
            ):
                sources.append("irr")
        except Exception as exc:
            log.warning(
                "corroboration en échec pour un lien",
                extra={"as_a": a, "as_b": b, "error": str(exc)},
            )
        rows.append(
            {
                "as_a": a,
                "as_b": b,
                "relationship": relationship,
                "sources": sources,
                "snapshot_date": stamp,
            }
        )

    log.info(
        "corroboration des relations terminée",
        extra={
            "liens": len(rows),
            "corrobores": sum(1 for r in rows if len(r["sources"]) > 1),
        },
    )
    return pl.DataFrame(rows, schema=REF_AS_REL_EVIDENCE_SCHEMA, strict=False)
