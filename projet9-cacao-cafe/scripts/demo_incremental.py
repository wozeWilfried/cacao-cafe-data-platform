"""Démonstration incrémentale : les runs 0→4 du guide (section 07).

Rejoue le scénario de soutenance en modifiant la base source et en exécutant
l'ETL à chaque étape, puis affiche les comptages de l'entrepôt :

  run 0  chargement complet initial
  run 1  insertion de nouvelles livraisons
  run 2  nouvelles + corrections de poids + changements de coopérative (SCD2)
  run 3  nouvelles + modifiées + suppressions (est_supprime)
  run 4  nouvelles, mais échec volontaire puis relance sans doublon

Usage :
    .venv/bin/python scripts/demo_incremental.py --reset
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "generate"))

from etl.common.db import dwh_conn, source_conn, scalar  # noqa: E402
from etl.pipeline import etl_livraisons, etl_referentiels  # noqa: E402


def _comptages(conn) -> dict:
    return {
        "total": scalar(conn, "SELECT count(*) FROM dwh.fait_livraison"),
        "actifs": scalar(conn, "SELECT count(*) FROM dwh.fait_livraison WHERE NOT est_supprime"),
        "supprimes": scalar(conn, "SELECT count(*) FROM dwh.fait_livraison WHERE est_supprime"),
        "prod_dim": scalar(conn, "SELECT count(*) FROM dwh.dim_producteur"),
        "prod_courants": scalar(conn, "SELECT count(*) FROM dwh.dim_producteur WHERE est_courant"),
    }


def _afficher(run: int, titre: str, c: dict) -> None:
    print(f"\n=== run {run} · {titre} ===")
    print(f"  fait_livraison total    : {c['total']:>8}")
    print(f"    dont actifs           : {c['actifs']:>8}")
    print(f"    dont supprimés        : {c['supprimes']:>8}")
    print(f"  dim_producteur (lignes) : {c['prod_dim']:>8}  dont courantes {c['prod_courants']}")


# -----------------------------------------------------------------------------
# Mutations de la source
# -----------------------------------------------------------------------------
def _refs(src):
    with src.cursor() as cur:
        cur.execute("SELECT producteur_id FROM coop.producteur")
        prods = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT cooperative_id FROM coop.cooperative")
        coops = [r[0] for r in cur.fetchall()]
    return prods, coops


def _derniers_ids(src, n: int) -> list[int]:
    with src.cursor() as cur:
        cur.execute("SELECT livraison_id FROM coop.livraison ORDER BY livraison_id DESC LIMIT %s", (n,))
        return [r[0] for r in cur.fetchall()]


def inserer_livraisons(src, n: int, rng: random.Random) -> list[int]:
    prods, coops = _refs(src)
    nouveaux = []
    with src.cursor() as cur:
        for _ in range(n):
            net = rng.randint(5000, 8000)
            brut = net + rng.randint(50, 400)   # poids_brut >= poids_net (R03)
            cur.execute(
                """INSERT INTO coop.livraison
                   (producteur_id, cooperative_id, produit, date_livraison,
                    poids_brut_kg, poids_net_kg, nb_sacs)
                   VALUES (%s, %s, %s, CURRENT_DATE, %s, %s, %s) RETURNING livraison_id""",
                (rng.choice(prods), rng.choice(coops), rng.choice(["CACAO", "CAFE"]),
                 brut, net, rng.randint(80, 140)),
            )
            nouveaux.append(cur.fetchone()[0])
    return nouveaux


def corriger_poids(src, ids: list[int]) -> int:
    with src.cursor() as cur:
        cur.execute(
            "UPDATE coop.livraison SET poids_net_kg = ROUND(poids_net_kg * 0.95, 2) "
            "WHERE livraison_id = ANY(%s)",
            (ids,),
        )
        return cur.rowcount


def changer_cooperatives(src, n: int, rng: random.Random) -> int:
    prods, coops = _refs(src)
    choisis = rng.sample(prods, min(n, len(prods)))
    with src.cursor() as cur:
        for pid in choisis:
            cur.execute(
                "UPDATE coop.producteur SET cooperative_id = %s, updated_at = now() "
                "WHERE producteur_id = %s",
                (rng.choice(coops), pid),
            )
    return len(choisis)


def supprimer_livraisons(src, ids: list[int]) -> int:
    with src.cursor() as cur:
        cur.execute("DELETE FROM coop.livraison WHERE livraison_id = ANY(%s)", (ids,))
        return cur.rowcount


# -----------------------------------------------------------------------------
# Orchestration du scénario
# -----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Démo incrémentale runs 0→4.")
    parser.add_argument("--reset", action="store_true",
                        help="recharger d'abord l'état complet (run 0)")
    parser.add_argument("--snapshot", default="2022-10-01")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    with dwh_conn(autocommit=True) as dwh:
        with source_conn() as src:
            if args.reset:
                # Run 0 : chargement complet initial.
                etl_referentiels(dwh, args.snapshot)
                etl_referentiels(dwh, "2023-10-01")
                run = etl_livraisons(dwh, mode="FULL")
                _afficher(0, f"FULL initial ({run.compteurs['inserees']} insérées)",
                          _comptages(dwh))

            # run 1 : nouvelles livraisons.
            inserer_livraisons(src, 4200, rng)
            src.commit()
            etl_livraisons(dwh, mode="INCR")
            _afficher(1, "4 200 nouvelles livraisons", _comptages(dwh))

            # run 2 : nouvelles + corrections + changements de coopérative.
            # Le SCD2 provient des instantanés GeoJSON : le snapshot 2023-10-01
            # contient les producteurs mutés (cf. generate/evolution_referentiels.py).
            nouveaux2 = inserer_livraisons(src, 3100, rng)
            corriger_poids(src, nouveaux2[:900])
            src.commit()
            etl_referentiels(dwh, "2023-10-01")   # SCD2 : nouvelles versions
            etl_livraisons(dwh, mode="INCR")
            _afficher(2, "3 100 nouvelles, 900 corrections, changements coop (SCD2)",
                      _comptages(dwh))

            # run 3 : nouvelles + modifiées + suppressions.
            # On supprime 400 livraisons DÉJÀ chargées (celles du run 2).
            inserer_livraisons(src, 1800, rng)
            cibles = nouveaux2[:400]
            supprimer_livraisons(src, cibles)
            src.commit()
            etl_livraisons(dwh, mode="INCR")
            _afficher(3, "1 800 nouvelles, 400 supprimées (journal CDC)", _comptages(dwh))

            # run 4 : nouvelles + échec volontaire puis relance.
            inserer_livraisons(src, 2500, rng)
            src.commit()
            try:
                etl_livraisons(dwh, mode="INCR", echouer=True)
            except Exception as exc:  # noqa: BLE001
                print(f"\n  ! run 4 échoué volontairement : {type(exc).__name__}")
            c_failed = _comptages(dwh)
            _afficher("4 (FAILED)", "après échec : inchangé", c_failed)
            etl_livraisons(dwh, mode="INCR")
            _afficher("4 (relance)", "2 500 nouvelles, zéro doublon", _comptages(dwh))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
