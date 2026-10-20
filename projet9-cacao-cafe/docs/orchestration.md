# Orchestration et incrémental (M4)

Trois portes d'entrée, un seul pipeline : les DAGs Airflow et l'écouteur CDC
appellent tous les mêmes fonctions de `etl/pipeline.py`.

## Stratégie d'incrémental par source

| Source | Nouvelles | Modifiées | Supprimées |
|---|---|---|---|
| Livraisons (PostgreSQL) | filigrane `updated_at` + recouvrement 5 min | upsert sur `livraison_id` | journal `coop.cdc_journal` (opération D) |
| Paiements (JSON) | un fichier/jour via `etl.fichier_traite` | hachage du fichier | statut ANNULE dans le fichier suivant |
| Qualité (JSON) | filigrane `date_analyse` | hachage de ligne | non applicable |
| Producteurs/parcelles (GeoJSON) | instantané complet | `hash_diff` → nouvelle version SCD2 | absent → statut RADIE |
| Prix/FAOSTAT | clé (date, série) | hachage de ligne | non applicable |
| Météo/change | dernier jour + 1 | fenêtre glissante 7 j | non applicable |

## Déclenchement automatique

| Mécanisme | DAG / script | Cron / mode |
|---|---|---|
| A · Planification | `dags/etl_filiere_cacao_cafe.py` | `0 2 * * *` |
| B · Dépôt de fichier | `dags/etl_depot_fichier.py` | `*/10 * * * *` + FileSensor |
| C · Événement base | `scripts/ecouteur_cdc.py` + `pg_notify` | LISTEN `livraison_changee` |

Airflow démarre ces DAGs ; en local sans Airflow, `etl/pipeline.py` expose les
mêmes fonctions en CLI.

## Reprise sur incident — cinq garanties

1. Une transaction par tâche : échec = rien de partiel.
2. Filigrane avancé dans la transaction de chargement (inchangé après échec).
3. Upsert sur la clé métier : rejouer ne duplique rien.
4. Fichiers XML/JSON invalides → `data/quarantaine`, sinon `data/archive`.
5. Statut `FAILED` visible dans `etl.run_log`.

## Démonstration runs 0→4

```bash
.venv/bin/python scripts/demo_incremental.py --reset
```

| Run | Action source | Effet entrepôt (mesuré) |
|---|---|---|
| 0 | FULL 304 200 | 304 200 |
| 1 | +4 200 | 308 400 |
| 2 | +3 100 (SCD2) | 311 500 |
| 3 | +1 800 −400 suppr. | 313 300 dont 400 `est_supprime` |
| 4 | panne volontaire | **FAILED**, comptage inchangé |
| 4 | relance | +2 500, **zéro doublon** |

## Requête à projeter

```sql
SELECT run_id, source_name, mode, declencheur, statut, lignes_lues, lignes_inserees,
       lignes_maj, lignes_supprimees, lignes_rejetees, watermark_avant, watermark_apres,
       round(extract(epoch FROM fin - debut)) AS secondes
  FROM etl.run_log
 WHERE source_name = 'livraison'
 ORDER BY run_id DESC LIMIT 10;
```
