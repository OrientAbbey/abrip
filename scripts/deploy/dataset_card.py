"""Carte du dataset Hugging Face : provenance et licence des sources."""

from __future__ import annotations

from pathlib import Path

CARTE_DATASET = """---
license: other
---
# ABRIP — données BGP dérivées

Jeu généré automatiquement par le pipeline ABRIP. Ce n'est pas une source
primaire : les conditions des sources d'origine s'appliquent.

## Sources et attribution

- **RouteViews** (University of Oregon) — données MRT sous **CC BY 4.0**.
  « This dataset utilizes data provided by RouteViews (www.routeviews.org).
  Use of this data is subject to the CC BY 4.0 license. » DOI : 10.7264/1y7v-2d90.
- **RIPE NCC RIS** — « The RIPE Routing Information Service (RIS) is a RIPE NCC
  service. » https://www.ripe.net/ris — conditions d'usage commercial décrites
  par le RIPE NCC.
- **CAIDA AS Relationships Dataset** — « The CAIDA AS Relationships Dataset,
  période utilisée, https://www.caida.org/catalog/datasets/as-relationships/ ».
  Usage régi par le CAIDA Acceptable Use Agreement ; redistribution à vérifier.
- **AFRINIC et autres RIR** (délégations), **RPKI**, **IRR**, **PeeringDB** et
  **bgp.tools** — selon les conditions propres à chaque source.

## Licence

Le tag `other` indique qu'ABRIP ne transmet aucun droit sur les données amont.
Toute redistribution doit respecter les conditions de chaque source. Les
fichiers calculés par ABRIP (métriques, événements, incidents, précalcul) sont
fournis sans garantie, pour la démonstration et la recherche.
"""


def ecrire_carte_dataset(data_dir: Path) -> None:
    (data_dir / "README.md").write_text(CARTE_DATASET, encoding="utf-8")
