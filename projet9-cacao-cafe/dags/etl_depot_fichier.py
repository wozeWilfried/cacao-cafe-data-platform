"""DAG Airflow — mécanisme B : capteur de fichier inbox.

Toutes les 10 minutes, un FileSensor attend l'arrivée d'un
`paiements_AAAAMMJJ.json` dans data/inbox/paiements. Dès qu'un fichier apparaît,
il est traité (ETL paiements) puis archivé.

Cf. guide, section 07.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.filesystem import FileSensor

from etl.pipeline import traiter_paiements

INBOX_PAIEMENTS = "/opt/airflow/data/inbox/paiements/paiements_*.json"


with DAG(
    dag_id="etl_depot_fichier",
    description="Traite les fichiers de paiements déposés dans inbox",
    schedule="*/10 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["filiere", "cacao-cafe", "fichier"],
) as dag:
    attendre = FileSensor(
        task_id="attendre_paiements",
        fs_conn_id="fs_default",
        filepath=INBOX_PAIEMENTS,
        poke_interval=30,
        timeout=240,
        mode="reschedule",
        soft_fail=True,   # aucun fichier : exécution ignorée, pas en échec
    )
    traiter = PythonOperator(
        task_id="traiter_et_archiver",
        python_callable=traiter_paiements,
        op_kwargs={"declencheur": "FICHIER"},
    )
    attendre >> traiter
