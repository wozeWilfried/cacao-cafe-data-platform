"""Connexions base de données et helpers ETL partagés.

Deux bases distinctes (cf. architecture) :
  - SOURCE  : la base opérationnelle `coop_source` (données brutes du quotidien) ;
  - DWH     : l'entrepôt `dwh` (staging, dimensions, faits, tables etl.*).

Les connexions sont lues depuis le .env (SRC_URL / DWH_URL) via common.load_env.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "generate"))

from common import load_env  # noqa: E402


def _url(env_var: str) -> str:
    load_env()
    url = os.environ.get(env_var)
    if not url:
        raise RuntimeError(f"{env_var} absente : renseignez le fichier .env")
    # SQLAlchemy accepte « postgresql+psycopg:// », psycopg veut « postgresql:// ».
    return url.replace("postgresql+psycopg://", "postgresql://")


@contextmanager
def source_conn(autocommit: bool = False):
    """Connexion à la base source (lecture de l'opérationnel)."""
    with psycopg.connect(_url("SRC_URL"), autocommit=autocommit) as conn:
        yield conn


@contextmanager
def dwh_conn(autocommit: bool = False):
    """Connexion à l'entrepôt (staging, dimensions, faits, etl.*)."""
    with psycopg.connect(_url("DWH_URL"), autocommit=autocommit) as conn:
        yield conn


@contextmanager
def transaction(conn):
    """Transaction explicite : commit si tout va bien, rollback sinon."""
    with conn.transaction():
        yield conn


def query(conn, sql: str, params=None) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def scalar(conn, sql: str, params=None):
    rows = query(conn, sql, params)
    return rows[0][0] if rows else None


def execute(conn, sql: str, params=None) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount
