"""DAG Airflow — mécanisme A : planification nocturne.

Tous les jours à 02:00, exécute la chaîne complète :
    extraire → contrôler → charger dimensions → charger faits → ML/NLP

Chaque tâche est idempotente : la relancer ne duplique rien. En cas d'échec,
Airflow relance 2 fois (retries) puis marque FAILED (visible dans etl.run_log).

Cf. guide, section 07.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from etl.pipeline import (
    etl_referentiels,
    etl_livraisons,
    etl_qualite,
    etl_prix,
    etl_export,
    etl_intrants,
    etl_trafic,
    etl_transport,
    etl_paiements,
)
from etl.common.db import dwh_conn


def _referentiels(**context):
    with dwh_conn(autocommit=True) as conn:
        run = etl_referentiels(conn, "2023-10-01")
    return run.compteurs


def _livraisons_incr(**context):
    with dwh_conn(autocommit=True) as conn:
        run = etl_livraisons(conn, mode="INCR")
    return run.compteurs


def _charger_faits(**context):
    with dwh_conn(autocommit=True) as conn:
        etl_qualite(conn)
        etl_prix(conn)
        etl_export(conn)
        etl_intrants(conn)
        etl_trafic(conn)
        etl_transport(conn)
        run = etl_paiements(conn)
    return run.compteurs


def _calcul_ml_nlp(**context):
    """Hook des étapes ML (M6) et NLP (M7) : importé paresseusement."""
    try:
        from ml.run import calculer  # type: ignore
        return calculer()
    except Exception:  # noqa: BLE001 — ML pas encore branché à ce stade du projet.
        return "ML/NLP non branché"


with DAG(
    dag_id="etl_filiere_cacao_cafe",
    description="Chaîne ETL complète cacao & café (planification nocturne)",
    schedule="0 2 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["filiere", "cacao-cafe", "etl"],
) as dag:
    t1 = PythonOperator(task_id="charger_referentiels", python_callable=_referentiels)
    t2 = PythonOperator(task_id="extraire_livraisons", python_callable=_livraisons_incr)
    t3 = PythonOperator(task_id="charger_autres_faits", python_callable=_charger_faits)
    t4 = PythonOperator(task_id="calcul_ml_nlp", python_callable=_calcul_ml_nlp)

    t1 >> t2 >> t3 >> t4
