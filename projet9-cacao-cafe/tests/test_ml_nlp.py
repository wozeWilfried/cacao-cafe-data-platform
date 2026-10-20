"""Tests ML et NLP : extraction, sorties des modèles, métriques d'évaluation.

Exécution :
    .venv/bin/python -m pytest tests/test_ml_nlp.py -v
Les tests marqués `db` nécessitent l'entrepôt chargé (ML/NLP exécutés au préalable).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "generate"))

from etl.common.db import dwh_conn, query, scalar  # noqa: E402
from nlp import contrats  # noqa: E402


# =============================================================================
# NLP 2 — extraction de clauses (unitaire, sans base)
# =============================================================================
class TestExtractionClauses:
    def test_date_texte_francais(self):
        d, _ = contrats._extrait_date("Expedition au plus tard le 15 novembre 2025.")
        assert d == "2025-11-15"

    def test_date_numerique(self):
        d, _ = contrats._extrait_date("Embarquement prevu au plus tard le 24/01/2025.")
        assert d == "2025-01-24"

    def test_volume_tonnes(self):
        v, _ = contrats._extrait_volume("Le contrat porte sur 250 tonnes nettes.")
        assert v == 250.0

    def test_incoterm_et_port(self):
        assert contrats._extrait_incoterm("Vente FOB Douala.")[0] == "FOB"
        assert contrats._extrait_port("Vente FOB Douala.")[0] == "Douala"

    def test_penalite(self):
        p, _ = contrats._extrait_penalite("une penalite de 0,5 % par jour sera appliquee.")
        assert p == 0.5

    def test_extraire_bloc(self):
        texte = ("Expedition au plus tard le 15 novembre 2025. Volume contractuel : 250 tonnes. "
                 "Vente FOB Douala. Penalite de 0,5% par jour de retard.")
        ext = contrats._extraire(texte)
        assert ext["DATE_LIMITE"] == "2025-11-15"
        assert ext["VOLUME_T"] == 250.0
        assert ext["INCOTERM"] == "FOB"
        assert ext["PORT"] == "Douala"
        assert ext["PENALITE_PCT"] == 0.5

    def test_theta_tolerance_volume(self):
        preds = {"a": 250.0, "b": 1000.0}
        verites = {"a": 248.0, "b": 1200.0}
        p, r, f1 = contrats._theta(preds, verites, "VOLUME_T")
        assert p == 50.0 and r == 50.0 and f1 == 50.0


# =============================================================================
# Sorties des modèles (intégration)
# =============================================================================
def _table_remplie(nom: str) -> bool:
    with dwh_conn() as conn:
        return scalar(conn, f"SELECT count(*) FROM {nom}") > 0


class TestSortiesML:
    def test_ml1_tonnage_rempli(self):
        assert _table_remplie("ml.prevision_tonnage")

    def test_ml1_intervalle_encadre(self):
        with dwh_conn() as conn:
            bad = scalar(conn, "SELECT count(*) FROM ml.prevision_tonnage "
                               "WHERE NOT (yhat_bas <= yhat AND yhat <= yhat_haut)")
        assert bad == 0

    def test_ml2_score_borne(self):
        with dwh_conn() as conn:
            bad = scalar(conn, "SELECT count(*) FROM ml.score_rejet_lot "
                               "WHERE proba_rejet < 0 OR proba_rejet > 1")
        assert bad == 0

    def test_ml2_metriques_presentes(self):
        with dwh_conn() as conn:
            n = scalar(conn, "SELECT count(*) FROM ml.metrique_modele "
                             "WHERE cible='rejet_lot' AND metrique IN ('F1','PR_AUC')")
        assert n >= 2

    def test_ml3_prevision_prix_horizon(self):
        with dwh_conn() as conn:
            n = scalar(conn, "SELECT count(DISTINCT date_cible) FROM ml.prevision_prix")
        assert n >= 3

    def test_ml3_scenarios_marge(self):
        with dwh_conn() as conn:
            n = scalar(conn, "SELECT count(*) FROM ml.scenario_marge")
            base = scalar(conn, "SELECT marge_pct FROM ml.scenario_marge WHERE scenario='BASE'")
        assert n >= 3
        assert base is not None and -100 < float(base) < 100


class TestSortiesNLP:
    def test_nlp1_defauts_rempli(self):
        assert _table_remplie("nlp.defaut_observation")

    def test_nlp1_proba_borne(self):
        with dwh_conn() as conn:
            bad = scalar(conn, "SELECT count(*) FROM nlp.defaut_observation "
                               "WHERE proba < 0 OR proba > 1")
        assert bad == 0

    def test_nlp1_f1_macro_present(self):
        with dwh_conn() as conn:
            val = scalar(conn, "SELECT valeur FROM ml.metrique_modele "
                               "WHERE modele='TFIDF_defauts' AND cible='defaut' AND metrique='F1_MACRO'")
        assert val is not None and 0.5 < float(val) <= 1.0

    def test_nlp2_extraction_remplie(self):
        assert _table_remplie("nlp.contrat_extraction")

    def test_nlp2_pas_de_doublon_traite(self):
        """Deux exécutions ne doivent pas dupliquer les extractions d'un contrat."""
        with dwh_conn() as conn:
            dups = scalar(
                conn,
                """SELECT count(*) FROM (
                       SELECT contrat_bk, entite, count(*) c
                         FROM nlp.contrat_extraction GROUP BY 1, 2 HAVING count(*) > 1
                   ) t""",
            )
        assert dups == 0
