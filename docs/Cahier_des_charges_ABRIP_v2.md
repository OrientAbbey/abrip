# Cahier des charges — African BGP Routing Intelligence Platform (ABRIP)

**Version 2.0 — Septembre 2026**
**Porteur du projet :** Orient Francis James Abbey Abbey
**Statut :** Projet autonome — Data Engineering appliqué au routage inter-domaines
**Remplace :** version 1.0 (septembre 2026)

### Journal des modifications par rapport à la v1.0

| # | Changement | Motif |
|---|---|---|
| 1 | Restitution : **FastAPI + frontend React/Vite** au lieu de Streamlit | Streamlit masque la couche service ; une API REST et une interface séparée rendent les données consommables par n'importe quel client, et permettent de faire évoluer l'interface sans toucher au traitement |
| 2 | Ajout d'un **référentiel de validation RPKI** (ROA) et IRR | Sans RPKI, un candidat « hijack » n'est qu'une heuristique ; la validation ROA transforme un signal faible en preuve exploitable |
| 3 | Ajout d'un **référentiel géographique dérivé des RIR delegated stats** (AFRINIC + autres) | La v1 supposait une liste d'ASN africains sans définir sa source ; le fichier `delegated-afrinic-extended-latest` est la source d'autorité, gratuite et versionnable |
| 4 | Ajout du **modèle de données explicite** (schémas de tables, types, clés, partitionnement) | La v1 nommait les tables sans les spécifier ; impossible à implémenter sans ambiguïté |
| 5 | Ajout du **contrat d'API** (endpoints, paramètres, codes retour) | Nécessaire pour développer backend et frontend en parallèle |
| 6 | Détection d'anomalies enrichie : sous-préfixe, violation valley-free, AS-path forgé, bogons | La v1 ne couvrait que MOAS + churn, ce qui laissait de côté les classes d'incidents les plus fréquentes |
| 7 | Ajout d'un **mode « sample »** avec jeu de données figé embarqué | Permet à un évaluateur de lancer le projet en moins de 5 minutes sans télécharger 30 jours de MRT |
| 8 | Corrections factuelles sur les collecteurs (JINX, KIXP, NAPAfrica, GIXA, rrc19) | La v1 citait `rrc00`/`rrc11` comme candidats africains, ce qui est inexact : `rrc00` est multihop et `rrc11` est à New York |
| 9 | Ajout des budgets de performance, du plan de test et de la définition de « terminé » par lot | Rend le projet pilotable et vérifiable |
| 10 | Phasage réorganisé en **lots livrables indépendants** plutôt qu'en phases séquentielles | Chaque lot produit une valeur démontrable, ce qui limite le risque d'un projet inachevé |

---

## 1. Contexte et objectifs

### 1.1 Contexte

Le routage entre opérateurs sur Internet repose sur BGP (Border Gateway Protocol, RFC 4271), un protocole fondé sur la confiance : un réseau annonce les préfixes IP qu'il prétend desservir, et ses voisins le croient. Cette confiance produit trois familles d'incidents observables depuis l'extérieur :

- **Le détournement de préfixe** (*hijack*) : un AS annonce un préfixe qu'il n'est pas autorisé à annoncer, par erreur ou délibérément.
- **La fuite de routes** (*route leak*, RFC 7908) : un AS réannonce à ses transitaires des routes apprises d'autres transitaires ou pairs, ce qui viole la politique de routage attendue et détourne du trafic.
- **L'instabilité** : rafales d'annonces/retraits (*flapping*), perte de visibilité d'un préfixe, changement brutal de transitaire — souvent symptôme d'une coupure de câble sous-marin, d'une panne d'équipement ou d'une coupure volontaire.

L'Afrique présente un profil de routage spécifique : dépendance persistante à des transitaires hors continent pour une partie du trafic intra-africain, concentration de la visibilité sur quelques points d'échange (Johannesburg, Nairobi, Accra, Lagos, Le Caire), et sensibilité forte aux ruptures de câbles sous-marins sur les façades ouest et est. Ces phénomènes sont mesurables à partir de données **publiques et gratuites** : les archives MRT de **Route Views** (University of Oregon) et de **RIPE RIS** (RIPE NCC).

### 1.2 Objectif

Construire une **plateforme d'observation du routage BGP africain** — pas une analyse ponctuelle de fichiers — capable de :

1. Ingérer de façon reproductible et incrémentale les archives BGP (dumps RIB et updates) des collecteurs pertinents, puis, en option, un flux quasi temps réel.
2. Transformer ces données brutes en tables analytiques partitionnées et requêtables en SQL.
3. Construire un référentiel d'autorité (ASN africains, ROA RPKI, relations entre AS, IXP) permettant de qualifier ce qui est observé.
4. Calculer des indicateurs de stabilité, de visibilité et de dépendance du routage africain.
5. Détecter des **candidats d'anomalie** explicables, horodatés, scorés et rejouables.
6. Exposer le tout via une API REST documentée et une interface web d'exploration.
7. Produire un jeu de données curé et documenté, exportable en Parquet, exploitable par tout outil tiers (notebook, tableur, base analytique) sans dépendre de la plateforme.

### 1.3 Utilisateurs cibles

| Profil | Ce qu'il attend de la plateforme |
|---|---|
| Ingénieur réseau / NOC d'un opérateur africain | Savoir si ses préfixes sont vus correctement depuis l'extérieur, et être alerté sur un MOAS ou une perte de visibilité |
| Analyste data / régulateur | Disposer d'indicateurs agrégés par pays sur la dépendance au transit et la stabilité |
| Évaluateur technique (recruteur, pair) | Comprendre l'architecture, relancer le pipeline et vérifier un résultat en moins de 30 minutes |

### 1.4 Périmètre géographique

Le périmètre analytique est l'ensemble des ASN dont le RIR d'attribution est **AFRINIC**, complété par une liste d'ASN africains attribués par d'autres RIR (cas des opérateurs enregistrés hors continent), maintenue en configuration. Le périmètre d'**ingestion** est plus large que le périmètre d'**analyse** : on ingère la vue complète des collecteurs retenus, puis on filtre à l'analyse. Restreindre l'ingestion aux seuls préfixes africains rendrait impossible la détection d'un préfixe africain détourné par un AS non africain.

### 1.5 Non-objectifs (hors périmètre V1)

- La plateforme n'est **pas** un service de production avec engagement de disponibilité ni alerting opérationnel temps réel.
- Elle ne cherche pas à concurrencer Cloudflare Radar, Kentik, BGPmon ou IIJ IHR, mais à démontrer une maîtrise de bout en bout de la chaîne donnée → décision.
- Aucune anomalie n'est présentée comme un fait avéré : la plateforme produit des **candidats à investiguer**, avec un score et les éléments de preuve.
- Pas de multi-tenant, pas de gestion de comptes utilisateurs en V1 (une clé API optionnelle suffit).

---

## 2. Glossaire

| Terme | Définition retenue dans ce document |
|---|---|
| **MRT** | Format binaire d'archive de messages de routage (RFC 6396), utilisé par RouteViews et RIS |
| **RIB dump** | Photographie complète de la table de routage d'un collecteur à un instant t (`bview.*` / `rib.*`) |
| **Updates** | Fichier des messages BGP incrémentaux (annonces/retraits) sur une fenêtre courte |
| **Collecteur** | Routeur d'observation qui établit des sessions BGP avec des opérateurs volontaires (*peers*) |
| **Peer / vantage point** | Un opérateur qui alimente un collecteur ; chaque peer offre une vue partielle d'Internet |
| **AS-path** | Suite d'AS traversés, telle qu'annoncée ; le premier élément côté préfixe est l'**AS d'origine** |
| **MOAS** | *Multiple Origin AS* — un même préfixe annoncé avec plusieurs AS d'origine distincts |
| **ROA** | *Route Origin Authorisation* — objet RPKI signé autorisant un AS à annoncer un préfixe jusqu'à une longueur maximale |
| **Valley-free** | Modèle de politique de routage : une route apprise d'un pair ou d'un transitaire ne doit pas être réannoncée à un autre pair ou transitaire |
| **Churn** | Volume d'annonces et de retraits par unité de temps |
| **Visibilité** | Proportion des peers observant un préfixe donné à un instant t |

---

## 3. Sources de données

### 3.1 Sources primaires — archives BGP

| Source | Contenu | Accès | Fréquence |
|---|---|---|---|
| Route Views | RIB + updates MRT par collecteur | HTTP sur `archive.routeviews.org`, indexé par `bgpkit-broker` | RIB toutes les 2 h, updates toutes les 15 min |
| RIPE RIS | RIB + updates MRT par RRC | HTTP sur `data.ris.ripe.net`, indexé par `bgpkit-broker` | RIB toutes les 8 h, updates toutes les 5 min |
| RIS Live | Flux BGP temps réel JSON | WebSocket `ris-live.ripe.net`, sans authentification | Continu |

**Collecteurs candidats pour la couverture africaine** (liste à valider en lot 0, par comptage effectif des peers africains dans un RIB) :

| Collecteur | Localisation | Intérêt |
|---|---|---|
| `route-views.napafrica` | Johannesburg, NAPAfrica | Le plus grand IXP du continent, forte densité de peers africains |
| `route-views.jinx` | Johannesburg, JINX | Vue complémentaire sur l'Afrique australe |
| `route-views.kixp` | Nairobi, KIXP | Afrique de l'Est |
| `route-views.gixa` | Accra, GIXA | Afrique de l'Ouest |
| `rrc19` | Johannesburg (RIPE RIS) | Vue RIS sur l'Afrique australe |
| `route-views2` / `rrc00` | Multihop (Eugene / Amsterdam) | Vue « extérieure » de référence, indispensable pour mesurer la visibilité mondiale d'un préfixe africain |

> Correction par rapport à la v1 : `rrc11` est situé à New York et `rrc00` est un collecteur multihop, ni l'un ni l'autre ne sont des points de vue africains. Ils restent utiles comme **référence extérieure**, ce qui est un rôle différent et doit être explicité dans la configuration (`role: local` vs `role: external`).

### 3.2 Sources de référence — enrichissement et validation

| Source | Usage | Fréquence de rafraîchissement |
|---|---|---|
| **AFRINIC delegated-extended** (`ftp.afrinic.net`) | Liste d'autorité des ASN et préfixes délégués par pays africain | Quotidienne |
| Delegated-extended des 4 autres RIR | Résolution pays pour les ASN africains attribués hors AFRINIC | Hebdomadaire |
| **RPKI / ROA** — export JSON d'un validateur public (RIPE NCC RPKI Validator, Cloudflare `rpki.cloudflare.com/rpki.json`) | Validation origine : `valid` / `invalid` / `not-found` | Quotidienne |
| **CAIDA AS Relationships (Serial-2)** | Qualification des liens d'AS-path : provider-to-customer, peer-to-peer | Mensuelle |
| **CAIDA AS Rank / AS-to-organization** | Regroupement d'ASN par organisation, détection des faux MOAS (même groupe) | Trimestrielle |
| **PeeringDB** | Rattachement des AS aux IXP, contexte d'interconnexion africaine | Hebdomadaire |
| **IRR (RADB, AFRINIC WHOIS)** *(optionnel)* | Vérification des objets `route:` déclarés | Hebdomadaire |

Chaque instantané de référence est stocké **daté et immuable** (`reference/rpki/date=YYYY-MM-DD/`) : un résultat d'analyse doit rester rejouable avec le référentiel en vigueur au moment des faits, pas avec le référentiel d'aujourd'hui.

### 3.3 Stratégie d'accès — décision d'architecture

Trois bibliothèques permettent d'accéder aux MRT. L'analyse comparée conduit à une **architecture en couches avec repli explicite** :

| Rang | Composant | Rôle | Repli si indisponible |
|---|---|---|---|
| 1 | `bgpkit-broker` (API HTTP publique) | Découverte des fichiers MRT disponibles par collecteur et plage de dates | Construction déterministe des URL d'archive à partir des conventions de nommage RouteViews/RIS (`scripts/url_builder`) |
| 2 | `bgpkit-parser` (binding Python `pybgpkit-parser`) | Parsing MRT → enregistrements élémentaires | `mrtparse` (pur Python, plus lent mais sans dépendance native) |
| 3 | RIS Live (WebSocket) | Flux temps réel | Non bloquant : le mode live est optionnel |
| 4 | `pybgpstream` (CAIDA) | Option de repli complète, référence académique | Documenté, non installé par défaut |

Le parseur est accédé à travers une **interface unique** (`MRTParser`) : les trois implémentations (`bgpkit`, `mrtparse`, `bgpstream`) sont interchangeables et sélectionnées par configuration. Aucun module en aval ne connaît la bibliothèque utilisée. C'est la décision d'architecture la plus structurante du projet et elle doit être documentée comme telle dans le README.

---

## 4. Architecture cible

### 4.1 Vue d'ensemble

```
   SOURCES PUBLIQUES
   ├─ RouteViews (MRT)        ├─ AFRINIC delegated-extended
   ├─ RIPE RIS (MRT)          ├─ RPKI ROA (JSON)
   └─ RIS Live (WebSocket)    ├─ CAIDA AS relationships / AS2org
                              └─ PeeringDB
                 │
                 ▼
   ┌────────────────────────────────────────────────────────┐
   │ INGESTION            broker → downloader → raw store   │
   │ reprise, retry, checksum, journal d'ingestion (DuckDB) │
   └────────────────────────────────────────────────────────┘
                 │
                 ▼
   ┌────────────────────────────────────────────────────────┐
   │ RAW  (bronze)   data/raw/{collector}/{type}/{date}/    │
   │ fichiers MRT non modifiés + captures RIS Live (.jsonl) │
   └────────────────────────────────────────────────────────┘
                 │  parsing en flux, par lots, mémoire bornée
                 ▼
   ┌────────────────────────────────────────────────────────┐
   │ CURATED (silver)  Parquet partitionné + vues DuckDB    │
   │ bgp_elements · rib_snapshots · ref_asn · ref_roa ·     │
   │ ref_as_rel · ref_as_org                                │
   └────────────────────────────────────────────────────────┘
                 │
                 ▼
   ┌────────────────────────────────────────────────────────┐
   │ ANALYTICS (gold)   agrégats Polars → Parquet           │
   │ churn · visibilité · évolution AS-path · upstream ·    │
   │ dépendance transit par pays                            │
   └────────────────────────────────────────────────────────┘
                 │
                 ▼
   ┌────────────────────────────────────────────────────────┐
   │ DÉTECTION   détecteurs enfichables → table events      │
   │ MOAS · sous-préfixe · valley-free · churn robuste ·    │
   │ perte de visibilité · bogon/RPKI invalid               │
   └────────────────────────────────────────────────────────┘
                 │
                 ▼
   ┌────────────────────────────────────────────────────────┐
   │ API  FastAPI (REST + WebSocket + OpenAPI)              │
   │ lecture seule sur DuckDB/Parquet, cache en mémoire     │
   └────────────────────────────────────────────────────────┘
                 │
                 ▼
   ┌────────────────────────────────────────────────────────┐
   │ FRONTEND  React + Vite + TypeScript (SPA)              │
   │ servi en statique par FastAPI en production            │
   └────────────────────────────────────────────────────────┘
```

### 4.2 Principes d'architecture

1. **Séparation stricte des couches.** Aucun module d'analyse ne lit un fichier MRT ; aucun module d'API n'exécute de transformation lourde. L'API sert des résultats **déjà calculés**.
2. **Immutabilité de la couche brute.** Un fichier MRT ingéré n'est jamais modifié ni écrasé. Le retraitement produit une nouvelle version de la couche curée.
3. **Idempotence.** Rejouer l'ingestion ou l'ETL sur la même plage produit exactement le même résultat, sans doublon. La clé d'idempotence est `(collector, file_type, file_timestamp)`.
4. **Mémoire bornée avant volume.** Tout traitement doit fonctionner sur 8 Go de RAM. Un dump RIB complet n'est jamais matérialisé en mémoire : parsing en itérateur, écriture Parquet par lots de N enregistrements.
5. **Explicabilité avant sophistication.** Chaque anomalie porte les éléments de preuve qui l'ont déclenchée. Un détecteur que l'on ne peut pas expliquer en deux phrases n'entre pas en V1.
6. **Configuration plutôt que code.** Collecteurs, seuils, fenêtres, listes d'ASN suivis sont en YAML, pas en dur.

### 4.3 Organisation du dépôt

```
abrip/
├─ configs/                 settings.yaml · collectors.yaml · detection.yaml
├─ data/                    raw/ · curated/ · analytics/ · reference/ · catalog.duckdb
├─ docs/                    cahier des charges · ADR · schémas
├─ src/abrip/
│  ├─ config.py             chargement typé de la configuration
│  ├─ models.py             schémas Pydantic + schémas Polars
│  ├─ storage/              catalogue DuckDB, écriture Parquet
│  ├─ ingestion/            broker · downloader · ris_live
│  ├─ reference/            afrinic · rpki · caida · peeringdb
│  ├─ etl/                  parsers MRT · normalisation · curation
│  ├─ analytics/            churn · visibility · aspath · upstream
│  ├─ anomaly/              base · détecteurs · moteur
│  ├─ api/                  FastAPI, routers, schémas de réponse
│  └─ cli.py                point d'entrée unique (Typer)
├─ frontend/                React + Vite + TypeScript
├─ tests/                   unitaires · intégration · fixtures MRT réduites
└─ Makefile                 cibles reproductibles
```

---

## 5. Modèle de données

Toutes les tables curées sont en **Parquet compressé zstd**, partitionnées, et exposées en SQL via des vues DuckDB. Les horodatages sont en UTC, en `TIMESTAMP` microseconde.

### 5.1 `bgp_elements` — table de faits principale

Partitionnement : `date=YYYY-MM-DD / collector=<nom> / hour=HH`

| Colonne | Type | Description |
|---|---|---|
| `ts` | `TIMESTAMP` | Horodatage du message BGP |
| `collector` | `CATEGORY` | Nom du collecteur |
| `peer_asn` | `UINT32` | ASN du peer qui a fourni l'information |
| `peer_ip` | `STRING` | Adresse IP du peer |
| `elem_type` | `ENUM('A','W','R')` | Annonce, retrait, entrée de RIB |
| `prefix` | `STRING` | Préfixe en notation CIDR |
| `prefix_ip_version` | `UINT8` | 4 ou 6 |
| `prefix_len` | `UINT8` | Longueur du masque |
| `origin_asn` | `UINT32 NULL` | AS d'origine (null pour un retrait) |
| `as_path` | `LIST[UINT32]` | Chemin d'AS brut, prepending conservé |
| `as_path_dedup` | `LIST[UINT32]` | Chemin sans prepending consécutif |
| `as_path_len` | `UINT16` | Longueur du chemin dédupliqué |
| `has_as_set` | `BOOLEAN` | Présence d'un AS_SET dans le chemin |
| `next_hop` | `STRING NULL` | Next-hop annoncé |
| `communities` | `LIST[STRING] NULL` | Communautés BGP |
| `med` / `local_pref` | `UINT32 NULL` | Attributs optionnels |
| `source_file` | `STRING` | Fichier MRT d'origine — traçabilité |

### 5.2 `rib_snapshots` — état de la table de routage

Partitionnement : `date / collector`. Une ligne par `(snapshot_ts, collector, peer_asn, prefix)`, obtenue à partir des RIB dumps. Sert de base au calcul de visibilité et de dépendance.

### 5.3 Tables de référence

| Table | Clé | Colonnes clés |
|---|---|---|
| `ref_asn` | `asn` | `country_iso2`, `rir`, `is_african`, `allocation_date`, `holder_name`, `snapshot_date` |
| `ref_prefix_alloc` | `prefix` | `country_iso2`, `rir`, `snapshot_date` |
| `ref_roa` | `(prefix, asn, max_len)` | `ta` (trust anchor), `snapshot_date` |
| `ref_as_rel` | `(as_a, as_b)` | `relationship` ∈ {`p2c`,`c2p`,`p2p`,`s2s`}, `source`, `snapshot_date` |
| `ref_as_org` | `asn` | `org_id`, `org_name`, `country`, `snapshot_date` |
| `ref_ixp` | `(ixp_id, asn)` | `ixp_name`, `city`, `country_iso2`, `snapshot_date` |

### 5.4 Tables analytiques (gold)

| Table | Grain | Contenu |
|---|---|---|
| `metric_churn` | `(window_start, collector, prefix)` et `(window_start, collector, origin_asn)` | `announcements`, `withdrawals`, `updates_total`, `distinct_peers` |
| `metric_visibility` | `(snapshot_ts, prefix)` | `peers_seeing`, `peers_total`, `visibility_ratio`, `collectors_seeing` |
| `metric_aspath` | `(window_start, prefix)` | `distinct_paths`, `distinct_origins`, `median_path_len`, `path_changes` |
| `metric_upstream` | `(window_start, asn)` | `upstreams` (liste), `upstream_changes`, `hhi_transit` (concentration) |
| `metric_country` | `(window_start, country_iso2)` | `prefixes_visible`, `avg_visibility`, `transit_dependency_ratio`, `intra_africa_path_share` |

### 5.5 `events` — sortie de la détection

| Colonne | Type | Description |
|---|---|---|
| `event_id` | `STRING` | UUIDv5 déterministe (même entrée ⇒ même identifiant) |
| `detector` | `STRING` | `moas`, `subprefix`, `valley_free`, `churn_spike`, `visibility_drop`, `rpki_invalid` |
| `severity` | `ENUM('info','watch','critical')` | Niveau issu du score et de l'impact |
| `score` | `FLOAT` | 0–1, normalisé par détecteur |
| `confidence` | `ENUM('low','medium','high')` | Fonction du nombre de peers concordants et de la validation RPKI |
| `first_seen` / `last_seen` | `TIMESTAMP` | Fenêtre de l'événement |
| `prefix` | `STRING NULL` | Préfixe concerné |
| `asns_involved` | `LIST[UINT32]` | AS impliqués |
| `country_iso2` | `STRING NULL` | Pays rattaché |
| `evidence` | `JSON` | Éléments de preuve : peers, chemins observés, valeurs de baseline, statut ROA |
| `explanation` | `STRING` | Phrase en langage naturel expliquant le déclenchement |
| `run_id` | `STRING` | Exécution de détection ayant produit l'événement |

### 5.6 `ingestion_log` et `runs` (catalogue DuckDB)

`ingestion_log(file_url PK, collector, file_type, file_ts, bytes, sha256, status, attempts, started_at, finished_at, error)`
`runs(run_id PK, stage, params_json, started_at, finished_at, status, rows_in, rows_out, notes)`

---

## 6. Spécifications fonctionnelles

Chaque exigence porte un identifiant stable, une définition de « terminé » (DoD) et un test associé.

### 6.1 Ingestion (F1)

| ID | Exigence | DoD |
|---|---|---|
| F1.1 | Interroger le broker pour lister les fichiers MRT disponibles par collecteur, type et plage de dates | Un appel CLI retourne la liste des fichiers avec URL, taille et horodatage |
| F1.2 | Télécharger les fichiers vers la couche brute avec reprise, backoff exponentiel et 3 tentatives | Une coupure réseau simulée n'entraîne ni fichier tronqué conservé, ni perte d'état |
| F1.3 | Vérifier l'intégrité : taille non nulle, en-tête MRT lisible, empreinte SHA-256 enregistrée | Un fichier corrompu est marqué `failed` et non promu en couche brute |
| F1.4 | Journaliser chaque fichier dans `ingestion_log` et ne jamais retélécharger un fichier déjà en statut `ok` | Deux exécutions successives : la seconde télécharge 0 fichier |
| F1.5 | Mode `--dry-run` listant le volume à télécharger sans écrire | Sortie chiffrée en Mo et en nombre de fichiers |
| F1.6 *(lot 6)* | Client RIS Live WebSocket avec filtre (préfixes, ASN, collecteurs), écriture en JSONL par fenêtres de 5 minutes, reconnexion automatique | Une coupure du socket est suivie d'une reconnexion en moins de 30 s sans perte de fichier |

### 6.2 Référentiel (F2)

| ID | Exigence | DoD |
|---|---|---|
| F2.1 | Télécharger et parser les fichiers `delegated-extended` des RIR, produire `ref_asn` et `ref_prefix_alloc` | La table contient les ASN AFRINIC avec leur pays ; contrôle manuel sur 5 ASN connus |
| F2.2 | Télécharger un export ROA JSON et produire `ref_roa` daté | La validation d'un préfixe de test renvoie le statut attendu |
| F2.3 | Implémenter la validation d'origine RPKI : `valid` si un ROA couvre le préfixe avec `prefix_len ≤ max_len` et l'ASN correspond ; `invalid` si un ROA couvre le préfixe mais ne l'autorise pas ; sinon `not-found` | Jeu de tests unitaires couvrant les trois cas et le cas `max_len` |
| F2.4 | Charger CAIDA AS-relationships et AS2org | Jointure réussie sur un échantillon d'AS-paths |
| F2.5 | Charger PeeringDB (IXP ↔ ASN) | Les AS africains présents dans les IXP majeurs sont retrouvés |
| F2.6 | Tout référentiel est daté, immuable, et le module expose `load(as_of: date)` | Deux exécutions avec deux dates différentes chargent deux instantanés différents |

### 6.3 ETL (F3)

| ID | Exigence | DoD |
|---|---|---|
| F3.1 | Parser un fichier MRT en itérateur d'enregistrements normalisés, quelle que soit l'implémentation retenue | Le même fichier parsé par `bgpkit` et par `mrtparse` produit le même nombre d'éléments et les mêmes 100 premiers préfixes |
| F3.2 | Normaliser l'AS-path : suppression du prepending consécutif, conservation du chemin brut, indicateur `has_as_set`, gestion des ASN 32 bits et des AS privés | Tests sur chemins synthétiques couvrant prepending, AS_SET, AS privés |
| F3.3 | Écrire `bgp_elements` en Parquet partitionné, par lots de 500 000 lignes, avec compression zstd | Un fichier updates de 50 Mo est traité avec un pic mémoire < 1,5 Go |
| F3.4 | Construire `rib_snapshots` à partir des RIB dumps | Le nombre de préfixes IPv4 uniques d'un RIB récent est cohérent avec l'ordre de grandeur attendu de la table globale |
| F3.5 | Enrichir les éléments avec le pays de l'AS d'origine, le statut RPKI et la nature des liens du chemin | Un échantillon enrichi est vérifié manuellement sur 10 lignes |
| F3.6 | Réexécution idempotente : une partition retraitée est remplacée atomiquement, pas dupliquée | Deux exécutions ⇒ même nombre de lignes |

### 6.4 Analytics (F4)

| ID | Exigence |
|---|---|
| F4.1 | **Churn** : annonces, retraits et total par fenêtre glissante configurable (5 min, 1 h, 24 h), par préfixe, par AS d'origine et par collecteur |
| F4.2 | **Visibilité** : `peers_seeing / peers_total` par préfixe et par instantané, avec ventilation collecteurs locaux / extérieurs, ce qui distingue une panne locale d'une perte de visibilité mondiale |
| F4.3 | **Évolution d'AS-path** : nombre de chemins distincts, changements d'AS d'origine, variation de longueur médiane, détection de changement de chemin par préfixe |
| F4.4 | **Changement d'upstream** : suivi de l'AS immédiatement en amont d'un AS africain suivi, qualifié par les relations CAIDA |
| F4.5 | **Dépendance au transit par pays** : part des préfixes d'un pays dont le chemin vers le point de vue extérieur ne traverse aucun AS africain autre que l'origine — indicateur de dépendance à un transit hors continent |
| F4.6 | **Concentration (HHI)** : indice de Herfindahl sur la répartition des upstreams d'un pays, mesurant la fragilité structurelle |
| F4.7 | Toutes les métriques sont écrites en Parquet, versionnées par `run_id`, et recalculables à l'identique |

### 6.5 Détection d'anomalies (F5)

Interface commune : chaque détecteur reçoit une fenêtre de données curées + un référentiel daté, et retourne une liste d'`Event`. Tous les détecteurs sont enfichables et activables en configuration.

| ID | Détecteur | Principe | Éléments de preuve produits |
|---|---|---|---|
| F5.1 | `moas` | Un préfixe annoncé avec ≥ 2 AS d'origine sur la même fenêtre. Exclusion des MOAS légitimes : même organisation (AS2org), relation directe c2p, MOAS stable historiquement | Liste des origines, nombre de peers par origine, ancienneté de chaque origine |
| F5.2 | `subprefix` | Apparition d'un préfixe plus spécifique qu'un préfixe couvert par un ROA, annoncé par un AS non autorisé | Préfixe couvrant, ROA applicable, AS annonceur |
| F5.3 | `rpki_invalid` | Annonce dont le statut de validation d'origine est `invalid` et qui est vue par plusieurs peers | ROA violé, nombre de peers, durée |
| F5.4 | `valley_free` | Chemin violant le modèle valley-free d'après les relations CAIDA : un AS réannonce à un transitaire/pair une route apprise d'un transitaire/pair — signature classique de fuite de routes | Chemin fautif, position de la violation, relations impliquées |
| F5.5 | `churn_spike` | Médiane glissante + MAD (robust z-score) sur le churn par préfixe/AS, avec baseline horaire et hebdomadaire | Valeur observée, médiane, MAD, z-score, fenêtre de baseline |
| F5.6 | `visibility_drop` | Chute de `visibility_ratio` au-delà d'un seuil relatif, corroborée par ≥ 2 collecteurs | Ratio avant/après, collecteurs concernés |
| F5.7 | `bogon` | Annonce d'un préfixe non alloué, réservé (RFC 1918, 6598, documentation) ou d'un AS privé en origine | Type de bogon, référence RFC |
| F5.8 | Scoring et corrélation : les événements portant sur le même préfixe et la même fenêtre sont regroupés en un **incident** ; le score final combine le nombre de détecteurs concordants, le nombre de peers et la validation RPKI | — |
| F5.9 | Aucun événement n'est présenté comme un fait : le champ `explanation` emploie systématiquement une formulation de candidat | — |
| F5.10 | Rejouabilité : un `run_id` permet de rejouer exactement la même détection sur les mêmes données | — |

**Calibration.** Les seuils par défaut sont fixés sur un jeu de validation : au moins deux incidents de routage africains publiquement documentés (coupures de câbles sous-marins, fuites de routes) sont rejoués a posteriori. Le taux de faux positifs est estimé par échantillonnage manuel de 30 événements et consigné dans `docs/calibration.md`.

### 6.6 API (F6)

Backend **FastAPI**, lecture seule, réponses JSON, documentation OpenAPI auto-générée sur `/docs`.

| Méthode | Route | Description | Paramètres |
|---|---|---|---|
| `GET` | `/api/health` | État du service, version, fraîcheur des données | — |
| `GET` | `/api/meta/collectors` | Collecteurs configurés, rôle, dernier fichier ingéré | — |
| `GET` | `/api/meta/coverage` | Plage temporelle disponible par couche | — |
| `GET` | `/api/overview` | Indicateurs de synthèse : préfixes africains suivis, visibilité moyenne, événements ouverts par sévérité | `window` |
| `GET` | `/api/asns` | Liste paginée des AS africains avec pays, nombre de préfixes, upstreams | `country`, `q`, `limit`, `offset`, `sort` |
| `GET` | `/api/asns/{asn}` | Fiche AS : préfixes annoncés, upstreams, historique de churn, événements | `window` |
| `GET` | `/api/prefixes/{prefix}` | Fiche préfixe : origines observées, visibilité, statut RPKI, chemins les plus fréquents | `window` |
| `GET` | `/api/metrics/churn` | Série temporelle de churn | `asn` \| `prefix` \| `collector`, `from`, `to`, `granularity` |
| `GET` | `/api/metrics/visibility` | Série temporelle de visibilité | idem |
| `GET` | `/api/metrics/countries` | Indicateurs agrégés par pays | `from`, `to` |
| `GET` | `/api/events` | Liste filtrable d'événements | `detector`, `severity`, `country`, `asn`, `prefix`, `from`, `to`, `limit`, `offset` |
| `GET` | `/api/events/{event_id}` | Détail d'un événement avec éléments de preuve | — |
| `GET` | `/api/events/{event_id}/timeline` | Reconstitution chronologique des annonces liées | — |
| `GET` | `/api/search` | Recherche unifiée : ASN, préfixe, nom d'opérateur, code pays | `q` |
| `GET` | `/api/export/{table}` | Export Parquet ou CSV d'une table curée | `format`, `from`, `to` |
| `WS` | `/ws/events` | Diffusion des nouveaux événements *(lot 6)* | — |

**Exigences transverses de l'API**

- Pagination systématique sur les listes, enveloppe `{ "items": [...], "total": n, "limit": l, "offset": o }`.
- Erreurs normalisées : `{ "error": { "code": "...", "message": "...", "details": {...} } }`, codes 400 / 404 / 422 / 503.
- Temps de réponse cible : p95 < 300 ms sur les routes de liste, < 800 ms sur les séries temporelles.
- Connexion DuckDB en lecture seule, une connexion par requête issue d'un pool, aucune écriture depuis l'API.
- Cache mémoire TTL (60 s par défaut) sur les routes d'agrégat.
- CORS restreint à l'origine du frontend en développement.
- Clé API optionnelle (`X-API-Key`) activable en configuration ; désactivée par défaut en local.
- Si une table analytique est absente, l'API répond `503` avec un message indiquant la commande CLI à lancer, jamais une erreur opaque.

### 6.7 Frontend (F7)

Application **React 18 + Vite + TypeScript**, construite en statique et servie par FastAPI en production (un seul processus, une seule URL, pas de CORS en production).

**Pages**

| Page | Contenu |
|---|---|
| **Vue d'ensemble** | Bandeau d'état du routage africain : nombre de préfixes suivis, visibilité médiane, événements ouverts. Frise temporelle des événements sur 30 jours. Classement des pays par instabilité |
| **Événements** | Table filtrable et triable des candidats d'anomalie, avec sévérité, détecteur, préfixe, AS, pays. Panneau latéral de détail avec éléments de preuve et explication |
| **Détail d'événement** | Chronologie des annonces, chemins d'AS observés avant/après, statut RPKI, peers concordants |
| **Explorateur AS** | Recherche d'un AS, fiche complète : préfixes, upstreams, graphe de voisinage, séries de churn |
| **Explorateur préfixe** | Historique d'origine, visibilité par collecteur, chemins observés |
| **Pays** | Indicateurs par pays africain : dépendance au transit, concentration des upstreams, visibilité moyenne |
| **À propos / méthode** | Sources, limites assumées, méthode de détection, date des référentiels |

**Exigences techniques frontend**

- Client API typé, généré ou dérivé du schéma OpenAPI ; aucun appel `fetch` brut dispersé dans les composants.
- États de chargement, d'erreur et de vide traités explicitement sur chaque vue ; un écran vide indique la commande à lancer pour produire la donnée.
- Graphiques : bibliothèque légère (uPlot ou Recharts) ; pas de dépendance lourde de type D3 complet.
- Tableaux virtualisés au-delà de 200 lignes.
- Responsive jusqu'à 375 px, navigation au clavier, focus visible, contrastes conformes WCAG AA.
- Aucune donnée en dur : toute valeur affichée provient de l'API.
- Budget : bundle JS initial < 250 Ko gzip, première peinture utile < 1,5 s en local.

### 6.8 Orchestration et CLI (F8)

Point d'entrée unique `abrip` (Typer), chaque commande étant journalisée dans `runs` :

```
abrip ingest broker      --collectors napafrica,rrc19 --from 2026-08-01 --to 2026-08-31 --type updates
abrip ingest ris-live    --duration 3600
abrip reference sync     --sources afrinic,rpki,caida,peeringdb
abrip etl curate         --from 2026-08-01 --to 2026-08-31
abrip analytics compute  --window 1h --from ... --to ...
abrip detect run         --detectors moas,valley_free,churn_spike --from ... --to ...
abrip api serve          --host 0.0.0.0 --port 8000
abrip pipeline daily     --date 2026-08-31        # enchaîne les étapes
abrip demo bootstrap                              # charge le jeu d'échantillon
```

Orchestration V1 par `cron` ou Planificateur de tâches Windows. Un ordonnanceur dédié (Prefect, Airflow) n'est justifié que si le nombre de flux dépasse ce qu'une table `cron` documente lisiblement — ce n'est pas le cas ici.

---

## 7. Spécifications techniques

### 7.1 Stack

| Composant | Choix | Justification |
|---|---|---|
| Langage backend | Python 3.11+ | Cohérence avec l'existant professionnel |
| Découverte MRT | `bgpkit-broker` (HTTP) | Léger, indexation quasi temps réel, pas de dépendance native |
| Parsing MRT | `pybgpkit-parser`, repli `mrtparse` | Compromis performance / installabilité |
| Traitement | **Polars** (lazy, streaming) | Performant à RAM contrainte, mode streaming disponible |
| Stockage | Parquet zstd + **DuckDB** | Format standard, SQL sans serveur, lecture partielle par colonne |
| Graphe | NetworkX | Suffisant à l'échelle du voisinage d'AS |
| API | **FastAPI** + Uvicorn | Typage Pydantic, OpenAPI natif, async, WebSocket intégré |
| Validation | Pydantic v2 | Schémas partagés entre API, CLI et configuration |
| Frontend | React 18 + Vite + TypeScript | Standard industriel, build statique servi par FastAPI |
| Graphiques | Recharts (ou uPlot pour les séries longues) | Léger, suffisant |
| CLI | Typer + Rich | Commandes typées, sorties lisibles |
| Tests | pytest, pytest-asyncio, httpx | — |
| Qualité | ruff (lint + format), mypy (mode strict sur `src/abrip/models.py` et `api/`) | — |
| CI | GitHub Actions : lint, typage, tests, build frontend | Preuve de rigueur visible sur le dépôt |
| Conteneurisation | Dockerfile multi-étapes + docker-compose *(optionnel)* | Reproductibilité pour l'évaluateur |

### 7.2 Contraintes matérielles et budgets

| Contrainte | Cible |
|---|---|
| RAM disponible | Fonctionnement garanti à 8 Go, dégradé accepté à 4 Go |
| Pic mémoire ETL | < 1,5 Go par fichier traité |
| Disque, couche brute | Purgeable après curation, rétention configurable (30 jours par défaut) |
| Disque, couche curée | < 20 Go pour 30 jours sur 3 collecteurs après filtrage |
| Durée du pipeline quotidien | < 45 min pour une journée sur 3 collecteurs |
| Démarrage de l'API | < 3 s |

Leviers : filtrage précoce, Polars en `scan_parquet` + `collect(streaming=True)`, écriture par lots, libération explicite entre fichiers, parallélisme borné par le nombre de cœurs physiques moins un.

### 7.3 Configuration

Trois niveaux, par ordre de priorité croissante : valeurs par défaut du code → fichiers YAML dans `configs/` → variables d'environnement préfixées `ABRIP_`. La configuration est chargée une seule fois, validée par Pydantic, et injectée ; aucun module ne lit l'environnement directement.

### 7.4 Qualité, tests et observabilité

- **Tests unitaires** : normalisation d'AS-path, validation RPKI, calcul MAD, chaque détecteur sur données synthétiques. Couverture cible ≥ 70 % sur `src/abrip/` hors API.
- **Tests d'intégration** : ETL bout en bout sur un fichier MRT réel réduit (< 2 Mo) stocké dans `tests/fixtures/`, puis vérification des tables produites.
- **Tests API** : chaque route testée avec un jeu de données d'échantillon ; contrat OpenAPI vérifié.
- **Tests de non-régression de détection** : un scénario d'incident synthétique doit être détecté avec la sévérité attendue.
- **Journalisation structurée** en JSON (`structlog` ou `logging` configuré), avec `run_id` propagé.
- **Métriques d'exécution** : lignes lues/écrites, durée, pic mémoire par étape, consignées dans `runs`.
- **Page de santé des données** : fraîcheur de chaque couche exposée par `/api/health` et affichée dans le frontend.

### 7.5 Sécurité et conformité

- Aucune donnée personnelle traitée : les archives BGP sont des données d'infrastructure publiques.
- Respect des conditions d'utilisation de RouteViews, RIPE NCC, CAIDA et PeeringDB ; attribution explicite dans le README et dans la page « À propos ».
- Politique de téléchargement raisonnable : limitation du débit, `User-Agent` identifiant le projet et un contact, pas de parallélisme agressif sur les archives publiques.
- Aucun secret en dur ; `.env` exclu du dépôt, `.env.example` fourni.
- API en lecture seule, pas d'exécution SQL fournie par l'utilisateur.

---

## 8. Phasage en lots livrables

Chaque lot est autonome et se termine par un artefact démontrable.

| Lot | Contenu | Durée | Artefact de fin de lot |
|---|---|---|---|
| **L0 — Cadrage** | Choix des collecteurs par comptage réel de peers africains dans un RIB ; test d'installation des parseurs ; squelette du dépôt, CLI, configuration, catalogue DuckDB | 1 sem. | `docs/adr/` avec la décision de parseur, `abrip --help` fonctionnel |
| **L1 — Ingestion + Raw** | F1.1 à F1.5 | 1 sem. | 7 jours de données ingérées, `ingestion_log` rempli |
| **L2 — Référentiel** | F2.1 à F2.6 | 1 sem. | `ref_asn`, `ref_roa`, `ref_as_rel` peuplées, validation RPKI testée |
| **L3 — ETL + Curated** | F3.1 à F3.6 | 1,5 sem. | `bgp_elements` et `rib_snapshots` interrogeables en SQL |
| **L4 — Analytics** | F4.1 à F4.7 | 1,5 sem. | Tables de métriques produites, exploration en notebook |
| **L5 — Détection** | F5.1 à F5.10 | 2 sem. | Table `events` peuplée, au moins un incident historique retrouvé |
| **L6 — API** | F6 complet | 1 sem. | `/docs` OpenAPI fonctionnel, toutes routes testées |
| **L7 — Frontend** | F7 complet | 1,5 sem. | SPA buildée et servie par FastAPI |
| **L8 — Industrialisation** | CI, Docker, README, jeu d'échantillon, documentation de calibration | 1 sem. | Dépôt public prêt à être présenté |
| **L9 — Live** *(optionnel)* | F1.6, WebSocket API, vue temps réel | 1 sem. | Événements poussés en direct dans l'interface |

Chemin critique : L0 → L1 → L3 → L4 → L5 → L6 → L7. L2 peut être mené en parallèle de L1. L8 est incrémental.

---

## 9. Livrables

1. Dépôt GitHub public structuré, licence MIT, historique de commits lisible.
2. `README.md` : problème traité, capture de l'interface, architecture, choix techniques justifiés, limites assumées, démarrage en 5 minutes.
3. `docs/adr/` : décisions d'architecture datées (choix du parseur, choix du stockage, choix du modèle de détection).
4. Jeu de données d'échantillon versionné (< 100 Mo) permettant de lancer l'interface sans rien télécharger.
5. Export Parquet documenté, accompagné d'un dictionnaire de données, lisible par DuckDB, pandas, Polars ou tout moteur compatible Arrow.
6. Note de synthèse `docs/findings.md` : au moins un incident détecté, analysé et corroboré par une source externe.
7. `docs/calibration.md` : seuils retenus, méthode d'estimation des faux positifs.
8. Pipeline CI vert et badge dans le README.

---

## 10. Risques

| Risque | Impact | Probabilité | Mitigation |
|---|---|---|---|
| Couverture africaine réelle des collecteurs plus faible qu'attendu | Moyen | Moyenne | Ingérer la vue complète et filtrer à l'analyse ; ajouter les collecteurs multihop comme point de vue extérieur |
| Échec d'installation des bindings de parsing | Élevé | Moyenne | Interface `MRTParser` avec trois implémentations interchangeables, dont `mrtparse` en pur Python |
| Volume MRT supérieur aux prévisions | Moyen | Élevée | Filtrage précoce, rétention courte de la couche brute, traitement incrémental, réduction de la plage plutôt que du nombre de collecteurs |
| Faux positifs en détection | Élevé | Élevée | Vocabulaire de « candidat », score et confiance, corrélation multi-détecteurs, calibration documentée |
| Obsolescence ou indisponibilité d'une source de référence | Moyen | Faible | Instantanés datés conservés localement, dégradation contrôlée si une source est absente |
| Dérive de périmètre (le frontend consomme tout le temps) | Élevé | Moyenne | Lots livrables indépendants ; l'API et les données ont priorité sur l'esthétique de l'interface |
| Projet inachevé faute de temps | Élevé | Moyenne | Les lots L0 à L6 forment déjà un livrable cohérent et utilisable ; le frontend minimal (L7) passe avant le flux temps réel (L9) |

---

## 11. Critères de réussite

| # | Critère | Mesure |
|---|---|---|
| 1 | Le pipeline ingère et traite ≥ 30 jours réels sur ≥ 3 collecteurs dont ≥ 2 africains | `ingestion_log` et volume curé |
| 2 | ≥ 5 indicateurs BGP calculés et exposés par l'API | Tables `metric_*` peuplées |
| 3 | ≥ 4 détecteurs actifs produisant des événements explicables | Table `events` |
| 4 | Au moins un incident documenté publiquement est retrouvé a posteriori par la plateforme | `docs/findings.md` |
| 5 | Un tiers technique installe et lance la démo en < 30 min à partir du README seul | Test réalisé par une personne extérieure |
| 6 | L'interface permet, sans écrire de code, de passer d'une alerte à son explication en 3 clics | Parcours vérifié |
| 7 | Les tables curées sont exploitables hors de la plateforme | Une requête DuckDB externe sur les fichiers Parquet renvoie les mêmes chiffres que l'API |
| 8 | CI verte, couverture ≥ 70 %, `ruff` et `mypy` sans erreur | Rapport CI |

---

## 12. Limites assumées

Ces limites sont revendiquées dans la documentation, pas dissimulées :

- La vue BGP est **partielle par construction** : elle dépend des peers qui alimentent les collecteurs. Un préfixe non vu n'est pas nécessairement inaccessible.
- Les archives ne sont pas temps réel : un retard de publication de quelques minutes à quelques heures est normal.
- Les relations entre AS de CAIDA sont **inférées**, pas déclarées ; une violation valley-free peut résulter d'une inférence erronée.
- Le statut RPKI `not-found` est majoritaire pour une partie de l'espace africain ; l'absence de ROA n'est pas un signal d'attaque.
- La plateforme observe le **plan de contrôle**, pas le plan de données : une route annoncée n'implique pas que le trafic passe.
