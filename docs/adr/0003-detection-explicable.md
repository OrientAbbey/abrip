# ADR 0003 — Détection par règles explicables plutôt que par modèle appris

**Statut :** accepté
**Date :** 2026-09
**Portée :** `abrip.anomaly`

## Contexte

Détecter des anomalies de routage est un problème classique d'apprentissage non supervisé : on dispose de séries temporelles massives, de peu d'étiquettes, et d'anomalies rares. `IsolationForest`, un autoencodeur ou un modèle de série temporelle seraient des choix défendables, et donneraient au projet une apparence plus sophistiquée.

Deux obstacles s'y opposent, et ils sont de nature différente.

Le premier est méthodologique : il n'existe pas de jeu étiqueté d'incidents BGP africains. Sans étiquettes, un modèle appris ne peut être ni calibré ni évalué. On peut mesurer qu'il signale des points inhabituels ; on ne peut pas mesurer qu'il signale les bons.

Le second est opérationnel, et décide seul. Un ingénieur réseau qui reçoit une alerte a besoin de savoir quoi vérifier. « Score d'anomalie 0,87 » ne lui dit rien. « Le préfixe `197.155.64.0/22` est annoncé depuis 09h12 par AS45090, alors que le ROA AFRINIC autorise uniquement AS37100, et cinq peers sur trois collecteurs concordent » lui dit exactement où regarder. Une alerte qu'on ne peut pas justifier ne sera pas traitée ; elle sera ignorée, puis désactivée.

## Décision

Sept détecteurs à règles, chacun ciblant un mécanisme de routage nommé : MOAS, sous-préfixe, invalide RPKI, violation valley-free, pic d'instabilité, chute de visibilité, bogon.

Chaque détecteur produit un **candidat**, jamais une affirmation, composé de :

- un **score** entre 0 et 1, issu du mécanisme propre au détecteur ;
- une **confiance** (`low`/`medium`/`high`) dérivée du nombre de points de vue concordants — et non du score, car ce sont deux dimensions indépendantes : un signal net vu par un seul peer reste fragile ;
- les **preuves** qui l'ont déclenché, conservées dans l'événement ;
- une **explication en français**, rédigée à partir des preuves.

La seule statistique employée est le **score z robuste** (médiane et écart absolu médian, facteur 1,4826). Ce n'est pas un modèle appris : c'est une mesure de dispersion résistante aux valeurs extrêmes, choisie parce que le churn BGP est très asymétrique et qu'un écart-type classique, gonflé par un premier pic, masquerait les suivants.

Un moteur de **corrélation** regroupe ensuite les événements pointant le même préfixe dans la même fenêtre, et rehausse le score quand des détecteurs indépendants concordent.

Les seuils sont dans `configs/detection.yaml`, jamais dans le code.

## Conséquences

**Bénéfices.** Chaque alerte est justifiable ligne à ligne. Les seuils s'ajustent sans redéploiement. La détection est déterministe : les mêmes données produisent les mêmes événements, avec les mêmes identifiants UUID — ce qui rend le pipeline rejouable et l'ingestion idempotente. Le générateur de démonstration fournit une vérité terrain plantée, donc un rappel mesurable : le test exige 5/5 et interdit à un réglage de seuil de casser la détection en silence.

**Coûts.** Les détecteurs ne trouvent que ce qu'on leur a appris à chercher. Un mécanisme d'attaque non prévu passe inaperçu — c'est la limite structurelle d'une approche par règles, et elle est réelle. Ajouter un mécanisme demande d'écrire un détecteur, là où un modèle appris pourrait en théorie généraliser.

**Faux positifs attendus.** MOAS et sous-préfixe produisent du bruit : l'anycast et le multihoming légitime en génèrent en permanence. C'est précisément pourquoi la validation RPKI est intégrée en renfort, et pourquoi la corrélation existe.

## Évolution prévue

L'approche par règles n'exclut pas l'apprentissage — elle le prépare. Les événements accumulés, avec leurs preuves et leur qualification, constituent le jeu étiqueté qui manque aujourd'hui. Un modèle entraîné dessus serait évaluable, et pourrait servir à hiérarchiser les candidats plutôt qu'à les produire. Dans ce sens, l'apprentissage viendrait après la détection, jamais à sa place.

## Alternatives écartées

**`IsolationForest` sur les séries de churn.** Écartée : non évaluable sans étiquettes, et produit un score sans justification exploitable.

**Seuils fixes en dur** (« plus de 100 mises à jour par heure »). Écartée : un seuil absolu est ingérable sur des préfixes dont les volumes de référence diffèrent de trois ordres de grandeur. La référence doit être propre à chaque préfixe, d'où le score z robuste.

**S'appuyer uniquement sur RPKI.** Écartée : `not-found` est le statut majoritaire dans la zone AFRINIC. Une détection qui n'agirait que sur les invalides serait aveugle sur la majorité du périmètre visé.
