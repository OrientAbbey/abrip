# Décision — suppression de `dev_cl5`

**Date :** 2026-11-17  
**Question :** peut-on supprimer directement `dev_cl5` (local et distant) ?  
**Éléments :** `comparaison-dev_cl-dev_cl5-backend.md`, `comparaison-dev_cl-dev_cl5-ux.md`, et le rapport initial `comparaison-dev_cl-dev_cl5.md`.

## Réponse courte

**Oui, sous réserve d'une seule décision backend.** Il n'y a aucun blocage UX, aucun blocage de performance, aucun blocage de sécurité et aucun contrat API dont dépendrait `dev_cl5`. Mais `dev_cl5` contient un module backend qui n'existe que dans lui et qui a une valeur réelle : `reference/history.py` (diff d'instantanés et classification de présence) avec les historiques ROA/IRR classés. Il faut soit le porter dans `dev_cl`, soit décider explicitement de l'écarter. Une fois ce point tranché, la suppression est sûre.

## Ce qui justifie la suppression

| Axe | Constat | Conséquence |
|---|---|---|
| Interface | `dev_cl` est nettement devant : sections adressables par URL, compteurs, pagination, brush, exports, focus clavier. Tous les apports utiles de `dev_cl5` ont déjà été portés. | Aucune régression UX à craindre. |
| Performance | `dev_cl` a le tri des partitions et les tables journalières, avec des mesures à 1–50 M lignes ; `dev_cl5` rescans `bgp_elements` et matérialise sans pagination ni plafond. | Aucun intérêt à conserver l'implémentation `dev_cl5`. |
| Sécurité | Profils proches ; `dev_cl` ajoute la protection du répertoire de démo, absente de `dev_cl5`. | `dev_cl5` n'est pas « plus sûr ». |
| Contrats API | 37 opérations documentées contre 33 ; `dev_cl5` renomme `neighbours` en `neighbors` et `route-history` en `route-object-history`, et retire des routes. | Pas de consommateur identifié de la variante `dev_cl5`. |
| Code commun | Le moteur de rejeu et `RelationshipIndex` sont identiques dans les deux branches. | Aucune exclusivité à préserver de ce côté. |

## La seule réserve

`dev_cl5/reference/history.py` (113 lignes) fournit `snapshot_dates()`, `diff_entities()` et `classify_presence()`, utilisés par les endpoints `/prefixes/changes`, `/neighbors` et les historiques ROA/IRR classés. Deux options :

1. **Porter le module et les endpoints associés dans `dev_cl` (recommandé).** Cela supprimerait la duplication de la règle New/Left/Unstable entre le SQL et le Python de `dev_cl`. Le port doit adapter les chemins d'API de `dev_cl` (`neighbours`, historiques imbriqués sous l'AS) et reprendre les tests `tests/test_reference.py` et `test_api.py` de `dev_cl5`.
2. **Écarter explicitement** cette fonctionnalité, en actant que `dev_cl` garde ses historiques bruts (`_history`) et sa classification actuelle. La suppression devient alors immédiate.

Le choix 2 est parfaitement défendable si aucun utilisateur ne demande les changements d'état ROA/IRR (`change`, `first_seen`, `last_seen`) ; le choix 1 est préférable si l'on veut récupérer l'abstraction la plus propre des deux branches.

## Points à traiter indépendamment

- `verify_api_key()` est du code mort dans **les deux** branches : jamais monté comme dépendance de routeur. Ce n'est pas une raison de garder `dev_cl5`, mais un correctif à planifier dans `dev_cl`.
- `GET /openapi.json` renvoie le HTML de repli SPA sur les serveurs locaux ; les schémas utilisés dans la comparaison ont été générés via `create_app().openapi()`. À clarifier si l'on veut exposer la documentation API.
- Les rapports de comparaison doivent être commités dans `dev_cl` avant suppression, afin de conserver le SHA `12fd25a` et la rationale.

## Suite proposée

1. Choisir l'option 1 ou 2 ci-dessus ; si option 1, créer un commit de port dédié dans `dev_cl`.
2. Commiter les trois documents de comparaison/décision dans `dev_cl`.
3. Supprimer `dev_cl5` local et distant, puis le worktree de revue détaché `abrip-dev_cl5-review`.
4. Garder `main` et `dev_cl` ; ne pas supprimer le jeu de données isolé `abrip-dev_cl5-data` tant que la décision n'est pas appliquée.

**Recommandation finale :** après port ou rejet explicite de `reference/history.py`, **supprimer `dev_cl5`**. Sa conservation n'apporterait qu'une branche non maintenue, des contrats concurrents et un risque de fusion accidentelle.
