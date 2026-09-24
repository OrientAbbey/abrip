# ADR 0002 — Parquet partitionné et DuckDB plutôt qu'un serveur de base de données

**Statut :** accepté
**Date :** 2026-09
**Portée :** `abrip.storage`, `abrip.api.deps`

## Contexte

La plateforme produit trois couches de données : les archives brutes, les éléments BGP normalisés, et les métriques et événements. Le volume est significatif — une journée de mise à jour sur sept collecteurs représente plusieurs millions de lignes — mais la charge de lecture est faible : quelques requêtes analytiques, pas de transactions concurrentes, pas d'écriture depuis l'interface.

Le choix par défaut dans ce contexte serait PostgreSQL ou TimescaleDB. Ce réflexe mérite d'être questionné : un serveur de base de données apporte des garanties transactionnelles, de la concurrence en écriture et un contrôle d'accès. Aucune des trois n'est requise ici.

À l'inverse, il impose un serveur à installer, administrer, sauvegarder et maintenir en vie, et rend le déploiement dépendant d'une ressource externe qu'un hébergement gratuit facture presque toujours.

## Décision

**Stockage en Parquet partitionné**, sur le système de fichiers, avec une hiérarchie explicite :

```
data/curated/bgp_elements/date=2026-08-27/collector=rrc19/part-0000.parquet
```

**Lecture en SQL via DuckDB**, qui interroge directement les fichiers sans import préalable :

```sql
SELECT prefix, count(*) FROM read_parquet('data/curated/bgp_elements/*/*/*.parquet')
WHERE date = '2026-08-27' GROUP BY 1
```

**Un catalogue DuckDB léger** (`catalog.duckdb`) conserve uniquement les métadonnées : fichiers ingérés avec leur empreinte SHA-256, exécutions, partitions enregistrées. C'est ce qui rend l'ingestion idempotente sans relire les données elles-mêmes.

**L'API est strictement en lecture.** Elle ouvre DuckDB en mode lecture seule sur des motifs de chemins. Toute production de données passe par la ligne de commande.

## Conséquences

**Bénéfices.** Aucun serveur à administrer : `git clone`, `pip install`, et les données sont interrogeables. Le partitionnement par date permet d'élaguer les fichiers avant lecture, donc de ne charger que ce qui est nécessaire — c'est ce qui tient le budget mémoire sur une machine à 8 Go. Les fichiers Parquet sont lisibles par pandas, Polars, DuckDB, Spark ou tout moteur compatible Arrow : les données survivent à la plateforme. La réécriture d'une partition est atomique (écriture dans un fichier temporaire puis renommage), ce qui rend une journée rejouable sans état intermédiaire corrompu.

**Coûts.** Pas de contrainte d'intégrité référentielle : rien n'empêche mécaniquement un événement de référencer un préfixe absent de la couche curée. C'est compensé par des tests, ce qui est plus faible qu'une contrainte de base. Les écritures concurrentes ne sont pas gérées : deux exécutions simultanées sur la même partition produiraient un résultat indéterminé. Le catalogue enregistre les exécutions, mais ne pose pas de verrou.

**Limite de montée en charge.** Cette architecture tient tant que les requêtes restent analytiques et que le volume par partition reste raisonnable. Une interface interrogeant des millions de lignes à chaque clic exigerait des agrégats pré-calculés — c'est d'ailleurs déjà ce que fait la couche `analytics`, qui existe pour cette raison.

## Alternatives écartées

**PostgreSQL ou TimescaleDB.** Écartée : apporte des garanties inutiles au cas d'usage, au prix d'un serveur à opérer et d'un coût d'hébergement. Reste le bon choix si la plateforme devait accepter des écritures concurrentes ou servir une interface transactionnelle.

**SQLite.** Écartée : excellent pour le catalogue, mais son modèle par lignes est mal adapté aux agrégations columnaires sur plusieurs millions d'enregistrements.

**Tout charger en mémoire.** Écartée d'emblée : le budget matériel cible est de 8 Go, et une seule journée de données brutes peut le dépasser.

**Un format tabulaire ouvert avec couche transactionnelle (Delta Lake, Iceberg).** Écartée pour la V1 : apporte le versionnement et les transactions, mais ajoute une dépendance lourde pour un besoin — rejouer une journée — que la réécriture atomique de partition couvre déjà.
