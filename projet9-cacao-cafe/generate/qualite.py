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
        "Aucun défaut majeur relevé, humidité {h}% dans les normes.",
        "Réception acceptée, aspect homogène, défauts {d}%.",
        "Lot propre, pas de corps étrangers, humidité {h}%.",
        "Contrôle de routine satisfaisant, {g} grains examinés.",
        "Marchandise conforme au cahier des charges, séchage correct.",
        "Échantillon de {g} grains analysé, qualité moyenne, aucun défaut critique.",
        "Lot accepté après tri de contrôle, humidité {h}% mesurée au laboratoire.",
    ],
    "MOISISSURE": [
        "Odeur de moisissure au déchargement, humidité {h}%. Lot à réexaminer.",
        "Présence de moisissure sur une partie du lot ({d}% de grains affectés).",
        "Moisissure détectée à l'ouverture des sacs, {g} grains contrôlés.",
        "Grains moisis repérés au tri, quelques sacs atteints, humidité {h}%.",
        "Développement fongique sur le lot inférieur, odeur de renfermé.",
        "Moisissure blanche visible sur plusieurs prélèvements, {d}% estimé.",
        "Léger moisi sur la couche superficielle, à surveiller au séchage.",
        "Contamination par moisissure confirmée au laboratoire.",
        "Taches de moisissure sur grains, lot refusé pour ce défaut.",
        "Présence de mycélium blanc, odeur de moisi signalée à {ville}.",
    ],
    "GRAINS_ARDOSES": [
        "Défauts : grains ardoisés nombreux ({d}%), qualité visuelle altérée.",
        "Grains ardoisés observés lors du tri, taux {d}% jugé excessif.",
        "Part du lot présentant des grains ardoisés au-delà de la tolérance.",
        "Coloration ardoisée anormale sur grains, fermentation suspectée.",
        "Grains vitreux et ardoisés repérés à la coupe, {d}% affectés.",
        "Teinte ardoisée marquée, défaut de fermentation relevé.",
        "Aspect ardoisé sur une fraction du lot, qualité déclassée.",
        "Grains noirs et ardoisés lors du contrôle visuel.",
        "Défaut de séchage ayant conduit à des grains ardoisés.",
        "Échantillon présentant des grains ardoisés, taux {d}%.",
    ],
    "INFESTATION": [
        "Présence d'insectes dans les sacs ({d}% contaminés), lot placé en quarantaine.",
        "Infestation relevée à la réception, traitement de fumigation recommandé. {g} grains comptés.",
        "Niveau d'infestation élevé : insectes vivants découverts au contrôle initial.",
        "Perforations d'insectes visibles sur grains, activité détectée.",
        "Relevé de larves et insectes adultes dans plusieurs sacs.",
        "Attaque parasitaire en cours, odeur et poussières caractéristiques.",
        "Présence de charançons vivants, taux de contamination {d}%.",
        "Fort taux d'insectes, stock menacé, quarantaine immédiate.",
        "Grains troués par les insectes, infestation confirmée à {ville}.",
        "Détection de vermine dans le lot, dégâts visibles sur {g} grains.",
    ],
    "HUMIDITE_ELEVEE": [
        "Humidité élevée {h}% (> seuil), lot mis en attente de séchage.",
        "Teneur en eau trop importante ({h}%), rejet pour séchage complémentaire.",
        "Humidité hors norme {h}% détectée au laboratoire, décision de rejet.",
        "Lot humide au toucher, humidité mesurée {h}% supérieure au seuil.",
        "Excès d'humidité {h}%, risque de moisissure, séchage requis.",
        "Grains collants et lourds, humidité {h}% au contrôle.",
        "Mesure d'humidité {h}% trop élevée, lot écarté pour séchage.",
        "Taux d'eau anormal ({h}%), qualité compromise.",
        "Humidité excessive relevée {h}%, conforme au rejet pour séchage.",
        "Échantillon humide, valeur {h}% au-dessus de la tolérance.",
    ],
    "ODEUR_FUMEE": [
        "Odeur de fumée perçue à l'ouverture, qualité organoleptique dégradée.",
        "Défaut d'odeur (fumée) constaté à {ville}, réception refusée.",
        "Odeur de fumée notable, rejet du lot conformément au cahier des charges.",
        "Grains imprégnés d'odeur de fumée, arôme altéré.",
        "Odeur persistante de brûlé au nez, lot non conforme.",
        "Senteur de fumée prononcée, test organoleptique défavorable.",
        "Contamination olfactive par fumée signalée à {ville}.",
        "Neurones aromatiques altérés par une odeur de fumée.",
        "Odeur de fumée marquée sur {g} grains prélevés, lot déclassé.",
        "Défaut organoleptique : fumée détectée au déchargement.",
    ],
    "CORPS_ETRANGERS": [
        "Corps étrangers (cailloux, débris végétaux) : {d}% estimé au tri.",
        "Présence de corps étrangers dans le lot, contrôle du taux de pureté.",
        "Impuretés détectées ({d}% de corps étrangers), lot rejeté au contrôle de qualité.",
        "Cailloux et débris végétaux relevés, taux de pureté insuffisant.",
        "Matières inertes mélangées au lot, nettoyage nécessaire.",
        "Éléments étrangers (sable, graines sauvages) repérés, {d}%.",
        "Impuretés diverses au tamisage, qualité non conforme.",
        "Présence de fragments de sac et graviers dans le lot.",
        "Corps étrangers abondants détectés à {ville}, tri complémentaire.",
        "Lot pollué par des débris, taux d'inertes {d}%.",
    ],
}

SEUIL_HUMIDITE = 9.5
SEUIL_DEFAUTS = 12.0

# Défauts « secondaires » pouvant co-occurrer (10-15 % de phrases multi-défauts).
DEFECTS = ["MOISISSURE", "GRAINS_ARDOSES", "INFESTATION", "HUMIDITE_ELEVEE",
           "ODEUR_FUMEE", "CORPS_ETRANGERS"]


def _fautes(texte: str, rng: Rng) -> str:
    """Introduit légèrement des fautes (frappe/accents) pour robustifier le NLP."""
    if rng.random() > 0.35:
        return texte
    substitutions = [("humidité", "humidity"), ("moisissure", "moisisure"),
                     ("odeur", "odeure"), ("grains", "grain"), ("défauts", "défaut"),
                     ("contrôle", "controlle"), ("présence", "presance")]
    for a, b in substitutions:
        if a in texte and rng.random() < 0.5:
            texte = texte.replace(a, b, 1)
    # Amendements des accents disparates (déjà l'orientation du corpus).
    if rng.random() < 0.5:
        texte = texte.replace("é", "e", 1)
    return texte


def _observation(rng: Rng, defaut: str, h: float, g: int, d: float, ville: str) -> str:
    texte = rng.choice(TEMPLATES[defaut]).format(h=f"{h:.1f}", g=g, d=f"{d:.1f}", ville=ville)
    # 10-15 % de phrases multi-défauts : on accole une clause d'un autre défaut.
    if defaut != "CONFORME" and rng.random() < 0.13:
        autre = rng.choice([x for x in DEFECTS if x != defaut])
        texte += " " + rng.choice(TEMPLATES[autre]).format(
            h=f"{h:.1f}", g=g, d=f"{d:.1f}", ville=ville)
    return _fautes(texte, rng)


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

        # Décision de rejet PROBABILISTE (guide, ML2 Précaution) : on adoucit les
        # seuils physiques par une probabilité logistique au lieu d'une règle
        # exacte. Un modèle ML apprend la frontière sans pouvoir l'inverser
        # parfaitement (la décision Bernoulli reste en partie imprévisible).
        # Calé pour ~5-6 % de refus (rejet rare).
        import math
        score = 0.8 * ((humidite - SEUIL_HUMIDITE) + (defectueux - SEUIL_DEFAUTS) / 3.0)
        p_rejet = 1.0 / (1.0 + math.exp(-score))
        refuse = rng.random() < p_rejet
        if refuse:
            decision = "REFUSE"
            if humidite > SEUIL_HUMIDITE and defectueux <= SEUIL_DEFAUTS:
                defaut_principal = "HUMIDITE_ELEVEE"
            elif rng.random() < 0.25:
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