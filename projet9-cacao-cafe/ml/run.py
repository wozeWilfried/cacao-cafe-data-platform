"""Orchestrateur des fonctionnalités ML et NLP (appelé par le DAG).

Expose `calculer()` : exécute les 3 modèles ML et les 2 traitements NLP, journalise
le run dans etl.run_log et renvoie un récapitulatif des lignes écrites.
"""

from __future__ import annotations

from ml.common import dwh_conn, journal


def calculer() -> dict:
    """Calcule tous les modèles ML + NLP et journalise l'exécution."""
    from ml import tonnage, rejet, prix
    from nlp import defauts, contrats

    with dwh_conn(autocommit=True) as conn:
        run = journal.ouvrir_run(
            conn, source_name="ml_nlp", mode="FULL",
            declencheur="PLANIFIE", dag_id="etl_filiere_cacao_cafe", task_id="calcul_ml_nlp",
        )
        resultat = {}
        try:
            resultat["ml1_tonnage"] = tonnage.executer(conn)
            resultat["ml2_rejet"] = rejet.executer(conn)
            resultat["ml3_prix"] = prix.executer(conn)
            resultat["nlp1_defauts"] = defauts.executer(conn)
            resultat["nlp2_contrats"] = contrats.executer(conn)
            total = sum(resultat.values())
            run.ajouter("inserees", total)
            journal.fermer_run(conn, run, statut="SUCCESS")
        except Exception as exc:  # noqa: BLE001 — journalise l'échec puis propage.
            journal.echec_run(conn, run, exc)
            raise
    return resultat


if __name__ == "__main__":
    import json

    print(json.dumps(calculer(), indent=2, ensure_ascii=False))
