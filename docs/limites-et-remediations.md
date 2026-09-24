# Limites et remédiations

Les limites de la plateforme viennent de la nature des données BGP, pas de défauts d'implémentation. Ce document les nomme une par une. Pour L1, L2, L3, L4, L6 et L7, la remédiation décrite est **implémentée et vérifiée** dans ce dépôt — le code, les tests et les commandes qui en font foi sont cités à chaque section. L5 reste à l'état de proposition : elle demande une boucle de qualification humaine (voir la section correspondante) qui n'a pas de sens à automatiser seule.

---

## L1 — BGP décrit le plan de contrôle, pas le trafic

**Le problème.** Une route annoncée ne dit rien du volume qui l'emprunte, de la latence, ni de la joignabilité réelle.

**Remédiation implémentée : confirmation par trois sources indépendantes du plan de données.**

| Source | Module | Nécessite une clé |
|---|---|---|
| IODA (CAIDA / Georgia Tech) | `enrichment.dataplane.IodaClient` | non |
| RIPE Atlas (ratio de sondes connectées) | `enrichment.dataplane.RipeAtlasClient` | non |
| Cloudflare Radar (annotations de coupure) | `enrichment.dataplane.CloudflareRadarClient` | oui, gratuite (`ABRIP_ENRICHMENT__CLOUDFLARE_RADAR_TOKEN`) |

`confirm_event()` interroge les trois sources disponibles et rend un verdict `confirmed` / `contradicted` / `inconclusive`. `enrich_events()` est appelée automatiquement après chaque détection (`anomaly.engine._enrich_dataplane`, contrôlé par `enrichment.dataplane_enabled`, activé par défaut) : un événement `critical` contredit par les sources consultées est rétrogradé en `watch`. Sans jeton Cloudflare configuré, les deux premières sources suffisent à faire fonctionner le mécanisme — Cloudflare Radar n'est qu'un renfort optionnel, jamais un prérequis.

Chaque appel réseau échoue en douceur (`inconclusive`, jamais d'exception) : un déploiement sans accès à ces domaines continue de fonctionner normalement.

**Vérifié par :** `tests/test_dataplane.py` (17 tests, transport HTTP simulé sur les trois clients, y compris la rétrogradation de sévérité et le cas « Cloudflare configuré mais sans jeton »).

---

## L2 — La vue est partielle : on ne voit que ce que les peers annoncent

**Le problème.** Un collecteur ne voit que ce que ses voisins lui envoient. Un pays mal couvert paraît artificiellement fragile, sans qu'on puisse le distinguer d'un pays réellement fragile.

**Remédiation implémentée, en trois parties.**

**a) Mesurer et publier la couverture plutôt que la subir.** `analytics.metrics.compute_coverage()` calcule, par pays, la part des AS alloués par AFRINIC effectivement observés depuis les collecteurs (table `metric_coverage`). Cette valeur est ensuite **jointe** dans `metric_country` (pas seulement laissée dans sa table dédiée) et consultée par `anomaly.base.build_event()` pour **plafonner la confiance** de tout événement touchant un pays sous 30 % de couverture — appliqué une seule fois, de façon centrale, plutôt que dans chaque détecteur séparément.

**b) Élargir les sources sans changer d'architecture.** Trois collecteurs européens accueillant des peers africains (`route-views.linx`, `route-views.amsix`, `rrc01`) sont déclarés dans `configs/collectors.yaml`, désactivés par défaut le temps de mesurer leur volume réel.

**c) Ingestion PCH réelle.** PCH publie des relevés quotidiens en texte Cisco (`sh ip bgp`), pas en MRT. `etl.pch_parser.PchTextDumpParser` les lit en repérant les colonnes par **position de caractère** plutôt que par comptage de jetons — une colonne LocPrf vide (le cas courant) rendrait un découpage par `split()` ambigu entre Metric/LocPrf/Weight et le début du chemin d'AS. `ingestion.broker.build_pch_url()` construit l'URL réelle (`downloads.pch.net/files/Routing_Data/IPv4_daily_snapshots/...`), et `etl.curate._parser_for()` sélectionne automatiquement ce parseur pour tout collecteur `project: pch`. Deux collecteurs PCH africains sont déclarés (Johannesburg, Lagos), désactivés par défaut pour la même raison qu'en (b).

**Vérifié par :** `tests/test_pch_parser.py` (9 tests, y compris le cas LocPrf vide et les lignes de continuation, sur un relevé fixé à largeur réelle) ; le pipeline de démonstration calcule et joint `coverage_ratio` sans régression (`abrip demo verify` → rappel 5/5).

---

## L3 — Les relations inter-AS de CAIDA sont inférées, pas contractuelles

**Le problème.** Le détecteur valley-free dépend de relations que CAIDA déduit des chemins observés. Une relation mal inférée produit une fausse fuite de routes, ou en masque une vraie.

**Remédiation implémentée : corroboration par deux sources déclarées.**

- **PeeringDB** (`reference.peeringdb.corroborate_peer`) : deux AS présents sur le même point d'échange, avec une politique de peering compatible, corroborent une relation `p2p`.
- **IRR** (`reference.peeringdb.corroborate_provider`, via `reference.irr.RipeDbClient.expand_as_set`) : si l'AS-SET déclaré par un fournisseur (champ `irr_as_set` de son objet PeeringDB) contient l'AS du client, c'est une corroboration `p2c` — la technique qu'utilisent réellement les opérateurs pour vérifier une relation de transit.

`reference.relationships.RelationshipIndex` porte désormais les sources ayant corroboré chaque lien (`sources()`) et calcule une confiance (`confidence()`). `ValleyFreeDetector` plafonne le score sous le seuil `critical` (`configs/detection.yaml`, `valley_free.min_sources_for_critical: 2`) tant qu'un lien n'est confirmé que par CAIDA seul.

**Vérifié par :** `tests/test_peeringdb.py` (10 tests, y compris la résilience quand une source tombe en panne) ; sur le jeu de démonstration, l'unique événement valley-free est bien plafonné à `watch` (score 0,55) faute de corroboration disponible en environnement isolé.

---

## L4 — `not-found` est le statut RPKI majoritaire dans la zone AFRINIC

**Le problème.** RPKI est la seule preuve cryptographique de la plateforme, et elle est muette sur la majorité des préfixes africains faute de ROA publiés.

**Remédiation implémentée, en deux parties.**

**a) Référentiel IRR de repli.** `reference.irr.IrrValidator` interroge les objets `route`/`route6` via l'API REST officielle de la base RIPE (`rest.db.ripe.net`, qui donne accès à plusieurs registres miroirs — RADB en particulier). Même structure d'index que `RpkiValidator` (recherche par supernet successif). **Les deux détecteurs qui consultaient déjà RPKI le consultent maintenant de la même façon :**
- `SubprefixDetector` : quand RPKI ne couvre pas le préfixe, consulte l'IRR avant de renoncer (`_irr_fallback`), avec un score plus prudent (déclaratif, non signé).
- `MoasDetector` : une origine validée par un ROA multi-origine, ou à défaut cohérente avec un objet route IRR, est traitée comme légitime (`ignore_authorised_origins`).

**b) Indicateur de couverture ROA.** `analytics.metrics.compute_rpki_coverage()` publie, par pays, la part des préfixes annoncés couverte par un ROA valide (table `metric_rpki_coverage`) — la limite devient une mesure suivie dans le temps plutôt qu'un angle mort.

**Vérifié par :** `tests/test_irr.py` (15 tests) ; `metric_rpki_coverage` calculée sans régression sur le jeu de démonstration.

---

## L5 — Une anomalie n'est pas une attaque

**Non implémentée à ce stade** — hors du périmètre demandé pour cette passe. La proposition reste documentée ci-dessous.

**Le problème.** La plateforme détecte des écarts de routage. Distinguer l'erreur de configuration du détournement délibéré demande un contexte que les données publiques n'apportent pas. Sans qualification, on ne peut pas non plus mesurer la précision : on connaît le rappel sur la vérité terrain plantée, pas le taux de faux positifs sur données réelles.

**Ce qu'on peut faire : une boucle de qualification humaine, qui rend la précision mesurable.**

1. Une table `event_feedback` : `event_id`, `verdict` (`legitimate` / `misconfiguration` / `malicious` / `unknown`), auteur, horodatage, note libre.
2. Une commande `abrip detect label <event_id> --verdict misconfiguration --note "..."` — la ligne de commande plutôt qu'une écriture depuis l'API, ce qui préserve la règle « l'API ne fait que lire ».
3. Une commande `abrip detect precision` qui calcule, par détecteur, la part d'événements qualifiés légitimes. C'est ce chiffre qui doit piloter les seuils de `configs/detection.yaml`, pas une intuition.
4. Une liste d'exemptions versionnée, `configs/allowlist.yaml`. La donnée AS2Org (désormais intégrée, voir L6) permet d'en pré-remplir une bonne partie automatiquement.

**Ce que ça ne règle pas.** La qualification demande un opérateur compétent et du temps. Sans utilisateur pour qualifier, la boucle reste vide — c'est une limite organisationnelle, pas technique.

---

## L6 — Les faux positifs MOAS et sous-préfixe

**Le problème.** L'anycast et le multihoming légitime génèrent du MOAS en permanence. Un détecteur qui les signale tous devient du bruit.

**Remédiation implémentée : les trois filtres, cumulables.**

**1. Même organisation.** Le filtre existait dans le code mais consultait un référentiel `ref_as_org` toujours vide — aucune donnée AS2Org n'était jamais chargée. `reference.as2org.parse_as2org()` lit désormais le format réel de CAIDA (deux tables concaténées) et `reference.sync.sync_as2org()` l'alimente. Le jeu de démonstration inclut un couple d'AS jumeaux (37100/37105, même organisation fictive) précisément pour vérifier que le filtre supprime effectivement l'événement qui serait sinon détecté.

**2. Stabilité historique.** `anomaly.engine._compute_stable_pairs()` lit la fenêtre précédant immédiatement la détection (`moas.stability_lookback_days`, 14 jours par défaut) et marque stable tout couple (préfixe, origine) vu au moins `stability_min_days_seen` jours distincts. `DetectionContext.is_stable_origin()` expose le résultat au détecteur. Sur un tout premier déploiement sans historique, l'ensemble est vide et le filtre n'a simplement aucun effet — comportement correct, pas une erreur.

**3. Anycast connu.** `reference.anycast` télécharge le catalogue public **réel** de préfixes anycast détectés par le projet `bgp.tools` (`github.com/bgptools/anycast-prefixes`, licence ouverte, mis à jour en continu — 6 036 préfixes au moment de la rédaction). Un MOAS n'est filtré que si le préfixe figure dans ce catalogue **et** que tous les couples de chemins observés entre les deux origines divergent significativement (recouvrement de Jaccard sous 50 %, hors origine) — les deux signaux sont exigés ensemble, jamais un seul.

**Vérifié par :** `tests/test_as2org.py` (7 tests), `tests/test_moas_stability.py` (7 tests, y compris la contre-épreuve : sans historique, le même scénario est bien signalé), `tests/test_anycast.py` (14 tests, dont le téléchargement réel du catalogue exécuté pendant le développement). Sur le jeu de démonstration, le couple jumeau 37100/37105 ne produit plus d'événement ; l'unique MOAS restant est celui planté délibérément — rappel toujours 5/5.

---

## L7 — Fenêtre temporelle et données manquantes

**Le problème, en deux parties : un collecteur momentanément indisponible peut passer pour une chute de visibilité réelle, et les archives MRT sont publiées avec 5 à 15 minutes de retard minimum.**

**Remédiation implémentée pour les deux parties.**

**a) Exclusion des collecteurs inactifs.** `VisibilityDropDetector._active_rib()` croise la table RIB avec le flux de mises à jour (`context.elements`) : un collecteur sans aucun message réel sur la fenêtre est exclu du calcul, plutôt que de laisser son absence gonfler artificiellement une baisse de ratio. Le détecteur identifie en plus, par instantané, le nombre de collecteurs ayant effectivement rapporté ; un instantané incomplet (moins que le maximum observé sur la fenêtre) est écarté aussi bien du calcul de la référence que de l'évaluation d'une baisse.

**b) Granularité via RIS Live.** `etl.curate.curate_ris_live_window()` intègre une fenêtre RIS Live capturée (`ingestion.ris_live.capture`) dans la couche curée en quelques secondes, par fusion idempotente avec la partition du jour — sans attendre la publication de l'archive suivante. La commande `abrip detect watch` enchaîne capture, curation et détection en continu.

Précision assumée plutôt que dissimulée : c'est le **délai de disponibilité** de la donnée qui est réduit (de 5-15 minutes à quelques secondes), pas la **granularité d'analyse** des détecteurs eux-mêmes, qui continuent d'opérer au jour calendaire — une évolution plus profonde des signatures de `run_detection`/`build_context` serait nécessaire pour une détection véritablement sub-horaire, et dépasserait le cadre de cette remédiation.

**Vérifié par :** `tests/test_ris_live_curation.py` (4 tests, y compris la fusion avec une partition existante et l'idempotence sur rejeu) ; `abrip detect watch --minutes 0 --iterations 1` s'exécute de bout en bout sans erreur réseau requise.

---

## Résumé des vérifications

| Limite | Modules | Tests | Effet mesuré sur le jeu de démonstration |
|---|---|---|---|
| L1 | `enrichment/dataplane.py` | 17 | rétrogradation de sévérité fonctionnelle (verdict `inconclusive` en environnement isolé, comme attendu) |
| L2 | `analytics/metrics.py`, `etl/pch_parser.py`, `ingestion/broker.py` | 9 | `coverage_ratio` joint dans `metric_country` sans régression |
| L3 | `reference/peeringdb.py`, `reference/relationships.py` | 10 | événement valley-free plafonné à `watch` faute de corroboration |
| L4 | `reference/irr.py`, détecteurs MOAS/sous-préfixe, `analytics/metrics.py` | 15 | `metric_rpki_coverage` calculée sans régression |
| L6 | `reference/as2org.py`, `reference/anycast.py`, `anomaly/engine.py` | 28 | couple jumeau correctement supprimé, rappel 5/5 conservé |
| L7 | `anomaly/detectors.py`, `etl/curate.py` | 4 | curation idempotente, `abrip detect watch` opérationnel |

Rappel sur la vérité terrain après l'ensemble de ces changements : **toujours 5/5**, 16 événements et 8 incidents inchangés — aucune remédiation n'a dégradé la détection existante.
