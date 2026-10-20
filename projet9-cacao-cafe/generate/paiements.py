"""Générateur des paiements Mobile Money (source JSON, un fichier par jour).

Lit les livraisons en base (`coop.livraison`) et en génère le paiement
correspondant : opérateur (MTN MoMo, Orange Money, virement, espèces), montant
en FCFA, frais, statut et horodatage. Les fichiers sont déposés dans
data/inbox/paiements/paiements_YYYY-MM-DD.json (un par jour, comme le guide).

Le paiement s'applique à une fraction des livraisons (une part reste impayée,
une minorité est annulée) — c'est ce qui alimente le journal `etl.fichier_traite`
et les modifications « statut ANNULE » des scénarios de run.

Exemples :
    python generate/paiements.py --taux 0.92
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
from urllib.parse import urlparse

try:
    from .common import (
        PAIEMENTS_DIR,
        PRIX_REFC,
        Rng,
        ensure_dir,
        load_config,
        load_env,
    )
except ImportError:
    from common import (
        PAIEMENTS_DIR,
        PRIX_REFC,
        Rng,
        ensure_dir,
        load_config,
        load_env,
    )

try:
    import psycopg
except ImportError:
    raise SystemExit("psycopg manquant. Installez-le :  pip install 'psycopg[binary]'")

OPERATEURS = [("MTN_MOMO", 0.45), ("ORANGE_MONEY", 0.35), ("VIREMENT", 0.12), ("ESPECES", 0.08)]
STATUTS = [("PAYE", 0.94), ("ANNULE", 0.03), ("EN_ATTENTE", 0.03)]


def _connexion():
    load_env()
    url = urlparse(os.environ["SRC_URL"])
    return psycopg.connect(
        host=url.hostname, port=url.port, dbname=url.path.lstrip("/"),
        user=url.username, password=url.password,
    )


def _lire_livraisons(conn) -> list[tuple]:
    """(livraison_id, producteur_id, date_livraison, poids_net_kg, produit)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT livraison_id, producteur_id, date_livraison, poids_net_kg, produit "
            "FROM coop.livraison ORDER BY livraison_id"
        )
        return cur.fetchall()


def generer(taux: float, seed: int, snapshot: str, out_dir=None):
    from pathlib import Path
    out_dir = Path(out_dir) if out_dir else PAIEMENTS_DIR
    cfg = load_config(seed=seed, snapshot=snapshot)
    rng = Rng(cfg.seed)

    with _connexion() as conn:
        livraisons = _lire_livraisons(conn)
    if not livraisons:
        raise SystemExit("Aucune livraison en base. Lancez d'abord generate/livraisons.py")

    par_jour: dict[str, list[dict]] = {}
    nb = 0
    for liv_id, prod_id, date_liv, net_kg, produit in livraisons:
        if rng.random() > taux:
            continue  # livraison non payée (impayée)
        date_liv = date_liv if isinstance(date_liv, dt.date) else date_liv.date()
        montant = int(round(float(net_kg) * PRIX_REFC.get(produit, 2500.0) * rng.uniform(0.92, 1.08)))
        operateur = rng.weighted(OPERATEURS)
        frais = int(montant * 0.015) if operateur in ("MTN_MOMO", "ORANGE_MONEY") else 0
        statut = rng.weighted(STATUTS)
        jour = date_liv + dt.timedelta(days=rng.randint(1, 15))
        horodatage = dt.datetime.combine(jour, dt.time(rng.randint(6, 22), rng.randint(0, 59)))
        record = {
            "paiement_id": f"PAY-{nb + 1:08d}",
            "livraison_id": liv_id,
            "producteur_id": prod_id,
            "operateur": operateur,
            "montant_fcfa": montant,
            "frais_fcfa": frais,
            "statut": statut,
            "horodatage": horodatage.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        par_jour.setdefault(jour.isoformat(), []).append(record)
        nb += 1

    ensure_dir(out_dir)
    for ancien in glob.glob(str(out_dir / "paiements_*.json")):
        os.remove(ancien)  # rejouabilité : on repart d'un répertoire propre
    for jour in sorted(par_jour):
        path = out_dir / f"paiements_{jour}.json"
        path.write_text(
            json.dumps(par_jour[jour], ensure_ascii=False, indent=1), encoding="utf-8"
        )

    (out_dir / "_manifest.json").write_text(
        json.dumps(
            {"taux": taux, "seed": cfg.seed, "paiements": nb,
             "fichiers": len(par_jour)},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return nb, len(par_jour)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Génère les paiements (JSON/jour) depuis les livraisons.")
    parser.add_argument("--taux", type=float, default=0.92, help="part des livraisons payées (défaut 0.92)")
    parser.add_argument("--seed", type=int, default=None, help="graine aléatoire")
    parser.add_argument("--snapshot", default=None, help="millésime des référentiels")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    nb, nj = generer(args.taux, args.seed, args.snapshot)
    print(f"Paiements générés : {nb} (taux {args.taux:.0%})")
    print(f"Fichiers journaliers : {nj} dans data/inbox/paiements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())