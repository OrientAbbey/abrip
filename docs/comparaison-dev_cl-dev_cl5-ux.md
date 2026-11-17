# Comparaison UX — `dev_cl` vs `dev_cl5`

**Date :** 2026-11-17  
**Branches comparées :** `dev_cl` dans son état courant (la branche de travail contient les commits de suivi UI `fe2716a`, `4b43722`, `c1dfbdc`, `c11cc16`, `f59ffaa`, non encore fusionnés dans `dev_cl`) et `dev_cl5` au commit `12fd25a`.  
**Méthode :** revue statique des deux frontends, complétée par une inspection des pages servies localement (`dev_cl` sur le port 8000, `dev_cl5` sur le port 8001). Le rapport `comparaison-dev_cl-dev_cl5.md` décrivait `dev_cl` avant les commits cités plus haut : ses constats d'accessibilité sont donc actualisés ici.

## Synthèse

**`dev_cl` est nettement devant sur le plan UX.** La différence ne tient pas au style visuel mais à trois choix structurants : des fiches segmentées en sections adressables par URL, des compteurs et de la pagination avant le clic, et une accessibilité au clavier réellement conforme. `dev_cl5` reste une variante « tout sur une page » plus simple à premier abord, mais elle perd en chemin la plupart des repères dont un analyste a besoin.

Aucune idée UX propre à `dev_cl5` n'est irremplaçable : les apports utiles ont déjà été portés sélectivement (fiche pays en sections, résumé des préfixes annoncés, vocabulaire des historiques, compteurs d'onglets). Les éléments restants sont des appauvrissements.

## 1. Architecture de l'information et navigation

- La navigation globale est identique : mêmes six liens, même `nav aria-label`, même chargement paresseux des pages (`components/Layout.tsx`, `App.tsx` des deux branches). Ce n'est pas un différentiel.
- **`dev_cl` segmente, `dev_cl5` empile.** La fiche ASN passe de six cartes consécutives dans `dev_cl5` (`pages/AsnDetail.tsx:78-235`) à cinq sections à onglets dont une seule est rendue dans `dev_cl` (`pages/AsnDetail.tsx:45-56,121-290`). La fiche pays passe d'une page unique (`dev_cl5:pages/CountryDetail.tsx:20-70`) à trois sections (`pages/CountryDetail.tsx:17-24,140-224`), avec chargement conditionnel des données non affichées (`:97-104`). Gain : moins de défilement et moins de requêtes pour une vue donnée.
- **État partageable.** `dev_cl` conserve la section dans `?section=` (`pages/AsnDetail.tsx:64-78`, `pages/CountryDetail.tsx:85-93`) et l'état du graphe dans `g_*` (`components/PropagationGraph.tsx:57-66`). `dev_cl5` ne conserve que `q`/`offset` et quelques filtres d'événements : un lien partagé vers « Voisins » ou vers une vue de graphe ne survit pas à un rechargement.
- **Découvrabilité.** Les onglets `dev_cl` portent des compteurs calculés en un seul appel (`components/PrefixExplorer.tsx:198-219` pour les préfixes, `components/NeighbourExplorer.tsx:145-168` pour les voisins) : on voit « New 1 » ou « IPv4 6 » sans cliquer. Aucun compteur dans les panneaux `dev_cl5` (`AsnPrefixesPanel.tsx:20-35,83,99`).
- **Exception en faveur de `dev_cl5` :** sa fiche pays montre directement les panneaux préfixes/voisins (`CountryDetail.tsx:63-69`). `dev_cl` a toutefois porté la réutilisation des explorateurs pour `asn` **ou** `country` (`PrefixExplorer.tsx:180-190`, `NeighbourExplorer.tsx:128-137`). Quant au bouton « tendance » de la liste des pays dans `dev_cl5` (`pages/Countries.tsx:131,149-180`), la section `?section=overview` de `dev_cl` couvre le même besoin avec une URL partageable.

## 2. Qualité d'interaction

| Dimension | `dev_cl` | `dev_cl5` |
|---|---|---|
| États chargement / erreur / vide | Composant commun, avec remède explicite (« Élargissez la période, ou changez d'onglet », `StateBlock.tsx:1-70`, `PrefixExplorer.tsx:251-253`) | Simples `<p className="muted">` (`AsnPrefixesPanel.tsx:86-87,102-103`) |
| Pagination | 25 lignes, « 26–50 sur 312 », boutons désactivés aux bornes (`PrefixExplorer.tsx:321-329`) ; résumé « 25 premiers sur N » sur la fiche ASN | Toutes les lignes rendues sans limite ni compteur (`AsnPrefixesPanel.tsx:119-174`) ; la fiche ASN laisse croire que ses 25 lignes sont exhaustives (`pages/AsnDetail.tsx:92-104`) |
| Période | Sélecteur commun avec bornes `min/max` et préréglages 7 j / 30 j / Tout (`DateRangeSelector.tsx:16-20,62-94`) ; le brush du graphe modifie la période et le tableau suit (`PrefixExplorer.tsx:228-243`) | Picker local par panneau, sans bornes ni préréglage ni brush (`DateRangePicker.tsx:19-52`) |
| Historiques | Trois modales nommées (ROA, objet route, périodes) avec notes et frise quotidienne (`PrefixExplorer.tsx:68-178`) | Boutons « Voir » répétés sans contexte (`AsnPrefixesPanel.tsx:130-166`, `AsnNeighborsPanel.tsx:138-148`) |
| Tri de tableaux | Aucun tri par colonne ; tri serveur sur Événements (`pages/Events.tsx:95-102`) | Idem — pas de différentiel |
| Exports / partage | SVG, PNG, CSV et « Copier le lien » (`PropagationGraph.tsx:181-217`) ; état du graphe dans l'URL | Aucun export, aucun lien partageable du graphe |
| Rejeu | Vitesse, sauts « Changement ◂/▸ », repères d'événements, comparaison des liens avec le début, focus (`PropagationReplay.tsx:230-255,305-333,383-430`) | Lecture / pas à pas / vitesse seulement (`dev_cl5:PropagationReplay.tsx:147-215`) |

Sur `PrefixDetail`, `dev_cl` ajoute la période partagée, le filtrage de la visibilité et le graphe des fournisseurs amont (`pages/Prefixes.tsx:165-170,180-183,199-200,275-281`), absents de `dev_cl5` (`dev_cl5:pages/Prefixes.tsx:155-189`).

## 3. Accessibilité

- **Onglets : `dev_cl5` est en régression.** `dev_cl` implémente le motif ARIA complet : `role="tablist"` + `aria-label`, `aria-selected`, `tabindex` mobile, flèches gauche/droite et Début/Fin (`components/Tabs.tsx:42-77`), compteur annoncé dans le libellé. `dev_cl5` utilise `aria-pressed` sur des éléments `role="tab"`, sans nom sur la liste ni navigation clavier (`dev_cl5:components/Tabs.tsx:22-36`).
- **Modales : régression également.** `dev_cl` place le focus dans le dialogue, le confine, le restaure à l'ouvrant, gère Échap et nomme le bouton de fermeture (`components/Modal.tsx:33-73,88-90`). `dev_cl5` ne gère que Échap et le clic sur le fond, sans piège ni restauration, avec un « Fermer » sans `aria-label` (`dev_cl5:components/Modal.tsx:16-35`).
- **Graphe.** Nœuds focalisables avec `role="button"`, `aria-pressed`, infobulle et `onKeyDown` dans `dev_cl` (`PropagationSvg.tsx:193-202`), contre un simple `role="img"` dans `dev_cl5` (`dev_cl5:PropagationSvg.tsx:62-63`). Le lecteur de rejeu `dev_cl` documente ses raccourcis et ignore les touches saisies dans un champ (`PropagationReplay.tsx:281-303`).
- **Noms accessibles.** Boutons d'historique nommés (`aria-label="Historique d'annonce de …"`, `PrefixExplorer.tsx:306-315`, `NeighbourExplorer.tsx:248-256`) contre des « Voir » indifférenciés dans `dev_cl5`. Glossaire structuré et navigable au clavier dans `dev_cl` (`components/Term.tsx:6-27`, `lib/glossary.ts:1-8`) contre une icône ⓘ à `title` natif (`dev_cl5:components/Info.tsx:1-11`).
- Les badges de sévérité ne reposent pas sur la couleur seule dans les deux branches (`dev_cl5:components/Badges.tsx:16-25`).

## 4. Langage, unités, sémantique

- Le port récent a aligné les deux branches sur les historiques : « Première vue » / « Dernière vue », `Active` dans la dernière vue au lieu d'une colonne « État », et code CAIDA brut `p2c` / `c2p` / `p2p` dans l'historique de relation (`components/PeriodsTable.tsx:26-42`, `lib/format.ts:103-112`, `components/NeighbourExplorer.tsx:63-65` ; `dev_cl5:PeriodsTable.tsx:3-7,24-35`).
- `dev_cl` accompagne ces codes d'une légende et de libellés explicites (« Fournisseurs — relation CAIDA : fournisseur », `NeighbourExplorer.tsx:41-47,90-94`) ; `dev_cl5` affiche des libellés français dans le tableau puis des codes bruts sans explication dans la modale (`dev_cl5:AsnNeighborsPanel.tsx:132`) : incohérence interne.
- `dev_cl` traduit les statuts RPKI/IRR (« valide / invalide / aucun ROA », « présent / incohérent / aucun ») et date chaque ligne « Vu du — au » (`PrefixExplorer.tsx:56-61,264,293-295`) ; `dev_cl5` réduit tout à « Voir » ou « — » sans plage (`dev_cl5:AsnPrefixesPanel.tsx:128-170`).
- `dev_cl5` écrit « Première vue (UTC) / Dernière vue (UTC) » pour des valeurs qui sont des **jours** sans heure (`dev_cl5:PeriodsTable.tsx:24-35`) : l'unité annoncée est trompeuse. `dev_cl` réserve le suffixe UTC aux horodatages réels (`lib/format.ts:24-30`). Vocabulaire également moins stable dans `dev_cl5` (`Tout` vs `Tous`, onglets anglais traduits différemment selon le panneau).

## 5. Idées propres à `dev_cl5` — et verdict

À considérer, mais déjà couvertes : (a) fiche pays « tout sur une page » → portée sous forme de sections avec URL partageable ; (b) aperçu de la tendance depuis la liste des pays → remplacé par une section `?section=overview` ; (c) noms AS2Org fournis par l'API → déjà affichés globalement par `AsnLink.tsx:10-17`.

Régressives ou redondantes : suppression de la pagination et des compteurs, perte du brush, `aria-pressed`, modales sans focus, boutons « Voir » génériques, graphe dégarni (seuils, repli hors Afrique, focus, alertes, exports, lien), rejeu sans clavier ni sauts, absence de glossaire, tables non bornées.

**Conclusion UX :** aucun motif bloquant ne justifie de conserver `dev_cl5`. Les seules raisons possibles de la garder relèvent du backend et des contrats API, traitées dans `comparaison-dev_cl-dev_cl5-backend.md`.
