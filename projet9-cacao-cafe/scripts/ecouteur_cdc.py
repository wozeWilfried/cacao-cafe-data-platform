"""Écouteur pg_notify — mécanisme C (déclenchement par événement de base).

Écoute le canal `livraison_changee` émis par le déclencheur CDC
(sql/source/07_cdc_trigger.sql). À chaque notification, appelle l'API Airflow
pour déclencher le DAG ETL avec le déclencheur « EVENEMENT ».

Usage :
    .venv/bin/python scripts/ecouteur_cdc.py
Arrêt : Ctrl-C.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "generate"))

from common import load_env  # noqa: E402
from etl.common.db import _url  # noqa: E402

import psycopg  # noqa: E402

AIRFLOW_API = os.environ.get("AIRFLOW_API", "http://localhost:8080/api/v1")
DAG_ID = "etl_filiere_cacao_cafe"
CANAL = "livraison_changee"


def declencher_dag() -> None:
    """Appelle l'API REST d'Airflow pour lancer le DAG (best-effort)."""
    url = f"{AIRFLOW_API}/dags/{DAG_ID}/dagRuns"
    body = b'{"conf": {"declencheur": "EVENEMENT"}}'
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    user = os.environ.get("AIRFLOW_USER", "admin")
    pwd = os.environ.get("AIRFLOW_PASSWORD", "admin")
    import base64
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"  DAG déclenché ({resp.status})")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! Airflow indisponible : {exc}")


def main() -> int:
    load_env()
    dsn = _url("SRC_URL")
    print(f"Écoute de « {CANAL} » sur la base source… (Ctrl-C pour quitter)")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"LISTEN {CANAL}")
        while True:
            for notify in conn.notifies(timeout=30, stop_after=0):
                print(f"  notification reçue : livraison {notify.payload}")
                declencher_dag()
            conn.notifies()  # purge
            time.sleep(0.5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nArrêt de l'écouteur.")
