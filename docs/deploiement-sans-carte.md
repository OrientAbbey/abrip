# Déploiement sans carte bancaire physique — étude novembre 2026

Contexte : héberger ABRIP avec des données réelles en restant **gratuit**, sachant que le seul moyen de paiement disponible est une **carte virtuelle Orange Money avec 1 000 FCFA**. Oracle Cloud a refusé cette carte (cartes prépayées/virtuelles interdites). Ce document reprend les recherches faites après ce refus et propose une architecture qui ne demande **aucun moyen de paiement**.

## 1. Ce qui est définitivement exclu

| Service | Raison |
|---|---|
| **Oracle Cloud Always Free** | Carte physique obligatoire pour l'inscription ; refus explicite des cartes prépayées/virtuelles/à usage unique |
| **Google Cloud / Cloud Run** | Compte de facturation obligatoire ; Google refuse cartes prépayées et virtuelles pour la facturation récurrente |
| **Koyeb Free** | Pré-autorisation de **29 $** demandée à l'inscription : impossible avec 1 000 FCFA, et le plan Pro est sélectionné par défaut |
| **Fly.io Free** | La carte est facultative pour le compte, mais nécessaire pour dépasser l'essai de 1 $ / 7 jours ; le $5 mensuel suppose une carte valide et le dépassement bascule en payant |
| **Hugging Face Spaces compute** | Depuis 2026, créer un Space Docker/Gradio sur `cpu-basic` exige PRO/Team ; seuls les Static Spaces sont gratuits |
| **PythonAnywhere Free** | Pas de carte, mais 512 Mo de disque, 100 CPU-s/jour, sortie Internet filtrée par liste blanche, web app expirant après 1 mois sans usage |

Sources : [Oracle Free Tier FAQ](https://www.oracle.com/cloud/free/faq/), [Google Cloud signup troubleshooting](https://docs.cloud.google.com/support/docs/troubleshoot-signup), [Koyeb Pricing FAQ](https://www.koyeb.com/docs/faqs/pricing), [Fly.io Free Plan](https://docs.fly.io/about/free-plan), [HF Spaces Overview](https://huggingface.co/docs/hub/spaces-overview), [PythonAnywhere Free Accounts](https://help.pythonanywhere.com/pages/FreeAccountsFeatures).

## 2. Ce qui reste possible sans carte

| Brique | Service gratuit | Limite | Usage pour ABRIP |
|---|---|---|---|
| API | **Render Free web service** | 512 Mo RAM, < 1 CPU, mise en veille après 15 min d'inactivité, redémarrage ~1 min, système de fichiers éphémère | Exécuter `abrip api serve` (l'API seule tient dans 512 Mo) |
| Données | **Dataset public Hugging Face** | Stockage public « best-effort », **egress et CDN inclus sans coût**, aucun compte payant | Héberger les Parquet curés/analytiques |
| Frontend | **GitHub Pages / Netlify / Vercel Hobby** | Statique gratuit, pas de carte | Servir `frontend/dist` |
| Pipeline ETL | **Machine locale** | Aucune limite de service | Télécharger les MRT, curer, calculer, détecter, puis publier vers le dataset HF |
| Métriques/alertes | Webhook Slack gratuit | — | `ABRIP_ALERTS__WEBHOOK_URL` |

Sources : [Render Free](https://render.com/docs/free), [HF Storage limits](https://huggingface.co/docs/hub/en/storage-limits), [HF Pricing](https://huggingface.co/pricing), [Vercel Hobby](https://vercel.com/docs/plans/hobby).

## 3. Deux architectures possibles

### Variante A — la plus simple : jeu de données léger téléchargé au démarrage

```
Machine locale (pipeline, 1–15 Go de MRT téléchargés)
        │  abrip ingest broker → etl curate → analytics compute → detect run
        ▼
Dataset public Hugging Face  (Parquet, quelques Mo à ~100 Mo)
        │  téléchargement au démarrage du service
        ▼
Render Free (FastAPI + frontend intégré)  ──►  https://<app>.onrender.com
```

- Aucun changement de code : `DataAccess` continue de lire des fichiers locaux.
- Un script de démarrage (`render.yaml` + `start.sh`) télécharge le dataset HF dans `ABRIP_DATA_DIR` puis lance `abrip api serve`.
- Le jeu doit rester **petit** (< 100–150 Mo) : le redémarrage après veille le télécharge à nouveau.
- Le catalogue DuckDB et les retours L5 ne survivent pas à un redémarrage : acceptable pour un service de consultation, mais `detect label`/alertes doivent rester locaux.

### Variante B — sans téléchargement : DuckDB lit le dataset HF à la demande

DuckDB, avec l'extension `httpfs`, sait lire un Parquet sur HTTPS en **range requests** : il ne télécharge que le pied de fichier et les row groups nécessaires à la requête.

```sql
INSTALL httpfs;
SELECT * FROM read_parquet(
  'https://huggingface.co/datasets/<user>/<repo>/resolve/main/curated/bgp_elements/date=2026-11-20/part-00000.parquet'
);
```

- Le dataset complet (~673 Mo à 50 M de lignes) reste sur HF ; rien n'est stocké sur Render.
- Nécessite une adaptation de `DataAccess.table()`/`glob_for()` pour produire des URL HTTPS et charger `httpfs` au démarrage.
- Le catalogue local reste facultatif : `/api/health` et `/api/quality` savent déjà fonctionner sans catalogue.
- Cold starts plus rapides, mais chaque requête peut générer un peu de trafic HF ; le cache `ETag`/304 et le cache applicatif limitent ce coût.
- À valider : acceptance des Range requests par le CDN HF (à tester avec un `curl -I -H "Range: bytes=0-10"` sur un fichier du dataset), taille mémoire de DuckDB + httpfs sous 512 Mo.

Sources : [DuckDB HTTP(S) support](https://duckdb.org/docs/1.4/core_extensions/httpfs/https), [DuckDB httpfs overview](https://duckdb.org/docs/archive/0.9.2/extensions/httpfs).

## 4. Workflow de données recommandé

1. **Sur la machine locale** (où la carte n'est pas nécessaire) :
   ```bash
   abrip ingest broker --from 2026-11-01 --to 2026-11-07 --type updates
   abrip etl curate --from 2026-11-01 --to 2026-11-07
   abrip analytics compute --from 2026-11-01 --to 2026-11-07
   abrip detect run --from 2026-11-01 --to 2026-11-07
   abrip analytics precompute
   ```
2. **Publier** `data/curated`, `data/analytics` et `data/reference` dans un dataset public HF avec `huggingface_hub` (gratuit, compte gratuit).
3. **Sur Render** : service `start.sh` qui télécharge (variante A) ou configure `httpfs` (variante B), puis lance l'API.
4. **Frontend** : `npm run build`, puis publier `frontend/dist` sur GitHub Pages ou Vercel. Si l'API est sur Render et le frontend sur un autre domaine, renseigner `ABRIP_API__CORS_ORIGINS` avec ce domaine — l'API reste protégée par clé si tu la déploies publiquement.

## 5. Limites à accepter

- **Mise en veille** : 15 min sans trafic, réveil d'environ 1 minute. À mitiger avec un ping périodique gratuit (UptimeRobot, cron GitHub Actions) si tu veux une latence stable.
- **Pas d'écriture persistante** : pas de `event_feedback`, ni `alert_log`, ni catalogue persistant sur le serveur. LA qualification L5 et les alertes restent exécutées en local.
- **512 Mo de RAM** : suffisant pour l'API seule, mais pas pour le précalcul (`asn_prefix_stats`) ni la curation — ces étapes restent locales.
- **Trafic sortant Render** : Render suspend les services gratuits qui génèrent un volume sortant inhabituel. La variante B (range requests HF) est plus économique que la variante A (téléchargement complet à chaque réveil).
- **Données publiques** : un dataset HF public est visible par tous. Si les données doivent rester privées, le stockage privé HF est payant — il faut alors revenir vers une offre avec carte.

## 6. Coût et réseau

| Poste | Coût | Réseau |
|---|---|---|
| Render Free | 0 FCFA | Faible (JSON API) |
| HF dataset public | 0 FCFA, egress inclus | Upload initial depuis chez toi : quelques centaines de Mo ; downloads via CDN HF |
| Frontend statique | 0 FCFA | ~254 Ko gzip |
| Pipeline local | 0 FCFA | 1–15 Go de MRT en entrée, selon la fenêtre |
| Carte bancaire | **aucune utilisée** | — |

## 7. Plan d'action proposé

1. Créer les comptes Render, Hugging Face et GitHub Pages **sans carte**.
2. Créer un jeu de démonstration réel réduit (3 collecteurs, 7 jours, quelques AS concernés) sur la machine locale, puis le publier sur HF.
3. Déployer une première version sur Render avec la variante A et vérifier `/api/health`, `/api/overview` et les pages du frontend.
4. Une fois validé, mesurer le trafic au réveil ; si le téléchargement complete devient gênant, passer à la variante B (httpfs).
5. Garder Oracle Cloud en objectif d'évolution si une carte physique devient disponible : le même dataset HF peut alors être téléchargé une fois sur le volume bloc.

## 8. Conclusion

Avec 1 000 FCFA sur une carte virtuelle, **aucune offre d'hébergement avec stockage persistant n'est accessible**. La combinaison **Render Free + dataset public Hugging Face + pipeline local** permet néanmoins de publier l'API et le frontend sur de vraies données, à condition d'accepter la mise en veille, l'absence d'écritures côté serveur et un jeu de données hébergé publiquement. C'est la solution gratuite la plus réaliste ; la variante B la rapproche du comportement d'une installation complète sans télécharger les Parquet à chaque démarrage.
