# Analyse — optimisation du pipeline de données

Document d'analyse rédigé le 28/11/2026 après l'échec du run GitHub Actions
`46091918817`. Il compare les solutions pour le tri des partitions, le test des
parseurs optionnels et la parallélisation, puis fixe le plan recommandé.
**BGPStream est volontairement écarté** (voir § 5).

## 1. Incident et diagnostic

Séquence des trois runs du pipeline cloud :

| Run | Symptôme | Cause |
|---|---|---|
| `46085320440` | `repli de parseur`, puis `Aucune partition rib_snapshots` | Extras non installés → parseur **synthétique** ; seules les `updates` téléchargées |
| `46089078597` | `'Parser' object has no attribute 'parse_iter'` | API de `pybgpkit-parser` 0.24 changée |
| `46091918817` | `OutOfMemoryException` dans `sort_partition` après ~3 h | Tri DuckDB déborde sur le disque temporaire (72,2 GiB utilisés) |

Le troisième échec n'est **pas** un problème de parsing : l'ingestion et la curation ont bien tourné. Le message précis :

```
failed to offload data block of size 256.0 KiB (72.2 GiB/72.2 GiB used)
This limit was set by the 'max_temp_directory_size' setting.
```

`sort_partition` est réglé pour un portable : `memory_limit=1GB`, `threads=1`,
`temp_directory` local. Sur le runner GitHub (4 vCPU / 16 Go / 14 Go de SSD pour
un dépôt public), ce réglage est à la fois trop lent et trop gourmand en
déversement disque. Le tri ne modifie pas le contenu des données, seulement
l'ordre physique des lignes dans le Parquet.

## 2. DuckDB : état des lieux et leviers

La version verrouillée est `duckdb==2.0.1`. Elle inclut le **nouveau tri
k-way merge** introduit dans DuckDB 1.4 (septembre 2025) :

- ~2× plus rapide sur les tables larges, >3× au-delà de la mémoire ;
- adaptatif aux données déjà triées ;
- **mais ~30 % plus lent qu'avant en mono-thread**, et il scale avec les threads.

Le réglage actuel `SET threads = 1` est donc le pire cas pour cette version.

Leviers documentés par DuckDB :

| Option | Effet |
|---|---|
| `memory_limit` | bornes la RAM ; au-delà, DuckDB déverse sur `temp_directory` |
| `max_temp_directory_size` | limite le déversement disque (par défaut 90 % du disque disponible, d'où 72 GiB) |
| `temp_directory` | répertoire de déversement ; le fixer permet de le monitorer |
| `preserve_insertion_order = false` | réduit les buffers de réordonnancement lors des COPY Parquet |
| `threads` | parallelise le tri (4 sur un runner public) |

Sources : [Tuning Workloads](https://duckdb.org/docs/1.5/guides/performance/how_to_tune_workloads),
[Configuration](https://duckdb.org/docs/2.0/configuration/overview),
[Redesigning DuckDB's Sort, Again](https://duckdb.org/2025/09/24/sorting-again).

## 3. Polars : alternative réelle mais à benchmarker

Le projet verrouille `polars==2.1.0`. Depuis Polars 2.0, le moteur streaming et
l'exécution *out-of-core* sont activés par défaut : `sort`, `group_by` et les
fonctions fenêtre peuvent déverser sur disque au lieu de échouer. Polars 2.1
ajoute le group-by OOC et un seuil `POLARS_OOC_MEMORY_BUDGET_MB` ; le répertoire
de déversement se règle avec `POLARS_OOC_SPILL_DIR`.

Une implémentation possible serait :

```python
(
    pl.scan_parquet(paths)
      .sort(["prefix", "ts"])
      .sink_parquet(destination)
)
```

**Réserves** : l'issue Polars #30174 montre que le tri OOC peut être plus lent
qu'un tri manuel sur certains jeux (3 700 à 7 400 déversements pour 10 Go). Nos
lignes contiennent des colonnes imbriquées (`as_path`, `communities`), ce qui
mérite un benchmark avant adoption. Polars reste une piste d'avenir, pas le
correctif d'urgence.

Sources : [Polars 2.0](https://pola.rs/posts/release-polars-2/),
[Polars 2.1](https://plotly.com/blog/polars-2-1/),
[issue #30174](https://github.com/pola-rs/polars/issues/30174).

## 4. Décision retenue pour le tri

1. **Désactiver `sort_partitions` dans le pipeline cloud** (`ABRIP_ETL__SORT_PARTITIONS=false`). L'API utilise déjà `daily_prefix_origin`, `daily_adjacency` et `asn_prefix_stats` pour ses endpoints les plus coûteux ; le tri de `bgp_elements` n'est plus critique pour la majorité d'entre eux.
2. **Rendre le tri configurable** pour une réactivation future : `sort_threads`, `sort_max_temp_size` et `preserve_insertion_order=false` dans `sort_partition`, avec des valeurs par défaut inchangées pour le local.
3. **Réserve** : soit réactiver le tri avec ces réglages après benchmark, soit accepter un léger ralentissement des endpoints « fiche préfixe » qui retombent sur le calcul direct, soit ajouter une table dédiée pour eux.

## 5. Parseurs optionnels — et pourquoi pas BGPStream

Le bug `parse_iter` aurait dû être détecté avant la production. Le plan retenu :

- un **job CI dédié** qui installe `--all-extras` (`bgpkit` **et** `mrtparse`) ;
- un test qui lit un **vrai petit fichier MRT** public (exemple de la doc BGPKIT) et vérifie au moins un enregistrement normalisé pour chaque parseur ;
- le test est ignoré quand le fichier n'est pas fourni, pour ne pas alourdir la CI habituelle.

**BGPStream est écarté** : `pybgpstream` date de 2020 (2.0.2), n'a pas de wheel Linux récent, exige la librairie C `libBGPStream` installée depuis le dépôt apt de CAIDA, et sa compatibilité avec Python 3.14 n'est pas garantie. Le jeu de parseurs reste donc `bgpkit` (rapide, Rust), `mrtparse` (repli Python) et `synthetic` (démo/tests).

## 6. Limites GitHub Actions (2026)

Le chiffre de **900 minutes** souvent cité est obsolète. Selon la documentation officielle :

| Ressource | Plan Free |
|---|---|
| Minutes incluses | 2 000 min/mois ($12 de calcul) pour les dépôts **privés** |
| Dépôts publics | Gratuit et non mesuré |
| Jobs concurrents | 20 (Linux) |
| Durée max d'un job | 6 heures |
| Matrix | 256 jobs par run |
| Durée d'un workflow | 35 jours |
| Artefacts | 500 Mo |
| Cache | 10 Go par dépôt |

Sources : [GitHub Actions limits](https://docs.github.com/en/actions/reference/limits),
[Billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage).

Le dépôt ABRIP étant public, les minutes ne sont pas la contrainte. La vraie limite est le **job de 6 heures** : 7 jours × ~3 h = 21 h séquentiel.

## 7. Parallélisation par jour

Plan recommandé :

1. un job `dates` calcule la liste des jours (JSON) ;
2. un job `pipeline` avec `strategy.matrix.day` traite **un jour par job** (~3 h chacun, sous la limite de 6 h) et publie ses Parquet directement dans le dataset HF ;
3. un job `finalize` liste les fichiers du dataset via l'API Hugging Face, génère `manifest.json` et la carte de données, puis les téléverse.

Cela évite les conflits d'écriture sur le manifeste et n'utilise pas les artefacts (limités à 500 Mo).

## 8. Accélération du parsing

`pybgpkit-parser` expose `iter_tuple_batches(fields, batch_size=10_000)`, recommandé par sa documentation pour les grands fichiers : il réduit le nombre de crossings Python↔Rust en ne convertissant que les champs nécessaires. Champs à conserver pour `to_element_dict` : `timestamp`, `elem_type`, `peer_ip`, `peer_asn`, `prefix`, `as_path`, `next_hop`, `communities`, `med`, `local_pref`.

Source : [bgpkit-parser-py](https://github.com/bgpkit/bgpkit-parser-py).

## 9. Plan d'implémentation du lot recommandé

- [x] Document d'analyse (ce fichier).
- [ ] Configurer et désactiver le tri dans le workflow cloud.
- [ ] Ajouter le job CI des parseurs optionnels avec vrai MRT.
- [ ] Paralléliser le pipeline par jour (matrix + job de finalisation).
- [ ] Utiliser `iter_tuple_batches` dans `BgpkitParser`.
- [ ] Mettre à jour les tests et la procédure de déploiement.

## 10. Non retenu

- BGPStream (§ 5).
- Polars pour le tri maintenant : à benchmarker après déblocage.
- Réactiver le tri sans réglage : cause directe de l'OOM.
