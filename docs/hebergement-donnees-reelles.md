# Hébergement avec données réelles — étude 2026

Étude menée le 27/11/2026 pour répondre à une contrainte précise : **héberger ABRIP avec de vraies données BGP, sans abonnement payant**, une carte de crédit étant acceptée pour la vérification d'identité. Ce document complète `docs/deploiement.md`, qui décrit surtout le déploiement de la démo et dont la section Hugging Face doit être lue avec la mise à jour ci-dessous.

**Cas sans carte utilisable** : Oracle refusant les cartes virtuelles/prépayées, une étude séparée propose une architecture 100 % gratuite (Render Free + dataset public Hugging Face + pipeline local) dans `docs/deploiement-sans-carte.md`.

## 1. Besoins réels du projet

| Besoin | Chiffre / contrainte | Conséquence pour l'hébergement |
|---|---|---|
| Données curées | ~673 Mo de Parquet à 50 M de lignes ; plusieurs Go avec de l'historique | Disque persistant obligatoire, pas de filesystem éphémère |
| Mémoire | API seule < 512 Mo ; précalcul (`sort_partition`) pic ~1,1 Go avec limite 1 Go ; curation réelle > 512 Mo | ≥ 2 Go, idéalement 8–12 Go pour exécuter le pipeline |
| CPU | Mono-processus, DuckDB monocœur ; ~4 req/s mesurés sur 1 cœur | 2 cœurs utiles pour API + tâches en parallèle |
| Persistance | Parquet, catalogue DuckDB, journaux, `alert_log`, `event_feedback` | Volume de données monté en permanence |
| Réseau entrant | ~1–3 Go pour 7 jours de `updates` sur 3 collecteurs, ~5–15 Go pour 2–4 semaines (chiffre exact via `--dry-run`) | Bonus : forfait sortant généreux |
| Réseau sortant | Faible : l'API sert des JSON, le frontend est compilé dans l'image | < 10 Go/mois suffisent largement |
| Ordonnancement | ingestion → curation → analytics → détection → précalcul → purge | Cron ou jobs planifiés, donc accès shell ou jobs serveur |
| Disponibilité | APIs publiques, monitoring `/api/health`, alertes webhook | Pas de mise en veille de 15 min si possible |

Le point bloquant sur la plupart des PaaS gratuits n'est pas la RAM : c'est **l'absence de disque persistant et de tâches planifiées**.

## 2. Mise à jour importante sur Hugging Face Spaces

Le guide `docs/deploiement.md` présente Hugging Face Spaces comme « recommandé et gratuit ». Ce n'est plus exact en 2026 :

- `cpu-basic` reste à 2 vCPU / 16 Go / 50 Go de disque, **sans coût horaire** ;
- mais créer un Space **Docker** ou **Gradio** sur `cpu-basic` **nécessite désormais un plan payant** (PRO pour un compte personnel, Team/Enterprise pour une organisation). Sans abonnement, la création échoue avec une erreur de paiement (HTTP 402) ;
- les Spaces gratuits non payants sont les **Static Spaces** (HTML/JS uniquement), qui ne peuvent pas exécuter FastAPI ;
- le stockage persistant des Spaces passe par des **Storage Buckets payants** ; le disque local est éphémère et supprimé au redémarrage ;
- les Spaces sur matériel gratuit sont suspendus après ~48 h d'inactivité.

Sources : [Spaces Overview](https://huggingface.co/docs/hub/spaces-overview), [Disk usage on Spaces](https://huggingface.co/docs/hub/main/en/spaces-storage), [Manage your Space](https://huggingface.co/docs/huggingface_hub/guides/manage-spaces), [Pricing](https://huggingface.co/pricing).

**Conclusion** : Hugging Face reste une excellente source de données (dataset public pour distribuer `data/`), mais n'est plus le meilleur choix pour *exécuter* le service avec des données réelles sans payer.

## 3. Comparatif des options réellement gratuites en 2026

| Option | Compute gratuit | Disque persistant | Veille | Verdict pour données réelles |
|---|---|---|---|---|
| **Oracle Cloud Always Free** | ARM `A1.Flex` : 2 OCPU / 12 Go ; + 2 micro VM AMD 1 Go | **200 Go** de volumes (boot + blocs), 10 To/mois sortant | Aucune, mais réclamation si inactif < 20 % sur 7 j | **Meilleur choix** |
| **Fly.io Free** (nouveau, 23/11/2026) | 3 Machines, shared CPU ; ~$5 d'usage/mois avec carte | Volumes jusqu'à 5 Go chacun | Aucune si machine allumée | Bon choix si données < 5 Go, mais risque de bascule PAYG |
| **Google Cloud Run** gratuit | 2 M requêtes, 180 000 vCPU-s, 360 000 GiB-s / mois | Aucun : données à monter depuis GCS | Scale-to-zero, cold starts | Viable API seule + GCS, pas de pipeline |
| **Render Free** | < 1 CPU / 512 Mo, 750 h/mois | **Aucun** (disque payant) | 15 min, réveil ~1 min | Insuffisant |
| **Koyeb Free** | 0,1 vCPU / 512 Mo / 2 Go | **Aucun volume en gratuit** | 1 h | Insuffisant |
| **Hugging Face Spaces** | 2 vCPU / 16 Go mais abonnement requis | Buckets payants | 48 h | Plus réellement gratuit pour du Docker |

Sources complémentaires : [Oracle Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm), [Oracle Free Tier FAQ](https://www.oracle.com/cloud/free/faq/), [Fly.io Free Plan](https://docs.fly.io/about/free-plan), [Cloud Run pricing](https://cloud.google.com/run/pricing), [Google Cloud Free Tier](https://docs.cloud.google.com/free/docs/free-cloud-features), [Render Free](https://render.com/docs/free), [Koyeb Pricing FAQ](https://www.koyeb.com/docs/faqs/pricing).

> Attention Oracle : les anciens guides citent 4 OCPU / 24 Go. Depuis juin 2026, le quota Always Free est **2 OCPU / 12 Go** (1 500 OCPU-heures et 9 000 Go-heures par mois). Le quota de 200 Go de stockage reste inchangé, et le trafic sortant est de 10 To/mois.

## 4. Recommandation : Oracle Cloud Always Free

### 4.1 Pourquoi

- C'est la seule option qui réunit **disque persistant de 200 Go**, **12 Go de RAM**, **2 OCPU**, **aucune mise en veille** et **10 To de trafic sortant**, sans frais.
- Le service peut tourner en continu, héberger les Parquet sur un volume détaché, et exécuter le pipeline complet (ingestion, curation, analytics, détection, précalcul) sur la même machine.
- Le volume de téléchargement des MRT (1–15 Go) est dérisoire face au quota sortant.
- Aucun risque de bascule automatique vers une facturation : les ressources Always Free restent gratuites tant qu'on reste dans les quotas.

### 4.2 Contraintes à accepter

- Carte de crédit ou de débit (pas de carte prépayée/virtuelle) et souvent numéro de téléphone pour l'inscription ; la carte sert uniquement à la vérification.
- Région « home » fixée à l'inscription ; les instances A1 peuvent être indisponibles (`out of host capacity`) — réessayer un autre domaine de disponibilité ou quelques jours plus tard.
- Architecture **ARM64** : l'image Docker doit être construite pour `linux/arm64` (ou installer directement via `uv` sur Ubuntu ARM, plus simple).
- Règle anti-inactivité : une instance est réclamée si, sur 7 jours, CPU, réseau **et** mémoire restent sous 20 % au p95. Un cron quotidien (détection ou simple tâche de maintenance) suffit à garder de l'activité ; à défaut, prévoir un monitoring qui garde au moins une métrique au-dessus du seuil.

### 4.3 Architecture proposée

```
Oracle Cloud (région home, A1.Flex 2 OCPU / 12 Go)
├── Boot volume 50 Go : Ubuntu 24.04 ARM64, Docker ou uv
├── Block volume 150 Go monté sur /app/data (ABRIP_DATA_DIR)
│   ├── raw/        MRT téléchargés (rétention 30 j)
│   ├── curated/    bgp_elements, rib_snapshots (rétention 90 j)
│   ├── analytics/  métriques, events, incidents, asn_prefix_stats
│   ├── reference/  ref_asn, ref_roa, ...
│   └── catalog.duckdb
├── Service systemd : abrip api serve --host 0.0.0.0 --port 8000 --workers 2
├── Reverse proxy : Caddy (TLS automatique) ou Cloudflare Tunnel (aucun port ouvert)
└── cron / systemd timers :
    ├── quotidien : ingest broker → etl curate → analytics compute → detect run --notify
    ├── après curation : analytics precompute
    └── hebdo : etl purge --apply (après simulation)
```

La variables d'environnement utiles :

```bash
ABRIP_DATA_DIR=/app/data
ABRIP_API__WORKERS=2
ABRIP_API__API_KEY=<cle-longue-et-aleatoire>
ABRIP_API__RATE_LIMIT_PER_MINUTE=120
ABRIP_API__PREWARM=true
ABRIP_ALERTS__WEBHOOK_URL=https://hooks.slack.com/services/...
ABRIP_LOG_LEVEL=INFO
```

### 4.4 Étapes de mise en œuvre

1. Créer le compte Oracle Cloud, choisir une région avec capacité Ampere, créer une instance `VM.Standard.A1.Flex` avec 2 OCPU / 12 Go et Ubuntu ARM64.
2. Créer un volume par bloc de 150 Go, l'attacher et le monter sur `/app/data` ; ajouter la ligne `/etc/fstab` correspondante.
3. Installer `uv`, cloner le dépôt, `uv sync --locked --no-dev`, copier les `configs/`, puis `abrip demo bootstrap` uniquement pour vérifier l'installation avant de remplacer `data/` par les vraies données.
4. Pour le frontend, construire les fichiers statiques (`npm ci && npm run build`) et copier `frontend/dist` ; sur ARM, il est plus simple de compiler localement et de copier le dossier que de construire une image multi-arch.
5. Configurer Caddy (ou un tunnel Cloudflare) pour TLS et le port 8000 ; vérifier `curl https://<domaine>/api/health`.
6. Créer le service systemd pour l'API et les timers pour le pipeline ; activer la clé API et le rate limiting avant exposition publique.
7. Renseigner `ABRIP_ALERTS__WEBHOOK_URL` pour recevoir les incidents critiques.

## 5. Alternantes selon le profil

### 5.1 Fly.io Free — le plus simple si les données tiennent dans 5 Go

Depuis le 23 novembre 2026, Fly.io propose un plan gratuit avec carte : **$5 d'usage par mois**, jusqu'à 3 Machines et des volumes de 5 Go chacun. Une machine `shared-cpu-1x` 256 Mo tournant en continu coûte ~$2,19/30 jours, donc le budget tient avec un volume de données ≤ 5 Go et un trafic modeste.

Avantages : `fly deploy` depuis le dépôt, volumes persistants, pas de mise en veille, TLS géré.
Risque majeur : si l'usage dépasse $5, l'organisation passe **automatiquement en pay-as-you-go et le mois entier est facturé au tarif standard**. Il faut donc surveiller le dashboard et rester largement sous le plafond. À réserver à un jeu de données ≤ 5 Go et à un trafic faible.

### 5.2 Google Cloud Run + Cloud Storage — le plus « managed »

- API en conteneur Cloud Run, données Parquet dans un bucket GCS monté en lecture (`gcsfuse`) ou téléchargées au démarrage.
- Quota gratuit : 2 M requêtes, 180 000 vCPU-s et 360 000 GiB-s par mois ; ~50 h de CPU à 1 vCPU.
- GCS gratuit : 5 Go-mois de stockage et 1 Go/mois de trafic sortant depuis l'Amérique du Nord.
- Limites : pas de pipeline permanent, cold starts, quotas de CPU consommés par chaque requête (0,2 s × 2 M requêtes dépasse le quota). Adapté à une API de consultation à faible trafic, pas à l'ingestion.

## 6. Choix recommandé

| Profil | Option |
|---|---|
| Données réelles, pipeline complet, zéro abonnement | **Oracle Cloud Always Free** |
| Données < 5 Go, simplicité de déploiement, surveillance des coûts | Fly.io Free |
| API seule, données < 5 Go, trafic faible, envie de managed | Cloud Run + GCS |
| Démo uniquement, sans données réelles | Image Docker actuelle, n'importe quel PaaS |

Pour le cas demandé — **données réelles et gratuit même avec carte** — la recommandation est **Oracle Cloud Always Free**, avec un volume bloc pour `ABRIP_DATA_DIR`, l'API en service systemd et le pipeline planifié par cron. Le budget réseau reste limité à 1–3 Go pour un premier jeu de données, 5–15 Go pour une calibration robuste, très loin des 10 To/mois autorisés.

## 7. Points à vérifier avant de s'engager

- Capacité Ampere disponible dans la région `home` au moment de la création.
- Possibilité d'ouvrir le port 80/443 ou, à défaut, d'utiliser Cloudflare Tunnel.
- Politique d'usage d'Oracle sur le trafic sortant et la réclamation des instances inactives.
- Volume réel des données après quelques semaines d'ingestion : ajuster `etl.retention_days` et la taille du volume blocks si nécessaire.
- Couverture des coûts en cas d'erreur de configuration sur Fly.io (bascule automatique en PAYG).
