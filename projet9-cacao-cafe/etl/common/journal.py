"""Journalisation ETL : run_log, filigrane, rejets, fichiers traités.

Le cycle d'une exécution (cf. guide, section 06) :
  1. ouvrir un run (statut RUNNING)          -> ouvrir_run()
  2. stager / contrôler / transformer
  3. charger (dans la même transaction que l'avancée du filigrane)
  4. fermer le run (SUCCESS) ou le marquer FAILED  -> fermer_run() / echec_run()

Toute erreur non rattrapée laisse le run en RUNNING : l'appelant doit alors
appeler echec_run(). Le filigrane n'est avancé que dans la transaction de
chargement, jamais avant.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .db import execute, scalar


@dataclass
class RunLog:
    """Poignée d'une exécution, passée aux étapes suivantes."""

    run_id: int
    source_name: str
    mode: str
    watermark_avant: str | None
    compteurs: dict = field(default_factory=dict)

    def ajouter(self, cle: str, n: int) -> None:
        self.compteurs[cle] = self.compteurs.get(cle, 0) + n


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ouvrir_run(
    conn,
    source_name: str,
    mode: str,
    declencheur: str = "MANUEL",
    dag_id: str | None = None,
    task_id: str | None = None,
) -> RunLog:
    """Crée une ligne run_log en statut RUNNING et retourne sa poignée."""
    wm = lire_watermark(conn, source_name)
    row = scalar(
        conn,
        """
        INSERT INTO etl.run_log
            (dag_id, task_id, source_name, mode, declencheur, statut, watermark_avant)
        VALUES (%s, %s, %s, %s, %s, 'RUNNING', %s)
        RETURNING run_id
        """,
        (dag_id, task_id, source_name, mode, declencheur, wm),
    )
    return RunLog(run_id=row, source_name=source_name, mode=mode, watermark_avant=wm)


def fermer_run(
    conn,
    run: RunLog,
    statut: str = "SUCCESS",
    watermark_apres: str | None = None,
    message_erreur: str | None = None,
) -> None:
    """Clôt un run (SUCCESS ou FAILED) avec ses compteurs et son filigrane final."""
    execute(
        conn,
        """
        UPDATE etl.run_log SET
            fin = now(), statut = %s,
            lignes_lues = %s, lignes_inserees = %s, lignes_maj = %s,
            lignes_supprimees = %s, lignes_rejetees = %s,
            watermark_apres = %s, message_erreur = %s
        WHERE run_id = %s
        """,
        (
            statut,
            run.compteurs.get("lues", 0),
            run.compteurs.get("inserees", 0),
            run.compteurs.get("maj", 0),
            run.compteurs.get("supprimees", 0),
            run.compteurs.get("rejetees", 0),
            watermark_apres if watermark_apres is not None else run.watermark_avant,
            message_erreur,
            run.run_id,
        ),
    )


def echec_run(conn, run: RunLog, erreur: Exception) -> None:
    """Marque le run en FAILED (à appeler dans le bloc except)."""
    fermer_run(conn, run, statut="FAILED", message_erreur=f"{type(erreur).__name__}: {erreur}")


# -----------------------------------------------------------------------------
# Filigrane
# -----------------------------------------------------------------------------
def lire_watermark(conn, source_name: str) -> str | None:
    return scalar(
        conn, "SELECT derniere_valeur FROM etl.watermark WHERE source_name = %s", (source_name,)
    )


def ecrire_watermark(conn, source_name: str, valeur: str) -> None:
    """Avance le filigrane (à faire DANS la transaction de chargement)."""
    execute(
        conn,
        """
        INSERT INTO etl.watermark (source_name, derniere_valeur, maj_le)
        VALUES (%s, %s, now())
        ON CONFLICT (source_name)
        DO UPDATE SET derniere_valeur = EXCLUDED.derniere_valeur, maj_le = now()
        """,
        (source_name, valeur),
    )


# -----------------------------------------------------------------------------
# Rejets
# -----------------------------------------------------------------------------
def rejeter(conn, run: RunLog, cle_metier, regle: str, valeur) -> None:
    """Enregistre une ligne rejetée avec sa règle et sa valeur (JSON)."""
    execute(
        conn,
        """
        INSERT INTO etl.rejet (run_id, source_name, cle_metier, regle, valeur_rejetee)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (run.run_id, run.source_name, str(cle_metier), regle, json.dumps(valeur, default=str)),
    )
    run.ajouter("rejetees", 1)


# -----------------------------------------------------------------------------
# Fichiers traités
# -----------------------------------------------------------------------------
def marquer_fichier(conn, nom: str, hash_md5: str, run_id: int, statut: str = "SUCCESS") -> None:
    execute(
        conn,
        """
        INSERT INTO etl.fichier_traite (nom, hash_md5, run_id, statut, traite_le)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (nom) DO UPDATE SET
            hash_md5 = EXCLUDED.hash_md5, run_id = EXCLUDED.run_id,
            statut = EXCLUDED.statut, traite_le = now()
        """,
        (nom, hash_md5, run_id, statut),
    )


def fichier_deja_traite(conn, nom: str, hash_md5: str) -> bool:
    rows = scalar(
        conn,
        "SELECT 1 FROM etl.fichier_traite WHERE nom = %s AND hash_md5 = %s AND statut = 'SUCCESS'",
        (nom, hash_md5),
    )
    return rows is not None
