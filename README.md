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

Sur le jeu de démonstration (7 jours, 7 collecteurs, 14 préfixes, 9 AS africains dont un couple jumeau pour le filtre L6) :

| Sortie | Volume |
|---|---|
| Éléments BGP curés | 21 011 |
| Lignes de snapshots RIB | 4 904 |
| Points de métriques | 22 217 |
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

**Recharts pour les graphiques.** Composants React déclaratifs, bien maintenus, et le découpage du bundle isole la bibliothèque dans son propre fragment. Total transféré : 191 Ko compressés, sous le budget de 250 Ko fixé au cahier des charges.

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
abrip etl curate --from 2026-08-01 --to 2026-08-07
abrip analytics compute --from 2026-08-01 --to 2026-08-07
abrip detect run --from 2026-08-01 --to 2026-08-07
abrip detect watch --minutes 5 --iterations 12  # détection continue sur RIS Live (L7)
abrip pipeline --date 2026-08-01                # tout l'enchaînement pour un jour
abrip api serve --port 8000
```

Toute commande supporte `--dry-run` là où elle télécharge ou écrit, et journalise en JSON pour être exploitable en production.

---

## Tests

```bash
make test        # 166 tests
make lint        # ruff
make typecheck   # mypy
```

Le test qui compte est `test_rappel_sur_verite_terrain` : il exige que toutes les anomalies plantées soient retrouvées. Un réglage de seuil qui « améliore les chiffres » en cassant la détection est arrêté là.

Les tests d'API et de non-régression sont ignorés proprement — et non en échec — si le pipeline n'a pas encore tourné : la suite reste verte sur une installation fraîche.

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

La plateforme se déploie gratuitement sans modification : aucune base externe, un seul processus, et 3,4 Mo de données qui tiennent dans l'image.

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
- [Limites et remédiations](docs/limites-et-remediations.md) — ce que la plateforme ne peut pas conclure, et comment y remédier
- [Guide de déploiement](docs/deploiement.md) — hébergement gratuit, Docker, intégration continue

## Sources de données

RouteViews · RIPE RIS et RIS Live · AFRINIC et fichiers `delegated-extended` des RIR · RPKI (jeu de ROA validés) · CAIDA AS-relationships et AS2Org · PeeringDB.

Toutes publiques, toutes horodatées : une analyse peut être rejouée à l'identique à partir des mêmes instantanés.
