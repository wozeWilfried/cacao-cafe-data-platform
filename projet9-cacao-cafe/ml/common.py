"""Outils partagés des fonctionnalités ML et NLP.

Fournit l'accès à l'entrepôt (réutilise etl.common.db), l'écriture des métriques
d'évaluation et une petite fonction de journalisation de run.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.common.db import dwh_conn, source_conn, execute, query, scalar  # noqa: E402,F401
from etl.common import journal  # noqa: E402,F401


def ecrire_metrique(conn, modele: str, cible: str, jeu: str, metrique: str,
                    valeur: float | None, reference: float | None = None,
                    run_id: int | None = None) -> None:
    """Upsert d'une métrique d'évaluation dans ml.metrique_modele."""
    execute(
        conn,
        """INSERT INTO ml.metrique_modele (modele, cible, jeu, metrique, valeur, reference, run_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (modele, cible, jeu, metrique)
           DO UPDATE SET valeur = EXCLUDED.valeur, reference = EXCLUDED.reference,
                         run_id = EXCLUDED.run_id, calcule_le = now()""",
        (modele, cible, jeu, metrique, valeur, reference, run_id),
    )


def charger_dataframe(conn, sql: str, params=None):
    """Exécute une requête et renvoie un DataFrame pandas."""
    import pandas as pd

    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)
