"""Dérive un nouvel instantané des référentiels à partir du précédent.

Sert à démontrer le SCD type 2 : entre deux millésimes, une minorité de
producteurs change de coopérative ou obtient une certification, et une
coopérative change de responsable ou de capacité de stockage.

Usage :
    python generate/evolution_referentiels.py \
        --depuis 2022-10-01 --vers 2023-10-01 --taux 0.05
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    REFERENTIELS_DIR,
    Rng,
    ensure_dir,
    iso_ts,
    load_config,
)

CERTIF_MIGRATION = ["Rainforest Alliance", "UTZ", "Fairtrade", "Bio"]


def _lire_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def evoluer(depuis: str, vers: str, taux: float, seed: int) -> tuple[Path, Path]:
    cfg = load_config(seed=seed, snapshot=vers)
    rng = Rng(seed + hash(vers) % 10_000)

    coop_src = REFERENTIELS_DIR / f"cooperatives_{depuis}.csv"
    geo_src = REFERENTIELS_DIR / f"producteurs_parcelles_{depuis}.geojson"
    if not coop_src.exists() or not geo_src.exists():
        raise FileNotFoundError(f"Instantané source {depuis} introuvable.")

    cooperatives = _lire_csv(coop_src)
    coop_ids = [c["cooperative_id"] for c in cooperatives]
    maj_le = iso_ts(cfg.snapshot)

    # --- Mutations coopératives (~10 %) --------------------------------------
    for c in rng.sample(cooperatives, max(1, int(len(cooperatives) * 0.10))):
        if rng.random() < 0.5:
            c["capacite_stockage_t"] = str(int(c["capacite_stockage_t"]) + rng.randint(50, 300))
        else:
            c["responsable"] = f"Responsable {rng.randint(100, 999)}"
        c["maj_le"] = maj_le

    # --- Mutations producteurs (~taux) ---------------------------------------
    geo = json.loads(geo_src.read_text(encoding="utf-8"))
    features = geo["features"]
    prods = {f["properties"]["producteur_id"]: f["properties"] for f in features}
    pid_list = list(prods.keys())
    n_mut = max(1, int(len(pid_list) * taux))
    mutes = set(rng.sample(pid_list, n_mut))

    for pid in mutes:
        prop = prods[pid]
        ancienne = prop["cooperative_id"]
        nouvelle = ancienne
        # Changer de coopérative (différente de l'actuelle).
        while nouvelle == ancienne and len(coop_ids) > 1:
            nouvelle = rng.choice(coop_ids)
        prop["cooperative_id"] = nouvelle
        if rng.random() < 0.4:
            prop["certification"] = rng.choice(CERTIF_MIGRATION)
        prop["maj_le"] = maj_le

    # Propage aux features (chaque feature référence le producteur).
    for f in features:
        p = prods[f["properties"]["producteur_id"]]
        f["properties"]["cooperative_id"] = p["cooperative_id"]
        f["properties"]["certification"] = p["certification"]
        f["properties"]["maj_le"] = maj_le

    # --- Écriture ------------------------------------------------------------
    ensure_dir(REFERENTIELS_DIR)
    coop_cols = list(cooperatives[0].keys())
    coop_out = REFERENTIELS_DIR / f"cooperatives_{vers}.csv"
    geo_out = REFERENTIELS_DIR / f"producteurs_parcelles_{vers}.geojson"
    with coop_out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=coop_cols)
        w.writeheader()
        w.writerows(cooperatives)
    geo_out.write_text(
        json.dumps(geo, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8"
    )
    print(f"  {len(coop_ids)} coopératives, {len(mutes)} producteurs mutés")
    print(f"  -> {coop_out.name}")
    print(f"  -> {geo_out.name}")
    return coop_out, geo_out


def main() -> int:
    parser = argparse.ArgumentParser(description="Évolution des référentiels (SCD2).")
    parser.add_argument("--depuis", required=True, help="instantané source AAAA-MM-JJ")
    parser.add_argument("--vers", required=True, help="nouvel instantané AAAA-MM-JJ")
    parser.add_argument("--taux", type=float, default=0.05, help="part de producteurs mutés")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(f"Évolution {args.depuis} → {args.vers} (taux {args.taux}):")
    evoluer(args.depuis, args.vers, args.taux, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
