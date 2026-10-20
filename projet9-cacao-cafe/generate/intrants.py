"""Générateur des distributions d'intrants (source Excel .xlsx).

Un classeur par campagne dans data/inbox/intrants/ : une feuille de données
(une ligne par distribution d'intrant à un producteur) et une feuille
« Référentiel » listant les intrants. Alimente la dimension dim_intrant et le
fait fait_intrants (relie intrants, rendement et coûts de marge).

Exemples :
    python generate/intrants.py --scale 0.01
    python generate/intrants.py --scale 1.0
"""

from __future__ import annotations

import argparse
import glob
import json
import os

try:
    from .common import (
        INBOX_DIR,
        Rng,
        date_campagne,
        ensure_dir,
        load_config,
        load_referentiels,
    )
except ImportError:
    from common import (
        INBOX_DIR,
        Rng,
        date_campagne,
        ensure_dir,
        load_config,
        load_referentiels,
    )

try:
    from openpyxl import Workbook
except ImportError:
    raise SystemExit("openpyxl manquant. Installez-le :  pip install openpyxl")

DISTRIBUTIONS_FULL = 40_000

INTRANTS = [
    ("INT-001", "Engrais", "NPK 20-10-10 (sac 50 kg)", "sac", 18000),
    ("INT-002", "Engrais", "Urée 46% (sac 50 kg)", "sac", 16500),
    ("INT-003", "Engrais", "Sulfate de potasse (sac 50 kg)", "sac", 21000),
    ("INT-004", "Produit phytosanitaire", "Fongicide cuprique (L)", "litre", 4500),
    ("INT-005", "Produit phytosanitaire", "Insecticide (L)", "litre", 6000),
    ("INT-006", "Matériel", "Machette", "unité", 3500),
    ("INT-007", "Matériel", "Sécateur", "unité", 5000),
    ("INT-008", "Matériel", "Sac de jute (60 kg)", "unité", 1200),
    ("INT-009", "Semence", "Semence améliorée cacao (kg)", "kg", 2500),
    ("INT-010", "Semence", "Semence améliorée café (kg)", "kg", 2200),
]

OUT_DIR = INBOX_DIR / "intrants"

COLONNES = ["distribution_id", "producteur_id", "cooperative_id", "date_distribution",
            "intrant_id", "quantite", "unite", "cout_fcfa", "campagne"]


def _campagne(d) -> str:
    return f"{d.year}/{d.year + 1}" if d.month >= 10 else f"{d.year - 1}/{d.year}"


def generer(scale: float, seed: int, snapshot: str, out_dir=None):
    from pathlib import Path
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    cfg = load_config(scale=scale, seed=seed, snapshot=snapshot)
    rng = Rng(cfg.seed)
    refs = load_referentiels(cfg.snapshot)
    producteurs = list(refs["producteurs"].values())
    n = cfg.count(DISTRIBUTIONS_FULL, minimum=200)

    ensure_dir(out_dir)
    for ancien in glob.glob(str(out_dir / "intrants_*.xlsx")):
        os.remove(ancien)

    par_campagne: dict[str, list[dict]] = {}
    for i in range(1, n + 1):
        prod = rng.choice(producteurs)
        culture = prod["culture"]
        intrant = rng.choice(INTRANTS)
        date = date_campagne(culture, rng)
        quantite = rng.randint(1, 40)
        cout = quantite * intrant[4]
        camp = _campagne(date)
        par_campagne.setdefault(camp, []).append({
            "distribution_id": f"DIS-{i:07d}",
            "producteur_id": prod["producteur_id"],
            "cooperative_id": prod["cooperative_id"],
            "date_distribution": date.isoformat(),
            "intrant_id": intrant[0],
            "quantite": quantite,
            "unite": intrant[3],
            "cout_fcfa": cout,
            "campagne": camp,
        })

    for camp in sorted(par_campagne):
        wb = Workbook()
        ws = wb.active
        ws.title = "Distributions"
        ws.append(COLONNES)
        for row in par_campagne[camp]:
            ws.append([row[c] for c in COLONNES])
        ws2 = wb.create_sheet("Referentiel")
        ws2.append(["intrant_id", "famille", "nom", "unite", "prix_unitaire_fcfa"])
        for it in INTRANTS:
            ws2.append(list(it))
        nom = camp.replace("/", "-")
        wb.save(out_dir / f"intrants_{nom}.xlsx")

    (out_dir / "_manifest.json").write_text(
        json.dumps({"snapshot": cfg.snapshot, "scale": cfg.scale, "seed": cfg.seed,
                    "distributions": n, "fichiers": len(par_campagne)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return n, len(par_campagne)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Génère les distributions d'intrants (Excel).")
    parser.add_argument("--scale", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--out-dir", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    n, nf = generer(args.scale, args.seed, args.snapshot, args.out_dir)
    print(f"Distributions d'intrants : {n} ({nf} classeurs Excel) dans data/inbox/intrants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())