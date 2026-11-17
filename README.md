# ABRIP — African BGP Routing Intelligence Platform

Plateforme d'observation du routage inter-domaines africain : elle collecte les archives BGP publiques, les recoupe avec les référentiels d'allocation et d'autorisation, calcule des indicateurs de visibilité et de dépendance au transit, et signale les anomalies **en expliquant pourquoi**.

Le projet répond à une question simple et peu outillée : *quand un préfixe africain devient injoignable ou se met à osciller, que voit-on depuis les collecteurs, et qu'est-ce qui explique ce qu'on voit ?*

---

## Démarrage en cinq minutes

Aucune donnée à télécharger : un générateur produit un jeu de démonstration avec des anomalies plantées, ce qui permet de voir la plateforme fonctionner avant de la brancher sur les archives réelles.

```bash
# 1. Installation (Python 3.11+)
pip install -e ".[dev]"

# 2. Jeu de démonstration : 7 jours de données, référentiels, métriques, détection
abrip demo bootstrap

# 3. Vérification : les anomalies plantées ont-elles été retrouvées ?
abrip demo verify

# 4. Interface web sur http://127.0.0.1:8000
abrip api serve
```

Le frontend compilé est servi par l'API. Pour le développer :

```bash
cd frontend && npm install && npm run dev   # http://127.0.0.1:5173
```

---

## Ce que la plateforme produit

Sur le jeu de démonstration (7 jours, 5 collecteurs, 19 préfixes, 12 AS d'origine dont quelques AS fictifs dédiés aux exemples de l'interface) :

| Sortie | Volume |
|---|---|
| Éléments BGP curés | 27 577 |
| Lignes de snapshots RIB | 4 904 |
| Points de métriques | 27 625 |
| Événements détectés | 16 |
| Incidents corrélés | 8 |
| Rappel sur la vérité terrain | 5/5 |

Les cinq anomalies plantées sont toutes retrouvées, et trois d'entre elles sont confirmées par plusieurs détecteurs indépendants — c'est la corrélation qui distingue un incident d'un signal isolé :

| Anomalie plantée | Détecteurs qui se déclenchent |
|---|---|
| Détournement MOAS sur `197.155.64.0/22` | pic d'instabilité + MOAS + invalide RPKI |
| Sous-préfixe sur `197.248.160.0/20` | invalide RPKI + sous-préfixe |
| Fuite de routes sur `102.64.0.0/12` | pic d'instabilité + valley-free |
| Instabilité sur `196.60.0.0/18` | pic d'instabilité |
| Chute de visibilité sur `197.32.0.0/13` | chute de visibilité |

---

## Interface web

Servie par l'API sur http://127.0.0.1:8000. Un sélecteur de période (champs de date, boutons 7 j / 30 j / Tout) pilote tous les graphes et tableaux d'une page ; les numéros d'AS s'affichent avec leur nom court quand le référentiel AS2Org le connaît (« AS174 · COGENT-174 »). Les termes techniques (HHI, dépendance, visibilité…) sont soulignés en pointillé : l'infobulle donne la définition, et la page « À propos » en rassemble le glossaire.

| Page | Contenu |
|---|---|
| Vue d'ensemble | indicateurs, préfixes les plus instables, répartition par détecteur, visibilité dans le temps |
| Événements | liste filtrable ; la fiche d'un événement montre les preuves qui le motivent |
| Systèmes autonomes | fiche d'un AS en cinq sections à onglets (une à la fois, la période analysée reste commune ; la section est dans l'adresse, `?section=neighbours`) : **Préfixes** (courbe du nombre de préfixes, onglets Tous / IPv4 / IPv6 ; tableau Actif, Préfixe, RPKI ROA, Route Object, Historique, avec onglets Tous / New / Left / Unstable ; une poignée sous la courbe restreint la période et le tableau ; « Périodes » ouvre l'**historique d'annonce** du préfixe, période par période, trous compris), **Voisins BGP** (fournisseurs / clients / peerings / non déterminé, graphe et tableau filtrés par le même onglet, plus les onglets Tous / New / Left / Unstable appliqués aux voisins avec la même règle que les préfixes ; un clic sur la frise ouvre l'**historique de la relation** en IPv4 et en IPv6), **Transit** (dépendance, HHI), **Activité** (annonces et retraits), **Événements** |
| Préfixes | fiche d'un préfixe, origines, ROA, chemins, et **graphe de propagation** réduit aux AS observés — voir l'[ADR 0004](docs/adr/0004-graphe-propagation-prefixe.md). Mode « Instantané » (période de la page) et mode « Rejouer » (tranche horaire de 7 jours au plus : lecture, pas à pas, saut d'un changement à l'autre, repères des événements détectés, liens permanents en pointillé, écart depuis le début). Liens colorés selon la relation, épaisseur = observations ; survol ou clic sur un AS : seuls ses chemins restent en relief ; statut RPKI de chaque origine (ROA ✓ / ✗) et lien en magenta quand un chemin viole le modèle valley-free (fuite probable, même verdict que le détecteur) ; seuil « chemins vus au moins N fois » ; repli des AS hors Afrique (les origines restent visibles) ; export SVG, PNG et CSV des chemins ; la vue entière (filtres, AS épinglé, tranche) est dans l'adresse (`g_*`) et la fiche d'un événement y renvoie. Sous le graphe, **fournisseurs amont dans le temps** : barres empilées des pairs qui voient le préfixe via chaque fournisseur (un basculement de fournisseur se lit comme une barre qui en remplace une autre) |
| Pays | indicateurs par pays ; la fiche `/countries/:iso2` liste les AS et leurs relations (fournisseurs, clients, peerings), puis les mêmes panneaux **Préfixes** et **Voisins BGP** que la page d'un AS, agrégés sur tous les AS du pays (une colonne indique l'AS concerné ; les historiques s'ouvrent par ligne) |

Les liens « RPKI ROA » et « Route Object » d'un tableau de préfixes ouvrent l'historique daté (origine, trust anchor ou source, longueur maximale, première et dernière observation, concordance avec l'origine observée). L'interface est en français ; seuls restent en anglais les termes que la page définit en infobulle (New, Left, Unstable) et les noms propres (RPKI ROA, Route Object, Trust Anchor, IPv4, IPv6). Les éléments cliquables du graphe de propagation ont un indicateur de focus clavier visible.

---

## Configuration et journaux

Cascade : valeurs par défaut → `configs/*.yaml` → variables d'environnement `ABRIP_*` (délimiteur imbriqué `__`) ; l'environnement l'emporte. Ce qui était figé dans le code se règle sans le modifier :

| Réglage | Où | Exemple de surcharge |
|---|---|---|
| Racine d'archive et cadence de publication par projet | `settings.yaml` : `ingestion.archive_root`, `ingestion.cadence` | `ABRIP_INGESTION__ARCHIVE_ROOT='{"routeviews": "https://miroir.example/rv", ...}'` |
| URL RIS Live, listes anycast | `ingestion.ris_live_url`, `reference.anycast_v4_url` / `anycast_v6_url` | `ABRIP_INGESTION__RIS_LIVE_URL=...` |
| Tri des partitions `bgp_elements` (requêtes par préfixe 3 à 4 fois plus rapides à 10 M de lignes) | `etl.sort_partitions`, `etl.row_group_size`, `etl.sort_memory_limit` | `ABRIP_ETL__SORT_PARTITIONS=false` |
| Seuils IODA / RIPE Atlas | `enrichment.ioda_outage_threshold`, `enrichment.atlas_connected_floor` | `ABRIP_ENRICHMENT__IODA_OUTAGE_THRESHOLD=0.8` |
| Recouvrement MOAS toléré pour l'anycast | `detection.yaml` : `detectors.moas.anycast_overlap_ceiling` | modifier le fichier |

Journal : sur la console, et dans `data/logs/abrip.log` (JSON, une ligne par message, rotation à 10 Mo, 5 sauvegardes ; `ABRIP_LOG_FILE`, `ABRIP_LOG_MAX_BYTES`, `ABRIP_LOG_BACKUP_COUNT`). Un échec réseau journalise le type d'erreur, la méthode, l'URL et le code de statut :

```bash
jq 'select(.status_code != null) | {ts, message, method, url, status_code}' data/logs/abrip.log
```

Le jeu de démonstration porte des AS fictifs : `abrip demo bootstrap` n'interroge ni IODA, ni RIPE Atlas, ni Cloudflare Radar.

**Ne mélangez pas la démonstration et de vraies données dans un même répertoire.** Les préfixes de la démo sont de vrais préfixes africains : une synchronisation réelle y ajoute des objets route (RADB…) pour des préfixes que la démo croit sans objet, et ses tests d'API échouent sans qu'on comprenne pourquoi. Le bootstrap écrit donc un marqueur (`.abrip-demo.json`) et la liste de ses fichiers :

```bash
abrip demo check                 # dit si data/ est exactement la démo ; sinon, liste les fichiers étrangers
abrip demo bootstrap --force     # écrase un répertoire qui n'est pas (que) la démo
ABRIP_DATA_DIR=./data-reel abrip reference sync   # vraies données : un dossier à part
```

Sans `--force`, le bootstrap refuse de passer sur un répertoire contenant autre chose que la démo (il réécrit les référentiels et supprime leurs anciens instantanés). Les tests qui lisent la démo s'ignorent, avec la raison, quand le répertoire n'est pas intact. Après une mise à jour depuis une version sans marqueur, relancer une fois `abrip demo bootstrap --force`.

---

## Architecture

```
Archives MRT ──┐
RIS Live ──────┼──► raw/ ──► curated/ ──► analytics/ ──► API ──► Interface web
Référentiels ──┘   (brut     (éléments    (métriques      (lecture   (React)
                   immuable)  normalisés)  + événements)   seule)
```

Trois couches, une règle par couche :

- **`raw/`** — les fichiers sont téléchargés tels quels et ne sont jamais modifiés. Un fichier déjà ingéré n'est pas retéléchargé : le catalogue DuckDB garde son empreinte SHA-256.
- **`curated/`** — normalisation en Parquet partitionné par jour et par collecteur. Rejouer une journée supprime puis réécrit sa partition : le résultat est identique quel que soit le nombre d'exécutions.
- **`analytics/`** — métriques et événements. Les identifiants d'événements sont des UUID déterministes calculés sur (détecteur, préfixe, AS impliqués, fenêtre) : rejouer la détection ne crée pas de doublons.

### Organisation du code

```
src/abrip/
├── config.py            Configuration en cascade : défauts → YAML → variables d'environnement
├── models.py            Modèles Pydantic et schémas Polars — le contrat interne
├── ingestion/           Broker BGPKIT, téléchargement résumable, flux RIS Live
├── reference/           AFRINIC/RIR, RPKI, AS2Org, IRR, PeeringDB, relations CAIDA, anycast
├── etl/                 Normalisation et curation, parseurs MRT et PCH à interface unique
├── analytics/           Churn, visibilité, chemins, transit, couverture, agrégats pays
├── anomaly/             Sept détecteurs, moteur de corrélation
├── enrichment/          Confirmation par le plan de données (IODA, RIPE Atlas, Cloudflare Radar)
├── storage/             Catalogue DuckDB, écriture Parquet à mémoire bornée
├── api/                 FastAPI en lecture seule
└── demo/                Générateur avec vérité terrain
frontend/                React + Vite + TypeScript + Recharts
```

---

## Choix techniques et pourquoi

**Polars plutôt que pandas.** Le mode *streaming* permet de traiter des fichiers plus gros que la mémoire disponible. Sur une machine à 8 Go, c'est la différence entre un pipeline qui tourne et un pipeline qui meurt par `MemoryError`. Le pic mesuré sur le pipeline quotidien reste sous 1,5 Go.

**Parquet plutôt qu'une base de données.** Pas de serveur à administrer, compression columnaire efficace, et DuckDB lit directement les fichiers en SQL. Le partitionnement par jour permet à l'API de ne lire que les fragments nécessaires.

**DuckDB en lecture seule côté API.** L'API ne calcule rien : elle interroge. La production des données passe exclusivement par la ligne de commande. Cette séparation rend l'API triviale à mettre en cache et impossible à corrompre par une requête.

**Un parseur MRT derrière une interface unique.** Quatre implémentations possibles (`bgpkit-parser`, `mrtparse`, `pybgpstream`, générateur synthétique) sont classées par ordre de préférence et sélectionnées automatiquement selon ce qui est installé. Le reste du code ne sait pas laquelle est active. C'est ce qui permet au projet de démarrer sur une machine sans dépendance native compilée.

**Recharts pour les graphiques.** Composants React déclaratifs, bien maintenus, et le découpage du bundle isole la bibliothèque dans son propre fragment. Total transféré : 240 Ko compressés, sous le budget de 250 Ko fixé au cahier des charges.

**Le score z robuste plutôt que l'écart-type.** Le churn BGP est très asymétrique : un seul pic gonfle l'écart-type au point de masquer les pics suivants. La médiane et l'écart absolu médian restent calés sur le bruit de fond.

**Explicabilité avant sophistication.** Aucun modèle appris. Chaque événement porte les observations qui l'ont déclenché, et la page de détail les affiche. Un détecteur qu'on ne peut pas expliquer à un ingénieur réseau ne sert à rien.

---

## Les sept détecteurs

| Détecteur | Signal | Nature de la preuve |
|---|---|---|
| MOAS | plusieurs AS d'origine pour un même préfixe | heuristique, renforcée par RPKI |
| Sous-préfixe | bloc plus spécifique annoncé par un autre AS | heuristique, renforcée par RPKI |
| Invalide RPKI | contredit un ROA publié | **cryptographique** |
| Valley-free | le chemin remonte après être redescendu | relations CAIDA (inférées) |
| Pic d'instabilité | volume très supérieur à la référence | statistique (z robuste) |
| Chute de visibilité | disparition d'une part des points de vue | observationnelle |
| Bogon | préfixe réservé ou AS privé annoncé | déterministe |

Chacun produit un score (0 à 1), une confiance fondée sur le nombre de points de vue concordants, et ses preuves. Le moteur regroupe ensuite les événements qui pointent le même préfixe dans la même fenêtre.

---

## Les collecteurs

Le cahier des charges initial citait `rrc00` et `rrc11` comme collecteurs africains. C'est faux : `rrc11` est à New York et `rrc00` est un collecteur multihop à Amsterdam. Les points d'observation réellement hébergés en Afrique sont :

| Collecteur | Projet | Lieu | Rôle |
|---|---|---|---|
| `route-views.napafrica` | RouteViews | Johannesburg | local |
| `route-views.jinx` | RouteViews | Johannesburg | local |
| `route-views.kixp` | RouteViews | Nairobi | local |
| `route-views.gixa` | RouteViews | Accra | local |
| `rrc19` | RIPE RIS | Johannesburg | local |
| `rrc00`, `route-views2` | — | Amsterdam, Eugene | **vue extérieure** |

Les deux derniers sont conservés délibérément : l'écart entre la vue africaine et la vue extérieure révèle les propagations asymétriques, qu'aucune des deux vues ne montre isolément.

**Couverture élargie (L2), désactivés par défaut le temps de mesurer leur volume réel :**

| Collecteur | Projet | Lieu | Rôle |
|---|---|---|---|
| `route-views.linx`, `route-views.amsix`, `rrc01` | RouteViews / RIPE RIS | Londres, Amsterdam | vue de couverture (IXP accueillant des peers africains) |
| `route-collector.jnb1.pch.net`, `route-collector.lgs1.pch.net` | PCH (relevés texte, pas MRT) | Johannesburg, Lagos | local |

---

## Commandes

```bash
abrip status                                   # état des données et couverture
abrip ingest broker --from 2026-08-01 --to 2026-08-07
abrip reference sync --sources afrinic,rpki,caida,as2org,irr,peeringdb,anycast
abrip etl curate --from 2026-08-01 --to 2026-08-07   # écrit bgp_elements trié par (prefix, ts)
abrip analytics compute --from 2026-08-01 --to 2026-08-07   # métriques + tables journalières (réponses rapides par AS)
abrip detect run --from 2026-08-01 --to 2026-08-07
abrip detect watch --minutes 5 --iterations 12  # détection continue sur RIS Live (L7)
abrip pipeline --date 2026-08-01                # tout l'enchaînement pour un jour
abrip api serve --port 8000
```

Toute commande supporte `--dry-run` là où elle télécharge ou écrit, et journalise en JSON pour être exploitable en production.

---

## Tests

```bash
make test        # 728 tests (245 + 483 ignorés sur une installation sans données)
make lint        # ruff
make typecheck   # mypy
```

Le test qui compte est `test_rappel_sur_verite_terrain` : il exige que toutes les anomalies plantées soient retrouvées. Un réglage de seuil qui « améliore les chiffres » en cassant la détection est arrêté là.

Les tests d'API et de non-régression sont ignorés proprement — et non en échec — si le pipeline n'a pas encore tourné : la suite reste verte sur une installation fraîche (`/api/health` y répond `degraded`, pas `ok`).

---

## Limites, et ce qu'on en a fait

Ces limites tiennent à la nature des données BGP. Le détail — modules, tests, effet mesuré sur le jeu de démonstration — est dans [docs/limites-et-remediations.md](docs/limites-et-remediations.md). Six des sept sont **implémentées et vérifiées** dans ce dépôt, pas seulement proposées :

| Limite | Remédiation | Statut |
|---|---|---|
| BGP décrit le plan de contrôle, pas le trafic | confirmation par IODA, RIPE Atlas et Cloudflare Radar ; rétrogradation automatique d'un `critical` contredit | ✅ implémenté (`enrichment/dataplane.py`, 17 tests) |
| La vue est partielle | métrique de couverture par pays jointe aux indicateurs ; ingestion PCH réelle (parseur texte à largeur fixe) ; collecteurs européens déclarés | ✅ implémenté (`analytics/metrics.py`, `etl/pch_parser.py`, 9 tests) |
| Les relations CAIDA sont inférées, pas contractuelles | corroboration par PeeringDB (co-présence IXP) et l'IRR (AS-SET) ; `critical` plafonné sans au moins deux sources | ✅ implémenté (`reference/peeringdb.py`, 10 tests) |
| `not-found` est majoritaire en RPKI dans la zone AFRINIC | repli sur les objets `route` IRR (RIPE DB REST) ; taux de couverture ROA publié par pays | ✅ implémenté (`reference/irr.py`, 15 tests) |
| Une anomalie n'est pas une attaque | boucle de qualification (`abrip detect label`) rendant la précision mesurable | proposée, non implémentée |
| Faux positifs MOAS dus à l'anycast et au multihoming | même organisation (AS2Org réel), stabilité historique, catalogue anycast public (bgp.tools, données réelles) | ✅ implémenté (`reference/as2org.py`, `reference/anycast.py`, 28 tests) |
| Un collecteur indisponible ressemble à une chute de visibilité ; granularité des archives MRT | exclusion des collecteurs inactifs ; détection en continu sur RIS Live (`abrip detect watch`) | ✅ implémenté (`anomaly/detectors.py`, `etl/curate.py`, 4 tests) |

Rappel sur la vérité terrain après l'ensemble de ces remédiations : toujours **5/5**, 16 événements et 8 incidents inchangés.

---

## Déploiement

La plateforme se déploie gratuitement sans modification : aucune base externe, un seul processus, et 3,5 Mo de données qui tiennent dans l'image.

```bash
docker build -t abrip .
docker run --rm -p 8000:7860 -e PORT=7860 abrip
```

L'étape `abrip demo verify` s'exécute pendant la construction : si la détection ne retrouve pas les cinq anomalies plantées, l'image ne se construit pas. Un déploiement ne peut donc pas partir avec une détection cassée.

Hugging Face Spaces est l'hébergement gratuit recommandé — 16 Go de mémoire, pas de mise en veille, pas de carte bancaire. Render et Fly.io sont documentés comme alternatives. Procédure complète, variables d'environnement, vérification post-déploiement et intégration continue : [docs/deploiement.md](docs/deploiement.md).

## Documents

- [Cahier des charges v2](docs/Cahier_des_charges_ABRIP_v2.md) — spécification complète
- [ADR 0001](docs/adr/0001-strategie-parseur-mrt.md) — stratégie de parsing MRT
- [ADR 0002](docs/adr/0002-stockage-parquet-duckdb.md) — Parquet + DuckDB plutôt qu'une base
- [ADR 0003](docs/adr/0003-detection-explicable.md) — détection explicable plutôt qu'apprise
- [ADR 0004](docs/adr/0004-graphe-propagation-prefixe.md) — graphe de propagation d'un préfixe
- [Limites et remédiations](docs/limites-et-remediations.md) — ce que la plateforme ne peut pas conclure, et comment y remédier
- [Guide de déploiement](docs/deploiement.md) — hébergement gratuit, Docker, intégration continue
- [Performances à grande échelle](docs/performances.md) — mesures de 1 à 50 millions de lignes, ce qui a été optimisé, ce qui ne passe pas encore à l'échelle

## Sources de données

RouteViews · RIPE RIS et RIS Live · AFRINIC et fichiers `delegated-extended` des RIR · RPKI (jeu de ROA validés) · CAIDA AS-relationships et AS2Org · PeeringDB.

Toutes publiques, toutes horodatées : une analyse peut être rejouée à l'identique à partir des mêmes instantanés.
