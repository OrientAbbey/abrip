# Performances à grande échelle

La démonstration compte environ 27 000 éléments BGP. De vraies données en comptent
des millions. Ce document dit ce qui a été mesuré, comment, ce que cela a changé
dans le code, et ce qui ne passe pas encore à l'échelle.

## Méthode

- **Jeux synthétiques** de 1, 5, 10 et 50 millions de lignes `bgp_elements`
  (7 jours, 5 collecteurs, 20 000 préfixes avec une origine chacun, 3 à 4 AS par
  chemin, un préfixe « chaud » qui concentre 0,4 % des lignes), même schéma et même
  partitionnement que la couche curated. Scripts : `scripts/bench/`.
- **Machine** : 1 cœur, 4 Go de RAM, disque virtuel — de l'ordre d'un portable
  modeste, pas plus rapide. Mesures dans le processus (`TestClient`), donc sans
  réseau ni navigateur. Premier appel puis médiane de deux suivants.
- **Bruit** : un cœur partagé, comptez ±25 % sur chaque valeur.

```bash
python scripts/bench/gen_bgp_elements.py 1e7 /tmp/bench_1e7      # affiche préfixe chaud, moyen, ASN
python scripts/bench/run_endpoints.py /tmp/bench_1e7 <chaud> <moyen> <asn>
```

## Résultats (partitions triées, en secondes, appel suivant le premier)

| Endpoint | 1 M | 5 M | 10 M | 50 M |
|---|---|---|---|---|
| fiche d'un préfixe (chaud) | 0,26 | 0,47 | 0,48 | 0,56 |
| graphe de propagation (chaud) | 0,21 | 0,36 | 0,27 | 0,65 |
| rejeu de propagation, 7 jours (chaud) | 0,46 | 1,04 | 1,10 | 2,47 |
| fournisseurs amont (chaud) | 0,26 | 0,43 | 0,42 | 1,15 |
| graphe de propagation (préfixe moyen) | 0,14 | 0,13 | 0,17 | 0,14 |
| rejeu (préfixe moyen) | 0,24 | 0,27 | 0,39 | 0,49 |
| fiche d'un AS | 0,17 | 0,27 | 0,36 | 1,09 |
| préfixes d'un AS (tableau) | 0,06 | 0,08 | 0,06 | 0,06 |
| préfixes d'un AS (courbe) | 0,07 | 0,05 | 0,04 | 0,05 |
| voisins d'un AS (tableau) | 0,07 | 0,07 | 0,07 | 0,07 |
| voisins d'un AS (courbe) | 0,05 | 0,05 | 0,05 | 0,05 |
| liste des préfixes (25 lignes) | 0,10 | 0,13 | 0,10 | 0,11 |
| liste des AS (25 lignes) | n. m. | n. m. | 0,10 | 0,12 |
| mémoire maximale du processus | 162 Mo | 176 Mo | 191 Mo | 315 Mo |

Lecture : tout ce qui part d'**un préfixe** reste sous 3 secondes à 50 millions de
lignes (tri des partitions). Les endpoints **par AS** et la liste des préfixes sont
indépendants du volume (tables journalières, ci-dessous) ; avant elles, à 50 M de
lignes : préfixes d'un AS 3,3 s, voisins d'un AS 5,7 s, liste des préfixes 4,8 s.

## Ce qui a changé : partitions triées par (prefix, ts)

Presque toutes les requêtes filtrent sur le préfixe. Avec les lignes dans l'ordre
d'arrivée, chaque groupe de lignes Parquet contient un peu de tous les préfixes :
DuckDB doit tout lire. Triées, chaque groupe ne couvre qu'une plage étroite et les
statistiques min/max permettent de sauter presque tous les autres.

À 10 millions de lignes, avant → après : fiche d'un préfixe 1,1 → 0,3 s, graphe de
propagation 0,7 → 0,25 s, fournisseurs amont 1,7 → 0,4 s, rejeu 1,6 → 0,7 s. Les
endpoints par AS ne gagnent rien (la clé de tri est le préfixe).

- **À l'écriture** : `abrip etl curate` trie chaque partition (`etl.sort_partitions`,
  vrai par défaut ; `etl.row_group_size` 100 000 ; `etl.sort_memory_limit` 1 Go).
- **Installation existante** : `abrip etl compact` trie les partitions déjà écrites.
  À lancer une fois ; idempotent.
- **Mémoire** : le tri passe par DuckDB, qui déborde sur disque au-delà de la limite.
  Trier une partition de 7,1 millions de lignes (5 fragments) a pris 21 s, pour un
  pic d'environ 1,1 Go avec la limite à 1 Go. Le tri en mémoire de polars coûte
  environ 200 octets par ligne, soit 1,4 Go pour 7 millions de lignes.
- **Rien d'autre ne change** : mêmes lignes, mêmes événements, mêmes incidents
  (test `test_demo_identique_triee_ou_non`).

### Un piège rencontré : `collector` en texte

DuckDB n'écrit pas de `Categorical`, donc `collector` est du texte dans
`bgp_elements`. Le laisser en `Categorical` dans `rib_snapshots` a rendu **muette**
la détection de chute de visibilité : le détecteur joint les deux tables sur
`collector`, et polars ne signale pas l'erreur quand les types diffèrent, il rend une
jointure vide (rappel de la démo tombé à 0,8). Les deux tables sont maintenant en
texte et un test garde la cohérence. Conséquence pour une installation existante :
polars refuse de lire ensemble d'anciennes partitions (`Categorical`) et de
nouvelles (texte) — `abrip etl compact` les uniformise.

## Tables journalières précalculées

Les endpoints par AS n'ont pas de clé de tri qui les aide : trier par préfixe
n'accélère rien quand on cherche une origine ou un voisin. Ce qu'ils calculent tient
pourtant dans de petites tables, une par jour (`analytics/daily.py`) :

| Table | Contenu | Sert à |
|---|---|---|
| `daily_prefix_origin` | par jour, préfixe et origine : annonces, retraits, RIB | tableau et courbe des préfixes d'un AS, liste des préfixes, bornes de dates |
| `daily_adjacency` | par jour, version IP et AS : ses voisins sur les chemins annoncés | tableau et courbe des voisins d'un AS |

- **Calcul** : fait par `abrip analytics compute` (donc par `abrip demo bootstrap`),
  jour par jour ; une plage remplace ses jours et laisse les autres. Sur 50 M de lignes :
  55 s, 252 Mo de pic, 0,9 Mo sur disque.
- **Exactitude** : l'API ne s'en sert que si la table couvre tous les jours demandés et
  n'est pas plus ancienne que les partitions curées ; sinon elle retombe sur le calcul
  direct, plus lent mais identique. Les 300 comparaisons des tests
  (`tests/test_tables_journalieres.py` : 9 AS × 4 plages × versions IP × statuts,
  voisins par type, liste des préfixes) donnent exactement les mêmes réponses par les
  deux chemins. Après `abrip etl compact` ou une nouvelle curation, les partitions curées
  sont plus récentes : relancer `abrip analytics compute` pour retrouver la vitesse.
- **Un changement de sémantique** : ces endpoints raisonnent désormais en **jours UTC
  entiers**. Une plage qui commence à 13 h inclut toute la journée (avant, elle coupait
  la première journée ; le classement New/Left/Unstable étant déjà fait par jour, seuls
  des appels avec heures étaient concernés — l'interface n'en fait pas).
- **Départage** : la liste des préfixes trie par activité puis par préfixe, pour qu'une
  égalité ne change pas de page d'un appel à l'autre.

## Autres changements de cette passe

- **`/prefixes/{p}/upstreams`** : un seul parcours des données au lieu de deux
  (bornes, puis agrégat). Les pairs distincts par heure sont ramenés par la requête,
  la tranche (6 h, 24 h…) est calculée en Python ; un test vérifie l'équivalence
  exacte avec `time_bucket` pour six pas.
- **Rejeu** : la liste des chemins distincts est renvoyée une fois, et chaque tranche
  ne porte que des indices ; omise au-delà de 3 000 chemins distincts ou 400 000
  références (le client se rabat alors sur les liens directs).

## Transport HTTP

- **Compression gzip** sur les réponses de plus de 1 024 octets, quelle que soit
  la route (API et documentation). En dessous, la compression coûte plus qu'elle
  n'économise. Le client n'a qu'à envoyer `Accept-Encoding: gzip`.
- **ETag faible** (SHA-256 du corps JSON) et `Cache-Control: private, no-cache` :
  le navigateur revalide à chaque appel et reçoit un **304 sans corps** quand rien
  n'a changé. Le gain porte sur les octets transférés, pas sur le calcul serveur —
  les requêtes rejouent normalement. `/api/health` est volontairement `no-store` :
  il porte un horodatage de génération et sert à la supervision.
- **Connexions DuckDB** : une par thread de travail, réutilisée entre les requêtes
  (`threading.local`). Une connexion DuckDB n'est pas partageable entre threads ;
  le thread-local évite un verrou global tout en conservant le catalogue entre
  deux requêtes d'un même appel (une fiche AS en enchaîne plusieurs).
- Ces changements n'ont pas été re-mesurés sur les jeux de 50 M de lignes : les
  temps du tableau ci-dessus restent ceux du calcul seul, sans transport.

## Ce qui ne passe pas encore à l'échelle

| Point | Constat à 50 M de lignes | Piste |
|---|---|---|
| Fiche d'un AS | 1,1 s (`updates`, premier et dernier instant, pairs **distincts** : ce dernier ne se déduit pas d'agrégats journaliers) | une table (jour, préfixe, origine, pair), nettement plus volumineuse |
| Vue d'ensemble, premier appel | 3,6 s, puis mis en cache | idem |
| Rejeu d'un préfixe très bavard | 2,5 s | agréger les tranches côté DuckDB |
| Calcul des tables et des métriques | non mesuré sur de vrais MRT | à mesurer sur ton poste |

## Concurrence

Le script `scripts/bench/run_charge.py` mesure un mélange de routes avec un
nombre configurable d'utilisateurs simultanés. Le service doit tourner :

```bash
uv run --locked abrip api serve --port 8010
uv run --locked python scripts/bench/run_charge.py --url http://127.0.0.1:8010 \
    --users 10 --duration 30 --json /tmp/charge.json
```

Il découvre un préfixe et un ASN au démarrage, préchauffe les index, puis
envoie les requêtes sans cache client (httpx ne réutilise pas les ETag). Le JSON
en sortie permet de comparer deux exécutions. Sur le jeu de démonstration, en
local, une seule instance uvicorn :

| Utilisateurs | Requêtes / 10 s | p50 global | p95 global |
|---|---|---|---|
| 1 | 22 | 0,38 s | 1,25 s |
| 5 | 43 | 1,07 s | 4,12 s |
| 10 | 43 | 1,22 s | 9,39 s |

Avec `--workers 4` sur la même machine, 10 utilisateurs pendant 15 s : 54
requêtes (3,6 req/s), p50 2,33 s, p95 8,21 s. Une première mesure à 10 s
n'avait donné que 2,1 req/s, le temps que chaque worker construise ses index.
Autrement dit : **pas de gain de débit sur un cœur partagé**, et un p95 du même
ordre. La voie de montée reste le précalcul des endpoints les plus demandés,
pas l'empilement de processus sur une machine sans cœurs disponibles.

Le débit plafonne vers 4 requêtes/s et la latence p95 explose avec la
concurrence : les endpoints analytiques utilisent DuckDB et la machine de mesure
n'a qu'un cœur. Ces chiffres ne sont pas transposables à une machine ou un jeu
de données différents : c'est la procédure qui est reproductible, pas la valeur
absolue. Avec plusieurs workers, `/api/metrics` ne couvre qu'un processus (voir
`docs/deploiement.md`).

## Limites de ces mesures

- **Sept jours de données seulement.** Les jeux synthétiques couvrent une semaine. Une
  rétention plus longue multiplie le volume parcouru par les requêtes sans filtre de
  date ; un essai de prédicat sur la partition `date` n'a rien gagné sur ces 7 jours et
  n'a pas été étendu plus loin.

- Données **synthétiques** : chemins courts et uniformes, un préfixe = une origine,
  pas de rafales. Des données réelles seront plus irrégulières, et les chemins plus
  longs.
- **Mesures de concurrence** : voir la section « Concurrence » ci-dessus ; le test de charge n'est pas joué en CI (il dépend d'une machine et d'une durée choisies).
- Pas de mesure sur **disque lent** ni sur ton portable : à refaire sur place avec
  `scripts/bench/`.
- Les 50 M de lignes pèsent 673 Mo en Parquet ; la couche brute (fichiers MRT) et le
  temps de la curation (lecture des MRT) ne sont pas mesurés ici.
