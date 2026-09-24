"""Détection d'anycast légitime, troisième filtre du détecteur MOAS (L6).

Un préfixe annoncé simultanément par plusieurs origines n'est pas forcément un
détournement : l'anycast (DNS, CDN) le fait en permanence, par construction. Ce
module croise deux signaux, chacun insuffisant seul :

- **un catalogue public d'anycast connu** — le projet ``bgp.tools`` scanne le
  routage mondial et publie, à chaque passage, la liste des préfixes qu'il a
  détectés comme anycast (``github.com/bgptools/anycast-prefixes``, licence
  ouverte, mis à jour en continu). Une entrée dans ce catalogue est un fait
  observé, pas une déclaration ;
- **une divergence de chemin entre les deux origines** — un anycast légitime
  fait typiquement apparaître des chemins d'AS très différents pour chaque
  origine (chaque site anycast a ses propres transitaires locaux), alors qu'un
  détournement partage souvent une partie du chemin amont avec l'origine
  légitime.

Aucun des deux signaux n'est utilisé seul : un préfixe présent dans le
catalogue mais dont les deux chemins observés sont quasi identiques n'est pas
filtré ici — ce serait alors plus probablement un artefact de collecte qu'un
site anycast distinct.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from datetime import date

import httpx
import polars as pl

from abrip.logging_conf import get_logger
from abrip.models import REF_ANYCAST_SCHEMA

log = get_logger(__name__)

ANYCATCH_V4_URL = (
    "https://raw.githubusercontent.com/bgptools/anycast-prefixes/master/anycatch-v4-prefixes.csv"
)
ANYCATCH_V6_URL = (
    "https://raw.githubusercontent.com/bgptools/anycast-prefixes/master/anycatch-v6-prefixes.csv"
)

# En dessous de ce taux de recouvrement entre les deux chemins (hors origine),
# on les considère divergents — signature attendue de sites anycast distincts.
PATH_OVERLAP_CEILING = 0.5


def parse_anycatch_csv(text: str) -> set[str]:
    """Extrait les préfixes d'un export ``anycatch-v{4,6}-prefixes.csv``.

    Format sans en-tête, deux colonnes : ``prefixe,adresse_testée``. Seule la
    première colonne est retenue ; la seconde (l'adresse ayant servi au test
    par ping multi-site) ne sert pas ici.
    """
    prefixes: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        prefix = line.split(",", 1)[0].strip()
        try:
            ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            continue
        prefixes.add(prefix)
    return prefixes


def fetch_anycast_reference(
    settings_timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> set[str]:
    """Télécharge les listes IPv4 et IPv6 publiées par bgp.tools.

    Retourne un ensemble vide sur toute erreur réseau plutôt que de lever :
    l'absence de ce catalogue dégrade le filtre à ses seules deux autres
    conditions (même organisation, stabilité historique), elle ne doit jamais
    faire échouer une synchronisation de référentiels.
    """
    prefixes: set[str] = set()
    with httpx.Client(
        timeout=settings_timeout, transport=transport, follow_redirects=True
    ) as client:
        for url in (ANYCATCH_V4_URL, ANYCATCH_V6_URL):
            try:
                response = client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("catalogue anycast indisponible", extra={"url": url, "error": str(exc)})
                continue
            prefixes |= parse_anycatch_csv(response.text)
    return prefixes


def build_anycast_reference(
    prefixes: Iterable[str], snapshot_date: date | None = None
) -> pl.DataFrame:
    stamp = (snapshot_date or date.today()).isoformat()
    rows = [{"prefix": p, "source": "bgptools-anycatch", "snapshot_date": stamp} for p in prefixes]
    if not rows:
        return pl.DataFrame(schema=REF_ANYCAST_SCHEMA)
    return pl.DataFrame(rows, schema=REF_ANYCAST_SCHEMA, strict=False)


def is_known_anycast(prefix: str, anycast_prefixes: frozenset[str]) -> bool:
    """``prefix`` est-il connu comme anycast, ou couvert par un bloc anycast connu ?"""
    if prefix in anycast_prefixes:
        return True
    try:
        network = ipaddress.ip_network(prefix, strict=False)
    except ValueError:
        return False
    for candidate in anycast_prefixes:
        try:
            other = ipaddress.ip_network(candidate, strict=False)
        except ValueError:
            continue
        if other.version == network.version and network.subnet_of(other):  # type: ignore[arg-type]
            return True
    return False


def _path_overlap(path_a: list[int], path_b: list[int]) -> float:
    """Recouvrement de Jaccard entre deux chemins d'AS, origine exclue.

    L'origine est retirée avant comparaison : elle diffère par construction
    entre les deux candidats MOAS, la retenir biaiserait toujours le calcul
    vers « divergent » sans rien dire du reste du chemin.
    """
    set_a, set_b = set(path_a[:-1]), set(path_b[:-1])
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def is_anycast_candidate(
    prefix: str,
    paths_a: list[list[int]] | None,
    paths_b: list[list[int]] | None,
    anycast_prefixes: frozenset[str],
) -> bool:
    """Le MOAS observé ressemble-t-il à de l'anycast légitime plutôt qu'à un détournement ?

    Exige les deux signaux : présence au catalogue **et** chemins divergents.
    ``paths_a``/``paths_b`` peuvent être vides (chemin non retenu par
    l'agrégation) — dans ce cas, seul le catalogue est consulté, avec une
    exigence renforcée implicite : un opérateur prudent préférera vérifier
    manuellement plutôt que de se fier au seul catalogue.
    """
    if not is_known_anycast(prefix, anycast_prefixes):
        return False
    if not paths_a or not paths_b:
        return False
    # Le recouvrement le plus FORT parmi toutes les paires doit rester sous le
    # seuil : une seule paire de chemins qui se recoupe beaucoup suffit à
    # douter d'un anycast propre (topologie partagée, donc plus proche d'un
    # cas à examiner que d'un site distinct). Prendre le minimum ferait
    # l'inverse — laisser passer sur la foi d'une seule paire favorable — et
    # affaiblirait le filtre au lieu de le renforcer.
    worst_overlap = max(
        (_path_overlap(a, b) for a in paths_a for b in paths_b),
        default=1.0,
    )
    return worst_overlap <= PATH_OVERLAP_CEILING
