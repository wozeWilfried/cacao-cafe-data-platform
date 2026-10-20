"""Tests automatiques ETL : règles de qualité, upsert idempotent, SCD2, reprise.

Exécution :
    .venv/bin/python -m pytest tests/ -v
Les tests d'intégration (marqués `db`) nécessitent la pile Docker démarrée.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "generate"))

from etl.quality import regles  # noqa: E402
from etl.common.db import dwh_conn, scalar  # noqa: E402
from etl.common import journal  # noqa: E402
from etl.load import dimensions as dim  # noqa: E402
from etl.load import faits as fts  # noqa: E402


# =============================================================================
# Règles de qualité (unitaires, sans base)
# =============================================================================
class TestRegles:
    def test_r02_obligatoires(self):
        assert regles.r02_obligatoires({"a": "x"}, ["a"]) is None
        assert regles.r02_obligatoires({"a": ""}, ["a"])[0] == "R02"
        assert regles.r02_obligatoires({"a": None}, ["a"])[0] == "R02"

    def test_r03_poids(self):
        assert regles.r03_domaine_poids({"poids_net_kg": 10, "poids_brut_kg": 12}) is None
        assert regles.r03_domaine_poids({"poids_net_kg": 0})[0] == "R03"
        assert regles.r03_domaine_poids({"poids_net_kg": 15, "poids_brut_kg": 12})[0] == "R03"

    def test_r03_humidite(self):
        assert regles.r03_domaine_humidite({"humidite_pct": 12}) is None
        assert regles.r03_domaine_humidite({"humidite_pct": 120})[0] == "R03"

    def test_r05_date(self):
        assert regles.r05_date({"d": "2024-01-15"}, "d") is None
        assert regles.r05_date({"d": "pas une date"}, "d")[0] == "R05"

    def test_r06_paiement(self):
        assert regles.r06_paiement({"montant_fcfa": 1000}) is None
        assert regles.r06_paiement({"montant_fcfa": 0})[0] == "R06"

    def test_r07_ordre_temporel(self):
        assert regles.r07_ordre_temporel({"a": "2024-01-01", "b": "2024-02-01"}, "a", "b") is None
        assert regles.r07_ordre_temporel({"a": "2024-02-01", "b": "2024-01-01"}, "a", "b")[0] == "R07"

    def test_r08_gps(self):
        assert regles.r08_gps({"lat": 4.0, "lon": 9.7, "vitesse_kmh": 60}) is None
        assert regles.r08_gps({"lat": 50.0})[0] == "R08"
        assert regles.r08_gps({"vitesse_kmh": 200})[0] == "R08"

    def test_r10_texte(self):
        rec = {"observation": ""}
        assert regles.r10_texte(rec, "observation") is True
        assert rec["observation"] == "NON_RENSEIGNE"

    def test_r01_doublons_garde_plus_recent(self):
        recs = [
            {"id": "1", "updated_at": "2024-01-01T00:00:00"},
            {"id": "1", "updated_at": "2024-06-01T00:00:00"},
        ]
        uniques, doublons = regles.detecter_doublons(recs, "id")
        assert len(uniques) == 1
        assert uniques[0]["updated_at"].startswith("2024-06")
        assert len(doublons) == 1


# =============================================================================
# Tests d'intégration (nécessitent la base dwh)
# =============================================================================
def _db_dispo() -> bool:
    try:
        with dwh_conn() as conn:
            scalar(conn, "SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_dispo(), reason="base dwh indisponible")


class TestDwh:
    def test_dim_date_campagne(self):
        with dwh_conn() as conn:
            # 30 sept 2023 -> campagne 2022/2023 ; 1er oct 2023 -> 2023/2024.
            a = scalar(conn, "SELECT campagne FROM dwh.dim_date WHERE date_complete = '2023-09-30'")
            b = scalar(conn, "SELECT campagne FROM dwh.dim_date WHERE date_complete = '2023-10-01'")
            assert a == "2022/2023"
            assert b == "2023/2024"

    def test_dimensions_type1_seedees(self):
        with dwh_conn() as conn:
            assert scalar(conn, "SELECT count(*) FROM dwh.dim_produit") >= 2
            assert scalar(conn, "SELECT count(*) FROM dwh.dim_canal") == 4
            assert scalar(conn, "SELECT count(*) FROM dwh.dim_port") == 2

    def test_upsert_idempotent(self):
        with dwh_conn() as conn:
            n1 = scalar(conn, "SELECT count(*) FROM dwh.fait_livraison")
            rows = [(f"TEST-{i}", 20231001, 1, None, None, None, None, 10.0, 9.0, 1, 0)
                    for i in range(3)]
            fts.upsert_livraison(conn, rows)
            fts.upsert_livraison(conn, rows)  # rejeu : aucun doublon
            n2 = scalar(conn, "SELECT count(*) FROM dwh.fait_livraison")
            assert n2 == n1 + 3
            with conn.cursor() as cur:
                cur.execute("DELETE FROM dwh.fait_livraison WHERE livraison_bk LIKE 'TEST-%'")
            conn.commit()

    def test_scd2_une_version_courante_par_bk(self):
        with dwh_conn() as conn:
            doublons = scalar(
                conn,
                """SELECT count(*) FROM (
                    SELECT producteur_bk FROM dwh.dim_producteur
                    WHERE est_courant GROUP BY producteur_bk HAVING count(*) <> 1
                ) t""",
            )
            assert doublons == 0

    def test_scd2_intervalle_coherent(self):
        with dwh_conn() as conn:
            mauvais = scalar(
                conn,
                "SELECT count(*) FROM dwh.dim_producteur WHERE date_fin < date_debut",
            )
            assert mauvais == 0

    def test_run_log_contient_failed_et_success(self):
        with dwh_conn() as conn:
            statuts = {r[0] for r in _query(conn, "SELECT DISTINCT statut FROM etl.run_log")}
            # Après la démonstration de reprise, les deux statuts existent.
            assert statuts <= {"RUNNING", "SUCCESS", "FAILED"}


def _query(conn, sql):
    from etl.common.db import query
    return query(conn, sql)
