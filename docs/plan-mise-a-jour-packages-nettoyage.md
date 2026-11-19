# Plan — mise à jour des packages et nettoyage du projet

**Branche de travail :** `chore/package-refresh-project-cleanup` (créée depuis `dev_cl`, base `5f69a43`)  
**Cible Python :** 3.12 exclusivement dans l’environnement de travail `.venv/`  
**État :** plan établi avant les changements fonctionnels ou de dépendances.

## Objectifs et règles

- Mettre à jour les dépendances Python et frontend vers les versions stables récentes compatibles, puis enregistrer les versions résolues de façon reproductible.
- Installer, vérifier et exécuter les commandes Python uniquement avec `.venv` créée avec Python 3.12 ; ne pas installer dans l’interpréteur global.
- Nettoyer les fichiers temporaires/caches et les incohérences manifestes sans supprimer les sources, données de l’utilisateur, fichiers de configuration ou rapports utiles.
- Garder les tests, le lint, le typecheck, la construction frontend, la démo et la CI comme critères d’acceptation. Corriger les régressions causées par les mises à jour plutôt que de les masquer.
- Ne pas pousser ni fusionner sans demander confirmation ; préserver les modifications préexistantes.

## Suivi des étapes

- [x] **0. Établir le plan** — ce document est créé avant toute modification aux dépendances ou au code.
- [x] **1. Établir l’état initial** — confirmer branche/arbre propre, version Python de `.venv`, versions installées et état des tests/lint/build pertinents ; noter les éventuels échecs préexistants. Branche et HEAD confirmés (`dev_cl`, `5f69a43`) ; environnement `.venv` confirmé sur Python 3.12.10. La capture des versions montrait plusieurs paquets installés plus anciens que les pins du projet (polars 1.44.2, duckdb 1.5.5, fastapi 0.141.1, etc.).
- [x] **2. Définir les mises à jour** — versions stables publiées vérifiées (PyPI et npm) : la plupart des pins étaient déjà à jour. Seules mises à jour retenues : `fastapi` 0.163.1 → 0.163.2, `websockets` 17.2 → 17.4, extras `pybgpkit-parser==0.24.0` et `mrtparse==2.2.0` épinglés, `uv.lock` créé (55 paquets, Python ≥3.12,<3.15). Côté npm, `recharts` 3.11.0 a été testé puis écarté (budget).
- [x] **3. Mettre à jour Python** — `uv sync --all-extras` a synchronisé `.venv` (38 paquets installés/mis à jour) ; `pip check` : aucune dépendance cassée. Un résidu `mypy-2.3.1.dist-info` sans `RECORD` a été retiré à la main après la mise à jour vers mypy 2.4.1.
- [x] **4. Mettre à jour le frontend** — `recharts` 3.11.0 a été essayé puis **rejeté** : il fait passer le chunk `charts` de 122 → 136 Ko gzip et le total CI à 259 569 octets, au-delà du budget de 256 000. Retour à 3.10.1 (245 739 octets = 240 Ko) ; `package-lock.json` reste donc inchangé. `npm run typecheck` et `npm run build` réussis.
- [x] **5. Nettoyer prudemment** — caches régénérables supprimés (`.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `frontend/tsconfig.tsbuildinfo`) ; `data/`, `.venv/`, `node_modules/`, `dist/` et `src/abrip.egg-info/` laissés en place. Documentation corrigée : README « Python 3.11+ » → « 3.12+ » et note `uv sync`. `ruff format` appliqué aux 7 fichiers qui n'étaient pas conformes à la version 0.17.5 (formatage seul).
- [x] **6. Vérifier** — Ruff (lint + format), Mypy, `pytest` complet, `demo verify`, typecheck/build frontend, budget gzip mesuré comme la CI, `pip check`, `uv lock --check` : tout passe.
- [x] **7. Revue et clôture** — diff relu, état Git et versions finales vérifiés, suivi mis à jour. Reste à commiter/pousser/ouvrir la PR sur confirmation.

## Critères de fin

1. `python`/`pip` utilisés pour le projet proviennent de `.venv` en Python 3.12.
2. Les dépendances sont à jour, compatibles avec la CI et résolues de manière reproductible.
3. Tous les contrôles applicables passent, ou chaque échec restant est décrit précisément avec sa cause.
4. Aucun fichier source/donnée utile n’a été supprimé au titre du nettoyage.
5. Le diff ne contient que les mises à jour, corrections indispensables, nettoyage sûr et ce plan de suivi.

## Journal d’exécution

| Étape | Résultat |
|---|---|
| 0 | Plan créé avant les changements aux packages/code. |
| 1 | `.venv` en Python 3.12.10 ; pins du projet plus récents que l’environnement installé (polars 1.44.2 vs 2.1.0, duckdb 1.5.5 vs 2.0.0, fastapi 0.141.1 vs 0.163.x). |
| 2 | Versions stables vérifiées ; mises à jour retenues : fastapi 0.163.2, websockets 17.4, extras bgpkit/mrt épinglés ; `uv.lock` généré (55 paquets). Frontend inchangé (voir étape 4). |
| 3 | `uv sync --all-extras` : 38 paquets installés, `pip check` propre ; résidu `mypy-2.3.1.dist-info` supprimé. |
| 4 | recharts 3.11.0 testé : chunk `charts` 136 Ko gzip, total 259 569 octets > 256 000 → **revert à 3.10.1**. Mesure finale identique à la CI (`gzip -c` par fichier, octets bruts) : **245 739 octets = 240,0 Ko**, marge 10 261 octets. Aucun changement frontend conservé. |
| 5 | Caches supprimés ; README (Python 3.12+, note `uv sync`) ; `ruff format` sur 7 fichiers non conformes. |
| 6 | `ruff check` : All checks passed ; `ruff format --check` : 79 fichiers conformes ; `mypy src` : 51 fichiers sans erreur ; `demo verify` : 5/5, recall 1.0 ; `pytest -q` : **728 passed** en 25 min 28 s ; `pip check` propre ; `npm run typecheck` et `npm run build` OK ; `uv lock --check` : 55 paquets cohérents. |
| 7 | Diff relu : 7 fichiers modifiés + `uv.lock` et ce plan ajoutés ; aucun fichier source/donnée supprimé. Commit/push/PR en attente de confirmation. |
