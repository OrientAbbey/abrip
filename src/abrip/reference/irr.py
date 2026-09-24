"""Référentiel IRR de repli, pour quand RPKI répond ``not-found`` (L4a).

La validation RPKI (``abrip.reference.rpki``) est la seule preuve
cryptographique dont dispose la plateforme, mais ``not-found`` est le statut
majoritaire dans la zone AFRINIC faute de ROA publiés — voir
``docs/limites-et-remediations.md``. Ce module ajoute un second avis,
déclaratif et non signé, à partir des objets ``route``/``route6`` enregistrés
dans les registres de routage (IRR).

Source retenue : l'API REST officielle de la base RIPE
(``https://rest.db.ripe.net``), qui interroge en HTTP/JSON plusieurs registres
miroirs (RADB, RIPE, APNIC, ARIN...) sans nécessiter le protocole WHOIS brut
(port 43, généralement filtré par les pare-feux et non joignable via un simple
client HTTP). C'est une source réelle et stable, pas une invention : le schéma
de réponse (``objects.object[].attributes.attribute[]``) est celui documenté
par le NCC depuis plus d'une décennie.

Limite assumée, à ne pas dissimuler : AFRINIC gère son propre registre IRR
(``whois.afrinic.net``), qui n'est pas nécessairement mirroré par RIPE. Beaucoup
d'opérateurs de la zone enregistrent malgré tout leurs objets ``route`` chez
RADB par habitude ou par choix historique, ce qui rend cette source utile sans
être exhaustive — exactement le type de second avis imparfait mais rarement
inutile que L4a demande.
"""

from __future__ import annotations

import ipaddress
from collections import defaultdict
from datetime import date
from typing import Any

import httpx
import polars as pl

from abrip.logging_conf import get_logger
from abrip.models import REF_IRR_ROUTE_SCHEMA, IrrStatus

log = get_logger(__name__)

DEFAULT_SOURCES = ("RADB", "RIPE", "APNIC", "ARIN")


class RipeDbClient:
    """Client de l'API REST de la base RIPE (``rest.db.ripe.net``).

    Interface volontairement étroite : une méthode par usage réel du projet,
    plutôt qu'un client générique de la base RIPE. ``transport`` est
    injectable pour les tests (``httpx.MockTransport``), sans dépendance de
    test supplémentaire.
    """

    def __init__(
        self,
        base_url: str = "https://rest.db.ripe.net",
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

    def __enter__(self) -> RipeDbClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _search(
        self, query: str, type_filter: str, sources: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        try:
            response = self._client.get(
                "/search.json",
                params={
                    "query-string": query,
                    "type-filter": type_filter,
                    "source": ",".join(sources),
                    "flags": "no-referenced",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("requête RIPE DB en échec", extra={"query": query, "error": str(exc)})
            return []
        try:
            payload = response.json()
        except ValueError:
            return []
        objects = (payload.get("objects") or {}).get("object") or []
        return objects if isinstance(objects, list) else [objects]

    def lookup_routes(
        self, prefix: str, sources: tuple[str, ...] = DEFAULT_SOURCES
    ) -> list[tuple[str, int, str]]:
        """Objets ``route``/``route6`` couvrant ``prefix``.

        Retourne une liste de ``(préfixe déclaré, ASN, source)``. Une recherche
        échouée (réseau, service indisponible) retourne une liste vide plutôt
        que de lever une exception : ce module ne doit jamais interrompre le
        pipeline de détection.
        """
        type_filter = "route6" if ":" in prefix else "route"
        objects = self._search(prefix, type_filter, sources)
        found: list[tuple[str, int, str]] = []
        for obj in objects:
            attrs = _attribute_map(obj)
            route = attrs.get("route") or attrs.get("route6")
            origin = attrs.get("origin")
            source = obj.get("source", {}).get("id", "?")
            if not route or not origin:
                continue
            try:
                asn = int(str(origin).upper().removeprefix("AS"))
            except ValueError:
                continue
            found.append((route, asn, source))
        return found

    def expand_as_set(self, as_set: str, sources: tuple[str, ...] = DEFAULT_SOURCES) -> set[int]:
        """AS membres directs d'un ``as-set`` (sans récursion sur les as-sets imbriqués).

        Utilisé par ``abrip.reference.peeringdb`` pour corroborer une relation
        client-fournisseur déclarée : si l'AS-SET publié par un fournisseur
        contient le client, c'est un accord entre deux sources indépendantes
        (PeeringDB pour le nom de l'AS-SET, l'IRR pour son contenu).
        La non-récursion est un choix assumé : un as-set imbriqué à plusieurs
        niveaux demanderait des appels en cascade coûteux pour un gain marginal
        sur la corroboration recherchée ici.
        """
        objects = self._search(as_set, "as-set", sources)
        members: set[int] = set()
        for obj in objects:
            attrs = _attribute_all(obj)
            for value in attrs.get("members", []):
                token = value.strip().upper()
                if token.startswith("AS") and token[2:].isdigit():
                    members.add(int(token[2:]))
        return members


def _attribute_map(obj: dict[str, Any]) -> dict[str, str]:
    """Dernière valeur par nom d'attribut (suffisant pour route/origin/source)."""
    out: dict[str, str] = {}
    for attr in (obj.get("attributes") or {}).get("attribute") or []:
        name = attr.get("name")
        if name:
            out[name] = attr.get("value", "")
    return out


def _attribute_all(obj: dict[str, Any]) -> dict[str, list[str]]:
    """Toutes les valeurs par nom d'attribut (nécessaire pour ``members``,
    répété une fois par AS dans un objet ``as-set``)."""
    out: dict[str, list[str]] = defaultdict(list)
    for attr in (obj.get("attributes") or {}).get("attribute") or []:
        name = attr.get("name")
        if name:
            out[name].append(attr.get("value", ""))
    return out


class IrrValidator:
    """Index d'objets route IRR, interrogeable comme ``RpkiValidator``.

    Même structure (index par supernet, recherche par ancêtres successifs) que
    le validateur RPKI : un lecteur qui connaît déjà l'un reconnaît l'autre
    immédiatement, et les deux peuvent être maintenus en parallèle sans
    dupliquer la logique de recherche par préfixe.
    """

    def __init__(self, entries: list[tuple[str, int, str]]) -> None:
        self._index: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for prefix, asn, source in entries:
            try:
                network = ipaddress.ip_network(prefix, strict=False)
            except ValueError:
                continue
            self._index[str(network)].append((asn, source))
        log.info(
            "index IRR construit", extra={"objets": len(entries), "prefixes": len(self._index)}
        )

    @classmethod
    def from_frame(cls, frame: pl.DataFrame) -> IrrValidator:
        if frame.is_empty():
            return cls([])
        return cls([(r["prefix"], int(r["asn"]), r["source"]) for r in frame.iter_rows(named=True)])

    def covering_routes(self, prefix: str) -> list[tuple[str, int, str]]:
        try:
            network = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            return []
        found: list[tuple[str, int, str]] = []
        for length in range(network.prefixlen + 1):
            candidate = str(network.supernet(new_prefix=length))
            for asn, source in self._index.get(candidate, ()):
                found.append((candidate, asn, source))
        return found

    def validate(self, prefix: str, origin_asn: int | None) -> IrrStatus:
        covering = self.covering_routes(prefix)
        if not covering:
            return IrrStatus.ABSENT
        if origin_asn is None:
            return IrrStatus.ABSENT
        if any(asn == origin_asn for _, asn, _ in covering):
            return IrrStatus.CONSISTENT
        return IrrStatus.INCONSISTENT


def build_irr_reference(
    client: RipeDbClient, prefixes: list[str], snapshot_date: date | None = None
) -> pl.DataFrame:
    """Interroge l'IRR pour une liste de préfixes et produit la table ``ref_irr_route``.

    Pensé pour être appelé une fois par cycle de synchronisation (``abrip
    reference sync --sources irr``), sur les préfixes actuellement annoncés —
    pas à la volée pendant la détection, où une latence réseau par préfixe
    serait inacceptable.
    """
    stamp = (snapshot_date or date.today()).isoformat()
    rows: list[dict[str, Any]] = []
    for prefix in prefixes:
        for route, asn, source in client.lookup_routes(prefix):
            rows.append({"prefix": route, "asn": asn, "source": source, "snapshot_date": stamp})
    if not rows:
        return pl.DataFrame(schema=REF_IRR_ROUTE_SCHEMA)
    return pl.DataFrame(rows, schema=REF_IRR_ROUTE_SCHEMA, strict=False).unique()
