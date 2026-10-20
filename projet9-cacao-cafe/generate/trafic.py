"""Générateur du trafic portuaire (source CSV, un fichier par mois).

Fichiers data/inbox/trafic/trafic_portuaire_YYYY-MM.csv : une ligne par escale
(mouvement de navire) aux ports de Douala et Kribi. Alimente l'indicateur 25
(attente à quai, retards de chargement).

Exemples :
    python generate/trafic.py --scale 0.01
    python generate/trafic.py --scale 1.0
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os

try:
    from .common import (
        TRAFIC_DIR,
        PORTS,
        Rng,
        ensure_dir,
        load_config,
        write_csv,
    )
except ImportError:
    from common import (
        TRAFIC_DIR,
        PORTS,
        Rng,
        ensure_dir,
        load_config,
        write_csv,
    )

ESCALES_FULL = 4000

NAVIRES = [
    "MSC Ambition", "Maersk Douala", "CMA CGM Kribi", "Ever Given II",
    "Hapag Lloyd Yaounde", "ONE Cameroun", "COSCO Africa", "Grimaldi Europa",
    "SAFMARINE Nomad", "Bahri Yanbu", "Nordic Orion", "Atlantic Star",
]
TERMINAUX = {
    "Douala": ["TCDA - Bonabéri", "APMT Douala", "Port autonome de Douala"],
    "Kribi": ["KCT - Kribi Containers Terminal", "Môle polyvalent de Kribi"],
}

COLONNES = [
    "escale_id", "port", "navire", "date_arrivee", "date_depart",
    "conteneurs", "tonnage_t", "terminal", "statut",
]


def generer(scale: float, seed: int, snapshot: str, out_dir=None):
    from pathlib import Path
    out_dir = Path(out_dir) if out_dir else TRAFIC_DIR
    cfg = load_config(scale=scale, seed=seed, snapshot=snapshot)
    rng = Rng(cfg.seed)
    n = cfg.count(ESCALES_FULL, minimum=40)

    ensure_dir(out_dir)
    for ancien in glob.glob(str(out_dir / "trafic_portuaire_*.csv")):
        os.remove(ancien)

    par_mois: dict[str, list[dict]] = {}
    for i in range(1, n + 1):
        port = rng.weighted([("Douala", 0.68), ("Kribi", 0.32)])
        navire = rng.choice(NAVIRES)
        annee_debut = rng.randint(2022, 2025)
        arrivee = dt.datetime(annee_debut, rng.randint(10, 12), rng.randint(1, 28),
                              rng.randint(0, 23), rng.randint(0, 59))
        # Attente à quai : jusqu'à plusieurs jours (retards de chargement).
        attente_h = rng.randint(6, 120)
        depart = arrivee + dt.timedelta(hours=attente_h + rng.randint(4, 30))
        tonnage = round(rng.uniform(2000, 40000), 2)
        statut = "A_QUAI" if rng.random() < 0.15 else rng.weighted(
            [("EN_ATTENTE", 0.35), ("CHARGE", 0.65)])
        escale = {
            "escale_id": f"ESC-{i:06d}",
            "port": port,
            "navire": navire,
            "date_arrivee": arrivee.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date_depart": depart.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "conteneurs": rng.randint(20, 900),
            "tonnage_t": tonnage,
            "terminal": rng.choice(TERMINAUX[port]),
            "statut": statut,
        }
        par_mois.setdefault(arrivee.strftime("%Y-%m"), []).append(escale)

    for mois in sorted(par_mois):
        write_csv(out_dir / f"trafic_portuaire_{mois}.csv", par_mois[mois], COLONNES)

    (out_dir / "_manifest.json").write_text(
        json.dumps({"snapshot": cfg.snapshot, "scale": cfg.scale, "seed": cfg.seed,
                    "escales": n, "fichiers": len(par_mois)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return n, len(par_mois)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Génère le trafic portuaire (CSV mensuel).")
    parser.add_argument("--scale", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--out-dir", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    n, nf = generer(args.scale, args.seed, args.snapshot, args.out_dir)
    print(f"Escales générées : {n} ({nf} fichiers CSV mensuels) dans data/inbox/trafic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())