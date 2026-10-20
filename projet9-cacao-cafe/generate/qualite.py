"""Générateur du contrôle qualité des lots (source JSON).

Produit un fichier JSON par mois de date_analyse dans data/inbox/qualite :
    controles_qualite_YYYY-MM.json   (tableau d'enregistrements)

Champs conformes au guide : lot_id, cooperative_id, date_reception,
date_analyse, humidite_pct, nb_grains_comptes, grains_defectueux_pct, grade,
decision, observation. Le champ `defaut_principal` porte l'étiquette réelle
des observations (base du NLP1 « classification des défauts »).

Reproductible : graine fixe + échelle. Volume cible ~150 000 contrôles.

Exemples :
    python generate/qualite.py --scale 0.01        # ~1 500 contrôles (dev)
    python generate/qualite.py --scale 1.0         # ~150 000 contrôles
"""

from __future__ import annotations

import argparse
import datetime as dt
import json

try:
    from .common import (
        QUALITE_DIR,
        Rng,
        date_campagne,
        ensure_dir,
        load_config,
        load_referentiels,
    )
except ImportError:
    from common import (
        QUALITE_DIR,
        Rng,
        date_campagne,
        ensure_dir,
        load_config,
        load_referentiels,
    )

QUALITE_FULL = 150_000

OUT_DIR = QUALITE_DIR

DEFAUTS = ["MOISISSURE", "GRAINS_ARDOSES", "INFESTATION", "HUMIDITE_ELEVEE", "ODEUR_FUMEE", "CORPS_ETRANGERS"]

# Poids d'apparition des défauts hors humidité (lots refusés pour défauts).
POIDS_DEFAUT = [
    ("MOISISSURE", 0.28),
    ("INFESTATION", 0.22),
    ("GRAINS_ARDOSES", 0.18),
    ("CORPS_ETRANGERS", 0.18),
    ("ODEUR_FUMEE", 0.14),
]

TEMPLATES: dict[str, list[str]] = {
    "CONFORME": [
        "Contrôle ok : humidité {h}%, {g} grains comptés, défauts {d}%. Lot conforme à la réception.",
        "Lot conforme, normes respectées (humidité {h}%, taux de défauts {d}%).",
        "Vérification de réception sans anomalie : {g} grains, humidité {h}%.",
    ],
    "MOISISSURE": [
        "Odeur de moisissure au déchargement, humidité {h}%. Lot à réexaminer.",
        "Présence de moisissure sur une partie du lot ({d}% de grains affectés).",
        "Moisissure détectée à l'ouverture des sacs, {g} grains contrôlés.",
    ],
    "GRAINS_ARDOSES": [
        "Défauts : grains ardoisés nombreux ({d}%), qualité visuelle altérée.",
        "Grains ardoisés observés lors du tri, taux {d}% jugé excessif.",
        "Part du lot présentant des grains ardoisés au-delà de la tolérance.",
    ],
    "INFESTATION": [
        "Présence d'insectes dans les sacs ({d}% contaminés), lot placé en quarantaine.",
        "Infestation relevée à la réception, traitement de fumigation recommandé. {g} grains comptés.",
        "Niveau d'infestation élevé : insectes vivants découverts au contrôle initial.",
    ],
    "HUMIDITE_ELEVEE": [
        "Humidité élevée {h}% (> seuil), lot mis en attente de séchage.",
        "Teneur en eau trop importante ({h}%), rejet pour séchage complémentaire.",
        "Humidité hors norme {h}% détectée au laboratoire, décision de rejet.",
    ],
    "ODEUR_FUMEE": [
        "Odeur de fumée perçue à l'ouverture, qualité organoleptique dégradée.",
        "Défaut d'odeur (fumée) constaté à {ville}, réception refusée.",
        "Odeur de fumée notable, rejet du lot conformément au cahier des charges.",
    ],
    "CORPS_ETRANGERS": [
        "Corps étrangers (cailloux, débris végétaux) : {d}% estimé au tri.",
        "Présence de corps étrangers dans le lot, contrôle du taux de pureté.",
        "Impuretés détectées ({d}% de corps étrangers), lot rejeté au contrôle de qualité.",
    ],
}

SEUIL_HUMIDITE = 9.5
SEUIL_DEFAUTS = 12.0


def _observation(rng: Rng, defaut: str, h: float, g: int, d: float, ville: str) -> str:
    texte = rng.choice(TEMPLATES[defaut])
    return texte.format(h=f"{h:.1f}", g=g, d=f"{d:.1f}", ville=ville)


def generer(scale: float, seed: int, snapshot: str, out_dir=None):
    from pathlib import Path
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    cfg = load_config(scale=scale, seed=seed, snapshot=snapshot)
    refs = load_referentiels(cfg.snapshot)
    cooperatives = list(refs["cooperatives"].values())
    n = cfg.count(QUALITE_FULL, minimum=400)
    rng = Rng(cfg.seed)

    lots: dict[str, list[dict]] = {}
    for i in range(1, n + 1):
        culture = rng.weighted([("cacao", 0.8), ("cafe", 0.2)])
        date_reception = date_campagne(culture, rng)
        date_analyse = date_reception + dt.timedelta(days=rng.randint(0, 3))
        coop = rng.choice(cooperatives)

        humidite = max(5.0, min(15.0, round(rng.gauss(7.9, 1.1), 1)))
        grains = rng.randint(100, 300)
        defectueux = max(0.0, min(25.0, round(rng.gauss(4.0, 3.0), 1)))

        if humidite <= 8.0 and defectueux <= 5.0:
            grade = "Grade 1"
        elif humidite <= 9.0 and defectueux <= 10.0:
            grade = "Grade 2"
        else:
            grade = "Grade 3"

        refuse = humidite > SEUIL_HUMIDITE or defectueux > SEUIL_DEFAUTS
        if refuse:
            decision = "REFUSE"
            if humidite > SEUIL_HUMIDITE and defectueux <= SEUIL_DEFAUTS:
                defaut_principal = "HUMIDITE_ELEVEE"
            else:
                defaut_principal = rng.weighted(POIDS_DEFAUT)
        else:
            decision = "ACCEPTE"
            defaut_principal = "CONFORME" if rng.random() > 0.02 else rng.weighted(POIDS_DEFAUT)

        ville = coop.get("ville", "")
        lot = {
            "lot_id": f"LOT-{i:07d}",
            "cooperative_id": coop["cooperative_id"],
            "date_reception": date_reception.isoformat(),
            "date_analyse": date_analyse.isoformat(),
            "humidite_pct": humidite,
            "nb_grains_comptes": grains,
            "grains_defectueux_pct": defectueux,
            "grade": grade,
            "decision": decision,
            "defaut_principal": defaut_principal,
            "observation": _observation(rng, defaut_principal, humidite, grains, defectueux, ville),
        }
        mois = date_analyse.strftime("%Y-%m")
        lots.setdefault(mois, []).append(lot)

    ensure_dir(out_dir)
    nbr = 0
    for mois in sorted(lots):
        path = out_dir / f"controles_qualite_{mois}.json"
        path.write_text(
            json.dumps(lots[mois], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        nbr += 1

    (out_dir / "_manifest.json").write_text(
        json.dumps(
            {"snapshot": cfg.snapshot, "scale": cfg.scale, "seed": cfg.seed,
             "controles": n, "fichiers": nbr},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return cfg, n, nbr


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Génère les contrôles qualité des lots (JSON).")
    parser.add_argument("--scale", type=float, default=None, help="0.01 (dev) .. 1.0 (complet)")
    parser.add_argument("--seed", type=int, default=None, help="graine aléatoire")
    parser.add_argument("--snapshot", default=None, help="millésime des référentiels")
    parser.add_argument("--out-dir", default=None, help="répertoire de sortie")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg, n, nbr = generer(args.scale, args.seed, args.snapshot, args.out_dir)
    print(f"Contrôles qualité générés : {n} (échelle {cfg.scale}, graine {cfg.seed})")
    print(f"Fichiers mensuels         : {nbr} dans data/inbox/qualite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())