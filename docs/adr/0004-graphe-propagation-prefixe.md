# ADR 0004 — Graphe de propagation d'un préfixe (nœuds d'AS)

**Statut :** mis en œuvre (27/09/2026) — voir « Mise en œuvre » en fin de
document pour les écarts avec la proposition initiale.
**Date :** 2026-09-25
**Portée :** `abrip.api`, frontend (page préfixe)

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

## Mise en œuvre

`GET /api/prefixes/{prefix}/propagation?asn=&from=&to=&targets=&max_paths=`
(`api/routers/topology.py::prefix_propagation`) et le composant frontend
`PropagationGraph.tsx`, posé sur la fiche préfixe (`Prefixes.tsx`).

Conforme à la proposition ci-dessus sur tous les points structurants :
graphe réduit (jamais de complétion vers un AS non observé), nœuds
étiquetés ASN + nom court avec info-bulle (ASN, nom complet, pays, chemins
limités à 10 par défaut + compteur des chemins non affichés), arêtes
colorées par relation CAIDA, troncature au premier `target` rencontré
depuis l'origine.

Deux précisions apportées en cours de route, sans changer la portée :

- **Disposition** : la proposition ne fixait pas de disposition. Choisie
  ici : en colonnes par distance BFS à l'origine (racines = AS sans arête
  entrante) plutôt qu'un algorithme de forces — plus lisible pour un graphe
  qui reste un arbre ou un DAG peu dense dans les cas observés, et pas
  besoin d'évaluer une bibliothèque de graphe supplémentaire pour une
  première version.
- **Poids des arêtes** : toujours absent de l'API comme prévu, mais
  `prefix_propagation` calcule déjà `edge_counts` en interne pour dédupliquer
  les arêtes — l'exposer un jour (ex. en épaisseur de trait) n'exigerait
  qu'un champ de réponse en plus, pas un nouveau calcul.


## Rejeu dans le temps (28/09/2026)

Demandé après la première version : dérouler la propagation sur une tranche
de temps plutôt que de n'en montrer que l'agrégat.

`GET /api/prefixes/{prefix}/propagation/replay?asn=&from=&to=&targets=&step=&max_frames=`
(`api/routers/topology.py`) et le mode « Rejouer » de `PropagationGraph.tsx`
(`PropagationReplay.tsx`). Le moteur est un module pur, `analytics/replay.py`.

- **État, pas événements.** Chaque tranche porte l'état du graphe à sa fin :
  l'état d'un pair (collecteur, adresse) est son dernier chemin annoncé, tant
  qu'il n'est pas retiré. Le graphe d'une tranche est l'union des chemins
  courants. Un retrait n'a pas de chemin donc pas d'origine : l'état est tenu
  pour toutes les origines, et le filtre `asn` n'est appliqué qu'à la
  construction de chaque tranche — filtrer avant conserverait à tort l'ancien
  chemin d'un pair passé d'une origine à une autre.
- **Disposition unique.** Nœuds et arêtes sont l'union de toutes les
  tranches ; le client calcule une seule disposition, les nœuds ne bougent pas
  pendant la lecture. Absent = grisé ; apparu ou disparu par rapport à la
  tranche précédente = vert / rouge pointillé (comparaison côté client).
- **Bornes.** Fenêtre limitée à 7 jours (`clamped`), pas élargi pour rester
  sous `max_frames` (`step_minutes` donne le pas réel), état amorcé 24 h avant
  le début.

Limite connue : un pair silencieux depuis plus de 24 h avant la fenêtre est
absent de la première tranche. En mode live, partir du dernier RIB avant la
fenêtre corrigerait cela ; non fait, la cadence des RIB varie selon le projet.

Le rejeu a révélé un défaut du jeu de démonstration : le MOAS planté déclarait
`duration_hours: 4` sans jamais y mettre fin, l'hijack restait donc actif
indéfiniment. Les pairs reviennent maintenant à l'origine légitime à la fin de
la durée (chemin déterministe, générateur aléatoire local pour ne pas décaler
le reste du jeu ; détection inchangée : 16 événements, mêmes détecteurs).
