# ADR 0004 — Graphe de propagation d'un préfixe (nœuds d'AS), pour plus tard

**Statut :** proposé — non implémenté
**Date :** 2026-09-25
**Portée :** `abrip.api`, frontend (page ASN / page préfixe)

## Contexte

Le point 6 de la refonte de la page ASN (New/Left/Unstable, voisins BGP par
type, page pays — voir `docs/revue-2026-09-24.md` et le fil de discussion du
25/09/2026) s'inspire de [radar.qrator.net](https://radar.qrator.net/). Cette
même source propose, pour un ASN et un préfixe donnés, un
[graphe de propagation](https://radar.qrator.net/as/36912/graph?prefix=102.244.190.0/23&targets=174,701,1299,2914,3257,3320,3356,3491,5511,6453,6461,6762,6830,6939,7018) :
les chemins AS-path observés vers ce préfixe, agrégés en un graphe de nœuds
plutôt qu'une liste de chemins bruts — bien plus lisible dès qu'un préfixe
est vu par plusieurs dizaines de collecteurs.

Cette fonctionnalité n'est **pas implémentée** dans ce lot : elle est notée
ici pour ne pas la perdre, et pour que sa conception soit tranchée avant
qu'elle ne devienne urgente. Rien dans ce document n'engage de code.

## Décision (portée envisagée)

Un graphe **réduit, non étendu** : uniquement les AS effectivement présents
dans au moins un AS-path observé pour le préfixe et la fenêtre demandés — pas
de complétion vers des AS voisins non observés. C'est la différence
structurante avec un graphe de topologie complet, beaucoup plus coûteux à
calculer et à lire.

**Nœuds.** Un nœud par AS distinct apparaissant dans au moins un chemin.
- Étiquette : `ASxxxx` + nom court (voir point 5, `ref_as_org.org_name`,
  tronqué si besoin — pas de nouvelle source de données à prévoir).
- Info-bulle (au survol/clic) : numéro d'AS, nom d'organisation complet,
  pays, et la liste des chemins qui traversent ce nœud — limitée à 10 par
  défaut (configurable), avec le nombre de chemins non affichés en complément
  (« + 7 autres chemins »). Cette limite est nécessaire dès qu'un AS de
  transit majeur (174, 3356, 6939...) est un point de passage commun à la
  plupart des chemins.

**Arêtes.** Une arête par lien AS-A → AS-B observé dans au moins un chemin,
colorée selon la relation CAIDA (`reference/relationships.py::RelationshipIndex`,
déjà utilisée par la Phase 2 du point 6) : fournisseur, client, peering, ou
inconnue (relation non trouvée dans `ref_as_rel`). Pas de poids sur l'arête
dans une première version — le nombre de chemins qui l'empruntent pourrait
s'ajouter plus tard (encodé en épaisseur de trait) sans changer la structure
du graphe.

**Cible.** Un ASN d'origine (celui dont on trace la propagation) et une liste
de nœuds `targets` optionnelle (les grands transitaires, par défaut, comme
dans l'exemple qrator.net ci-dessus) — au-delà de la cible, un chemin observé
n'apporte plus d'information nouvelle et peut être tronqué.

**API envisagée.** `GET /api/prefixes/{prefix}/propagation?asn=&start=&end=&targets=`,
retournant `{nodes: [...], edges: [...]}` calculé à partir de
`curated_elements`/`curated_rib` (`as_path_dedup`, déjà stocké — voir
`RIB_SNAPSHOT_SCHEMA`/`ELEMENTS_SCHEMA` dans `models.py`) : aucune nouvelle
donnée à collecter, uniquement une agrégation de ce qui existe déjà.

**Frontend envisagé.** Rendu via SVG/Canvas (pas de nouvelle dépendance de
graphe de nœuds à évaluer avant que la fonctionnalité ne soit engagée) ; nœud
cliquable vers la fiche ASN correspondante.

## Conséquences

**Bénéfices.** Complète naturellement l'onglet Voisins BGP du point 6 (Phase
2) : ce dernier montre les voisins directs d'un AS, ce graphe montrerait la
propagation de bout en bout d'un préfixe précis. Aucune nouvelle collecte de
donnée requise — uniquement de l'agrégation.

**Coûts.** L'agrégation de chemins en graphe (dédoublonnage des arêtes,
calcul de la liste de chemins par nœud, application de la limite d'affichage)
est un calcul non trivial, à isoler dans son propre module plutôt que dans le
routeur API, pour rester testable indépendamment du rendu. Le rendu d'un
graphe de nœuds interactif (disposition automatique, évitement de
chevauchement) est également non trivial côté frontend et mérite son propre
lot, séparé de la Phase 2 du point 6 dont il réutilise les couleurs de
relation.

## Alternatives écartées

**Graphe étendu** (complétion vers les voisins connus de chaque AS du
chemin, même non observés pour ce préfixe). Écartée pour une première
version : plus coûteuse à calculer, et mélange dans un même graphe ce qui a
été observé et ce qui est seulement inféré — une distinction que le reste du
projet maintient soigneusement (voir ADR 0003).

**Liste de chemins bruts, sans graphe.** C'est l'existant (`AsnDetail`
n'affiche aujourd'hui aucun chemin agrégé). Écartée comme solution durable
dès qu'un préfixe est vu par une dizaine de collecteurs ou plus : la
redondance entre chemins partageant les mêmes AS de transit rend une liste
brute difficile à parcourir, ce que le graphe résout par construction.
