# ADR 0001 — Stratégie de lecture des archives MRT

**Statut :** accepté
**Date :** 2026-09
**Portée :** `abrip.etl.mrt_parser`, `abrip.ingestion`

## Contexte

Les archives BGP de RouteViews et RIPE RIS sont distribuées au format MRT (RFC 6396), compressé en `.bz2` ou `.gz`. Quatre bibliothèques permettent de les lire en Python, et aucune n'est satisfaisante dans l'absolu :

| Bibliothèque | Vitesse | Installation | Problème |
|---|---|---|---|
| `bgpkit-parser` | très rapide (Rust) | roue précompilée, sinon chaîne Rust complète | pas de roue pour toutes les plateformes |
| `pybgpstream` | rapide | exige `libbgpstream` compilée localement | échoue sur une machine sans outils de build |
| `mrtparse` | lent (Python pur) | `pip install`, rien d'autre | inutilisable sur de gros volumes |
| générateur synthétique | immédiat | aucune | ne lit pas de vraies données |

La plateforme doit tourner sur un poste de développement modeste, sans droits d'administration garantis, tout en restant capable de traiter des volumes réels quand l'environnement le permet. Le premier réflexe — choisir la plus rapide et en faire une dépendance dure — rend le projet indémarrable partout où la roue précompilée manque. Le second réflexe — choisir la plus portable — condamne le traitement de volumes réels.

## Décision

Définir une interface `MRTParser` unique, et quatre implémentations classées par ordre de préférence décroissante. La fonction `get_parser("auto")` sélectionne la première disponible à l'exécution et journalise un avertissement quand elle n'obtient pas le premier choix.

```python
class MRTParser(abc.ABC):
    @abc.abstractmethod
    def available(self) -> bool: ...
    @abc.abstractmethod
    def parse(self, path: Path) -> Iterator[dict]: ...
```

Ordre de préférence : `bgpkit` → `mrtparse` → `pybgpstream` → `synthetic`.

Aucun autre module n'importe une bibliothèque de parsing. Le reste du code manipule des dictionnaires normalisés et ignore quelle implémentation les a produits.

Les parseurs réels sont déclarés en extras optionnels dans `pyproject.toml` (`.[bgpkit]`, `.[mrt]`), jamais en dépendance obligatoire.

## Conséquences

**Bénéfices.** Le projet s'installe et démarre partout, y compris sur une machine sans compilateur. Le générateur synthétique n'est pas un artifice de démonstration : c'est le dernier maillon d'une chaîne de repli cohérente, et il fournit la vérité terrain du test de non-régression. Changer de bibliothèque, ou en ajouter une cinquième, ne touche qu'un fichier.

**Coûts.** Une couche d'indirection supplémentaire à maintenir. Les formats de sortie des quatre bibliothèques diffèrent, et la normalisation vers un dictionnaire commun doit être testée pour chacune — sinon le repli produit des données subtilement différentes, ce qui est pire qu'une absence de repli.

**Risque assumé.** Un repli silencieux vers `synthetic` en production produirait des données inventées. Le parseur actif est donc journalisé à chaque exécution, exposé par `abrip status`, et un repli au-delà du premier choix émet un `WARNING`.

## Alternatives écartées

**Dépendance unique sur `bgpkit-parser`.** Écartée : rend l'installation impossible sur plusieurs plateformes cibles, pour un gain de vitesse qui n'a d'intérêt qu'au-delà d'un volume que le projet n'atteint pas en développement.

**Conversion préalable en JSON par un outil externe** (`bgpdump`, `bgpreader`). Écartée : déplace le problème d'installation vers un binaire système, et fait perdre le contrôle sur la gestion mémoire du flux.

**Détection à l'installation plutôt qu'à l'exécution.** Écartée : l'environnement peut changer entre l'installation et l'exécution, notamment en conteneur.
