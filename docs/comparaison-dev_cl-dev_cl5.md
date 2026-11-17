# Comparaison des branches `dev_cl` et `dev_cl5`

**Date de la revue :** 2026-11-17  
**Branches examinées :** `dev_cl` à `14bedd5` et `dev_cl5` à `12fd25a`  
**Base commune :** `12e536c`  
**Statut :** revue comparative, aucun changement fonctionnel fusionné pendant cette analyse.

## Synthèse

`dev_cl5` n'est pas une branche strictement en avance sur `dev_cl`. Les deux branches ont divergé depuis `12e536c`. `dev_cl` contient ensuite l'intégration importante `c4cf1e6` (explorateurs ASN/pays, API et calculs journaliers, performances, propagation, historiques, etc.), ainsi que la détection des répertoires de démonstration (`b5a9099`) et les correctifs de portabilité (`14bedd5`). `dev_cl5` contient une autre série de commits et une variante de plusieurs fichiers.

Le diff `dev_cl...dev_cl5` comprend **42 fichiers modifiés, environ 3 845 insertions et 82 suppressions**. Le diff direct `dev_cl` vers `dev_cl5` compte de nombreuses suppressions : il ne faut donc pas le fusionner comme s'il ne faisait qu'ajouter des fonctionnalités. Certaines suppressions sont le résultat de sa base plus ancienne, d'autres correspondent à de vrais changements/remplacements à comparer.

La comparaison OpenAPI montre **54 routes sur `dev_cl` contre 53 sur `dev_cl5`**. Des chemins sont renommés (`neighbours` → `neighbors`, historique IRR `route-history` → `route-object-history`), et certaines opérations de `dev_cl` ne sont plus exposées sous le même contrat dans `dev_cl5` (noms ASN, listes paginées de préfixes, relations pays, upstreams). À valider avec les consommateurs avant toute adoption.

**Conclusion préliminaire : conserver `dev_cl` comme branche de référence.** Des idées de `dev_cl5` peuvent être reprises sélectivement, mais il n'y a pas de preuve que sa version complète soit globalement meilleure. Ne supprimer aucune des deux branches avant d'avoir décidé du sort des changements exclusifs et, idéalement, intégré la branche retenue à `main`.

## Fonctionnalités et qualité de l'interface

### Apports intéressants de `dev_cl5`

- La fiche ASN est réorganisée en sections/onglets Préfixes, Voisins, Transit, Activité et Événements.
- Les panneaux ASN préfixes et voisins sont réutilisables aussi depuis les fiches pays : `frontend/src/components/AsnPrefixesPanel.tsx` et `AsnNeighborsPanel.tsx`.
- Les panneaux ajoutent des vues de changement et des modales d'historique (ROA/objets route, annonces et relations IPv4/IPv6 selon le panneau).
- La navigation par pages est chargée de manière différée dans `frontend/src/App.tsx` sur **les deux branches** ; ce n'est donc pas un avantage propre à `dev_cl5`. Le gain n'a pas été mesuré.
- `CountryDetail.tsx` est présent dans les deux branches et offre à `dev_cl5` une fiche pays plus intégrée aux panneaux préfixes/voisins réutilisés ; en revanche, les routes pays ne sont pas identiques, et `dev_cl` expose entre autres la relation agrégée que `dev_cl5` ne reprend pas sous le même chemin.
- Le rejeu de propagation est représenté par des composants séparés (`PropagationReplay.tsx`, `PropagationSvg.tsx`) et a un moteur backend dédié. Le rejeu existe déjà dans `dev_cl`; l'apport de `dev_cl5` est une autre implémentation, pas l'introduction de la fonctionnalité. **Bilan de la comparaison détaillée :** l'implémentation de `dev_cl5` retire des contrôles du graphe instantané (seuil d'observations, repli hors Afrique, focus, alertes, exports SVG/PNG/CSV, lien partageable) et du rejeu (clavier, sauts entre changements, événements détectés, comparaison des liens avec le début de fenêtre). L'implémentation de `dev_cl` est plus complète sur ces parcours.

### Fonctions à ne pas perdre de `dev_cl`

- Les explorateurs de préfixes et voisins de `dev_cl` ont des tableaux paginés, filtres et informations détaillées qui ne sont pas repris à l'identique dans les nouveaux panneaux de `dev_cl5`.
- La période partagée sur la fiche ASN de `dev_cl` devient une sélection de dates locale aux panneaux dans `dev_cl5`.
- Le graphe de propagation de `dev_cl` a des commandes supplémentaires relevées dans la revue : repli des AS hors Afrique, focus, seuils d'observations, alertes, exports SVG/PNG/CSV et copie d'un lien partageable.
- Le rejeu de `dev_cl` fournit davantage de navigation et de contexte : focus, navigation clavier, sauts vers les changements de topologie, événements détectés et comparaison des liens avec le début de fenêtre. Ces fonctions ne sont pas toutes présentes dans la variante `dev_cl5`.

### Accessibilité

La revue des composants identifie une régression à éviter si l'on reprend les composants de `dev_cl5` : les onglets y exposent `aria-pressed` au lieu de l'état `aria-selected` attendu par le rôle `tab`, et la liste d'onglets n'a pas de nom accessible. Dans les modales, `dev_cl` place le focus à l'ouverture et fournit un libellé accessible au bouton de fermeture ; ces points ne sont pas repris complètement par `dev_cl5`. Les deux versions gagneraient à compléter la gestion du focus (piège et restauration).

Aucun test frontend d'interaction/accessibilité n'a été identifié lors de cette revue. `typecheck` et `build` ne suffisent pas à valider ces parcours.

## Backend, API et risques de régression

La branche `dev_cl5` remplace notamment l'organisation autour de `asn_explorer.py` et `propagation.py` par `topology.py`, et ajoute/retouche les endpoints de topologie. La comparaison statique relève les points suivants, qui doivent être confirmés par des tests avant tout portage :

1. **Rejeu et types d'éléments MRT (problème commun aux deux branches) :** les endpoints de rejeu de `dev_cl5` (`topology.py`) et de `dev_cl` (`propagation.py`) sélectionnent `elem_type` sans exclure `R`, tandis que leur moteur traite tout type autre que `W` comme une annonce. La curation PCH place explicitement des éléments `R` dans `bgp_elements` (confirmé dans `etl/curate.py` et `etl/pch_parser.py`). Les deux branches présentent ce risque de correction, qui mérite un test et une décision métier, mais **ce n'est pas un défaut différentiel permettant de les départager**. Il faut décider si les RIB doivent amorcer l'état ou être filtrés, puis ajouter un test avec un cas PCH.
2. **Borne temporelle de fin (défaut différentiel reproduit) :** dans `dev_cl5`, `_prefixes_timeseries` compare `ts <= date_to` directement. Pour une date `YYYY-MM-DD`, FastAPI la convertit en minuit : la requête `GET /api/asns/37100/prefixes/timeseries?from=2026-08-27&to=2026-08-27` renvoie `points: []`, alors que les données contiennent ce jour-là **425 enregistrements d'annonce couvrant 2 préfixes distincts** pour cet AS. Avec une borne exclusive au lendemain, la série retourne les 2 préfixes. Le calcul direct correspondant dans `dev_cl` utilise `ts < d1 + INTERVAL 1 DAY`. Défaut confirmé dans l'endpoint et à couvrir par un test ; ne pas reprendre la borne de `dev_cl5` telle quelle.
3. **Agrégation MOAS :** `_prefixes_changes` construit les jours observés par préfixe, mais conserve un unique `origin_of[prefix]` qui est écrasé pour chaque ligne ; en périmètre pays, un MOAS peut ainsi être attribué arbitrairement au dernier AS rencontré. Le `SELECT DISTINCT` ne garantit pas l'ordre des origines. À tester/résoudre (représenter plusieurs origines ou définir explicitement la sémantique).
4. **Origines courantes :** `_current_origins` cherche les annonces du préfixe dans la fenêtre `[max(ts) global - 1 jour, max(ts) global]`. Un préfixe toujours annoncé mais observé avant cette fenêtre peut être omis si d'autres préfixes ont des timestamps plus récents. Comparer avec une notion par préfixe ou une fenêtre définie pour le jeu entier.
5. **Compatibilité API :** la comparaison des schémas OpenAPI confirme des chemins absents/renommés entre les versions. En particulier, `dev_cl5` expose `/neighbors` à la place de `/neighbours`, `/prefixes/changes` mais pas les listes `/prefixes` filtrables/paginées de `dev_cl`, et `/prefixes/{prefix}/route-object-history` à la place de `/route-history`. Les noms ASN, préfixes pays, relations pays et upstreams n'ont pas non plus tous un chemin équivalent évident. La réponse de propagation diffère également (informations pondérées et annotations RPKI/valley-free notamment). Ce sont des changements de contrat concrets à documenter et tester avec les consommateurs avant adoption.
6. **Volume/performance :** `dev_cl` possède les calculs journaliers `daily_prefix_origin` et `daily_adjacency`, le tri des partitions, `etl compact` et des mesures documentées dans `docs/performances.md`. Ces éléments ne sont pas conservés dans l'état `dev_cl5` examiné. Les nouvelles routes de voisins paraissent matérialiser davantage de données en Python ; mesurer mémoire et latence sur des volumes réalistes avant de reprendre leur approche.

Ces points sont des **risques issus de la revue statique**, pas tous des défauts reproduits. Ils ne doivent pas être présentés comme des bugs confirmés tant que les tests correspondants n'ont pas été exécutés.

## Vérifications disponibles et limites

- Pour `dev_cl`, les vérifications précédentes de la branche ont donné : **715 tests Python passés**, Ruff, Mypy sur 50 fichiers, `pip check`, typecheck/build frontend et budget gzip sous 256 000 octets. Le job Docker n'avait pas pu être lancé localement (Docker indisponible).
- Pour `dev_cl5`, Ruff a passé et `tests/test_replay.py` a donné **12 passed**. Le bootstrap de démonstration, dans un répertoire de données isolé, a produit 18 617 éléments curés sur 7 jours ; `abrip demo verify` a confirmé **5/5 anomalies plantées (rappel 1,0)**. Après avoir relancé le bootstrap au chemin par défaut attendu par les tests, la suite complète a donné **203 passed, 1 failed, 5 skipped**. L'unique échec restant est `TestPrecedence.test_environnement_prime_sur_yaml` : le test compare `/tmp/abrip-test` à `C:/tmp/abrip-test` sous Windows. C'est un échec de portabilité du test/chemin sur cet environnement, pas une défaillance fonctionnelle de l'application ; les autres tests passent. La première exécution complète avec le répertoire de données explicite avait donné 198 passed, 6 failed, les cinq échecs supplémentaires étant dus au bootstrap non placé dans le répertoire par défaut et à la normalisation Windows du chemin de traversal URL.
- Le worktree détaché de revue est `C:\Users\FRANCIS\AppData\Local\Temp\opencode\abrip-dev_cl5-review` ; les données explicites isolées sont dans `C:\Users\FRANCIS\AppData\Local\Temp\opencode\abrip-dev_cl5-data`. Mypy a dépassé le délai de 600 secondes dans cette exécution ; aucune conclusion n'en est tirée.
- Frontend `dev_cl5` : `npm ci`, `npm run typecheck` et `npm run build` ont réussi ; total gzip des JS/CSS **205 276 octets**, sous le budget de 256 000. Vite signale néanmoins un chunk `charts` de 418 kB minifiés (119,55 kB gzip) au-dessus de son seuil d'avertissement. Les parcours d'interface et l'accessibilité n'ont pas de tests interactionnels relevés.
- Le CLI `dev_cl5` n'a pas de commande `demo check` (son aide expose `bootstrap` et `verify` seulement) ; cette commande ne doit pas être requise pour ce commit. Ne pas faire pointer `dev_cl5` vers les données de `dev_cl` : les essais utilisent les seules données du worktree ou le répertoire isolé.

## Recommandation de portage

1. **Ne pas fusionner `dev_cl5` en bloc dans `dev_cl` et ne pas remplacer les fichiers courants par ceux de `dev_cl5`.** Le diff contient des remplacements et des retraits de fonctionnalités.
2. Sélectionner les améliorations d'interface jugées utiles (notamment fiche pays et panneaux réutilisables) et les porter par petits changements, en conservant les contrats, filtres, exports et fonctions de graphe de `dev_cl`. Le lazy loading est déjà présent dans les deux branches et ne nécessite pas de portage.
3. Pour le rejeu, comparer les deux implémentations à l'aide de fixtures couvrant annonces, retraits, RIB/PCH, changement d'origine, MOAS, limites de dates, fenêtres vides et plusieurs préfixes. Ne reprendre que les modifications démontrant une correction ou un bénéfice mesurable.
4. Ajouter des tests de compatibilité API et d'interface/accessibilité avant d'intégrer les changements concernés. Garder les tables journalières, optimisations et protections de démo de `dev_cl`.
5. Après portage : suite Python complète, Ruff, Mypy, les commandes de démo disponibles dans la branche cible (`demo verify` et, si présent, `demo check`), typecheck/build et budget frontend ; vérifier également le job image Docker sur CI.

**Décision suggérée aujourd'hui :** `dev_cl` est la base à garder. `dev_cl5` est une source d'idées et de variantes à évaluer, pas une branche de remplacement prête à fusionner. La comparaison ne justifie pas encore sa suppression tant que ses changements exclusifs n'ont pas été formellement écartés ou portés.
