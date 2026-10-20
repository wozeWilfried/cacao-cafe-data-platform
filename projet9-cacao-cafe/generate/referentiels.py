"""Générateur des référentiels : coopératives, producteurs, parcelles.

Sorties (déposées dans data/inbox/referentiels) :
  - cooperatives_<snapshot>.csv        : référentiel des coopératives ;
  - producteurs_parcelles_<snapshot>.geojson : une entité par parcelle, avec les
    attributs du producteur (comme prévu par le guide pour la source « Parcelles
    et producteurs » au format GeoJSON) ;
  - _manifest.json                      : trace (graine, échelle, comptages).

Reproductible : même graine + même échelle => fichiers identiques.

Exemples :
    python generate/referentiels.py --scale 0.01        # développement
    python generate/referentiels.py --scale 1.0         # volumétrie cible
    python generate/referentiels.py --snapshot 2022-10-01
"""

from __future__ import annotations

import argparse
import json
from datetime import date

try:  # exécution en module : python -m generate.referentiels
    from .common import (
        CERTIFICATIONS,
        REFERENTIELS_DIR,
        REGIONS,
        STATUTS_COOPERATIVE,
        STATUTS_PRODUCTEUR,
        VARIETES,
        Rng,
        dates_between,
        ensure_dir,
        iso_ts,
        jitter_point,
        load_config,
        person,
        polygon_around,
        write_csv,
        write_geojson,
    )
except ImportError:  # exécution en script : python generate/referentiels.py
    from common import (
        CERTIFICATIONS,
        REFERENTIELS_DIR,
        REGIONS,
        STATUTS_COOPERATIVE,
        STATUTS_PRODUCTEUR,
        VARIETES,
        Rng,
        dates_between,
        ensure_dir,
        iso_ts,
        jitter_point,
        load_config,
        person,
        polygon_around,
        write_csv,
        write_geojson,
    )

# Poids de répartition des coopératives par région (bassins de production).
POIDS_REGIONS = [
    ("Sud-Ouest", 0.22),
    ("Sud", 0.20),
    ("Centre", 0.18),
    ("Est", 0.15),
    ("Littoral", 0.10),
    ("Ouest", 0.08),
    ("Nord-Ouest", 0.07),
]

# Volumétrie cible à l'échelle 1.0.
COOPERATIVES_FULL = 48
PRODUCTEURS_FULL = 9000
PARCELLES_FULL = 15000

COOP_ID_W = 4
PROD_ID_W = 6
PARC_ID_W = 7


def _culture(region: str, rng: Rng) -> str:
    options = list(REGIONS[region]["cultures"].items())
    return rng.weighted(options)


def _telephone(rng: Rng) -> str:
    prefixe = rng.choice(["65", "67", "69", "62", "66", "68"])
    return f"+237{prefixe}{rng.randint(0, 999999):06d}"


def generer(scale: float, seed: int, snapshot: str, out_dir=None):
    cfg = load_config(scale=scale, seed=seed, snapshot=snapshot)
    from pathlib import Path
    out_dir = Path(out_dir) if out_dir else REFERENTIELS_DIR
    rng = Rng(cfg.seed)
    maj_le = iso_ts(cfg.snapshot)
    snapshot_date = date.fromisoformat(cfg.snapshot)

    n_coop = cfg.count(COOPERATIVES_FULL, minimum=6)
    n_prod = cfg.count(PRODUCTEURS_FULL, minimum=80)
    n_parc = cfg.count(PARCELLES_FULL, minimum=120)

    # --- Coopératives -------------------------------------------------------
    cooperatives: list[dict] = []
    for i in range(1, n_coop + 1):
        region = rng.weighted(POIDS_REGIONS)
        info = REGIONS[region]
        ville = rng.choice(info["villes"])
        departement = rng.choice(info["departements"])
        lat, lon = jitter_point(region, rng)
        prenom, nom, _ = person(rng)
        cooperatives.append(
            {
                "cooperative_id": f"COOP-{i:0{COOP_ID_W}d}",
                "nom": f"Coopérative Agricole de {ville} ({i:02d})",
                "region": region,
                "departement": departement,
                "ville": ville,
                "latitude": lat,
                "longitude": lon,
                "capacite_stockage_t": rng.randint(50, 2000),
                "responsable": f"{prenom} {nom}",
                "certification": rng.weighted(CERTIFICATIONS),
                "statut": rng.weighted(STATUTS_COOPERATIVE),
                "date_creation": dates_between(
                    date(2005, 1, 1), date(2021, 12, 31), rng
                ).isoformat(),
                "maj_le": maj_le,
            }
        )

    # --- Producteurs --------------------------------------------------------
    producteurs: list[dict] = []
    for i in range(1, n_prod + 1):
        coop = cooperatives[(i - 1) % n_coop]
        region = coop["region"]
        prenom, nom, sexe = person(rng)
        annee_naissance = rng.randint(1960, 2003)
        annee_creation = int(coop["date_creation"][:4])
        annee_adhesion = rng.randint(annee_creation, snapshot_date.year)
        producteurs.append(
            {
                "producteur_id": f"PROD-{i:0{PROD_ID_W}d}",
                "cooperative_id": coop["cooperative_id"],
                "nom": f"{prenom} {nom}",
                "sexe": sexe,
                "annee_naissance": annee_naissance,
                "culture": _culture(region, rng),
                "region": region,
                "telephone": _telephone(rng),
                "annee_adhesion": annee_adhesion,
                "certification": rng.weighted(CERTIFICATIONS),
                "statut": rng.weighted(STATUTS_PRODUCTEUR),
                "maj_le": maj_le,
            }
        )

    # Nombre d'adhérents par coopérative = producteurs rattachés.
    adher = {c["cooperative_id"]: 0 for c in cooperatives}
    for p in producteurs:
        adher[p["cooperative_id"]] += 1
    for c in cooperatives:
        c["nb_adherents"] = adher[c["cooperative_id"]]

    # --- Parcelles ----------------------------------------------------------
    # Chaque producteur reçoit au moins une parcelle, puis on complète.
    parcelles_par_prod: dict[str, int] = {p["producteur_id"]: 1 for p in producteurs}
    restant = n_parc - n_prod
    while restant > 0:
        p = rng.choice(producteurs)
        if parcelles_par_prod[p["producteur_id"]] < 6:
            parcelles_par_prod[p["producteur_id"]] += 1
            restant -= 1

    features: list[dict] = []
    parc_num = 0
    for p in producteurs:
        for _ in range(parcelles_par_prod[p["producteur_id"]]):
            parc_num += 1
            surface_ha = round(rng.uniform(0.3, 6.0), 2)
            lat, lon = jitter_point(p["region"], rng)
            variete = rng.choice(VARIETES[p["culture"]])
            annee_plantation = rng.randint(1990, min(2020, p["annee_adhesion"] + 25))
            parcelle_id = f"PARC-{parc_num:0{PARC_ID_W}d}"
            ring = polygon_around(lat, lon, surface_ha, rng)
            features.append(
                {
                    "type": "Feature",
                    "id": parcelle_id,
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {
                        "parcelle_id": parcelle_id,
                        "producteur_id": p["producteur_id"],
                        "nom": p["nom"],
                        "sexe": p["sexe"],
                        "annee_naissance": p["annee_naissance"],
                        "cooperative_id": p["cooperative_id"],
                        "culture": p["culture"],
                        "variete": variete,
                        "surface_ha": surface_ha,
                        "annee_plantation": annee_plantation,
                        "certification": p["certification"],
                        "region": p["region"],
                        "statut": p["statut"],
                        "maj_le": maj_le,
                    },
                }
            )

    # --- Écriture -----------------------------------------------------------
    ensure_dir(out_dir)
    coop_cols = [
        "cooperative_id", "nom", "region", "departement", "ville", "latitude",
        "longitude", "capacite_stockage_t", "responsable", "certification",
        "statut", "date_creation", "nb_adherents", "maj_le",
    ]
    coop_path = out_dir / f"cooperatives_{cfg.snapshot}.csv"
    geo_path = out_dir / f"producteurs_parcelles_{cfg.snapshot}.geojson"
    write_csv(coop_path, cooperatives, coop_cols)
    write_geojson(geo_path, features)

    manifest = {
        "snapshot": cfg.snapshot,
        "scale": cfg.scale,
        "seed": cfg.seed,
        "cooperatives": len(cooperatives),
        "producteurs": len(producteurs),
        "parcelles": len(features),
        "fichiers": [coop_path.name, geo_path.name],
    }
    (out_dir / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return manifest, coop_path, geo_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère les référentiels (coopératives, producteurs, parcelles)."
    )
    parser.add_argument("--scale", type=float, default=None, help="0.01 (dev) .. 1.0 (complet)")
    parser.add_argument("--seed", type=int, default=None, help="graine aléatoire (défaut 42)")
    parser.add_argument("--snapshot", default=None, help="date du millésime AAAA-MM-JJ")
    parser.add_argument("--out-dir", default=None, help="répertoire de sortie")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.scale, args.seed, args.snapshot)
    out_dir = args.out_dir or REFERENTIELS_DIR
    manifest, coop_path, geo_path = generer(cfg.scale, cfg.seed, cfg.snapshot, out_dir)
    print("Référentiels générés :")
    print(f"  coopératives : {manifest['cooperatives']:>6}")
    print(f"  producteurs  : {manifest['producteurs']:>6}")
    print(f"  parcelles    : {manifest['parcelles']:>6}")
    print(f"  -> {coop_path}")
    print(f"  -> {geo_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
