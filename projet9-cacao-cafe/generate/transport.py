"""Générateur des logs GPS de transport (source : logs texte).

Un fichier texte par trajet dans data/inbox/transport/, plus un fichier d'index.
Chaque ligne est un « ping » : horodatage, camion, lot, lat/lon, vitesse,
événement (DEPART, ARRIVEE, ARRET, FUMIGATION, ARRIVEE_PORT) et notes d'incident.

Trame fidèle au cahier des charges, mais dans un format positionnel réel :

    HORODATAGE CAMION LOT LAT LON VITESSE EVENEMENT POIDS NOTES

Ce générateur illustre la variété des formats demandée par le projet (après SQL,
JSON par jour et JSON mensuel, voici le log texte). Les pings d'un trajet sont
répartis sur une même route, prêts à être reconstruits en trajets par l'ETL.

Exemples :
    python generate/transport.py --scale 0.01     # échantillon (dev)
    python generate/transport.py --scale 1.0      # ~600 000 pings
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import math
import os

try:
    from .common import (
        PORTS,
        REGIONS,
        Rng,
        TRANSPORT_DIR,
        date_campagne,
        ensure_dir,
        load_config,
        load_referentiels,
    )
except ImportError:
    from common import (
        PORTS,
        REGIONS,
        Rng,
        TRANSPORT_DIR,
        date_campagne,
        ensure_dir,
        load_config,
        load_referentiels,
    )

CAMIONS_FULL = 120
LOTS_FULL = 15_000
CAMPAGNES = 4

EVENEMENTS = [("ARRET", 0.62), ("FUMIGATION", 0.03), ("ARRIVEE", 0.05)]
NOTES = [
    "circulation normale",
    "ralenti à l'entrée de la ville",
    "pause chauffeur",
    "contrôle routier",
    "pluie forte, vitesse réduite",
    "attente au péage",
    "incident mineur, pneu réparé",
    "aucune anomalie",
]


def _camions(rng: Rng, n: int) -> list[str]:
    return [f"CAM-{rng.randint(1, 999):03d}" for _ in range(n)]


def _route(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    lat = a[0] + (b[0] - a[0]) * t
    lon = a[1] + (b[1] - a[1]) * t
    # léger serpentement pour un tracé naturel
    lat += 0.02 * math.sin(t * 12.0)
    lon += 0.02 * math.cos(t * 12.0)
    return round(lat, 6), round(lon, 6)


def generer(scale: float, seed: int, snapshot: str, out_dir=None):
    from pathlib import Path
    out_dir = Path(out_dir) if out_dir else TRANSPORT_DIR
    cfg = load_config(scale=scale, seed=seed, snapshot=snapshot)
    rng = Rng(cfg.seed)
    refs = load_referentiels(cfg.snapshot)

    n_camions = max(5, cfg.count(CAMIONS_FULL, minimum=5))
    n_lots = max(50, cfg.count(LOTS_FULL, minimum=50))
    camions = _camions(rng, n_camions)

    parcelles = refs["parcelles"]

    ensure_dir(out_dir)
    for ancien in glob.glob(str(out_dir / "trajet_*.log")):
        os.remove(ancien)  # rejouabilité

    index = []
    total_pings = 0
    for i in range(1, n_lots + 1):
        park = rng.choice(parcelles)
        region = park["properties"]["region"]
        origine = (REGIONS[region]["lat"], REGIONS[region]["lon"])
        port_nom = rng.weighted([("Douala", 0.7), ("Kribi", 0.3)])
        port = (PORTS[port_nom]["lat"], PORTS[port_nom]["lon"])

        camion = rng.choice(camions)
        poids = round(rng.uniform(8000, 32000), 2)
        # premier lot de la 1re campagne jusqu'à la 4e
        annee_debut = 2022 + rng.randint(0, CAMPAGNES - 1)
        depart = dt.datetime(annee_debut, rng.randint(10, 12), rng.randint(1, 28),
                             rng.randint(5, 9), rng.randint(0, 59))
        propagation = rng.randint(3, 9)  # jours de trajet

        lot_id = f"LOT-{(i * 3) % n_lots + 1:07d}"
        note_depart = rng.choice(NOTES)
        lignes = []
        latitude, longitude = origine
        base_ts = depart

        # DEPART
        lignes.append(
            (base_ts, camion, lot_id, latitude, longitude, 0, "DEPART", poids, note_depart)
        )
        # pings intermédiaires (route + arrêts)
        frac = rng.randint(22, 55)
        for k in range(1, frac + 1):
            t = k / (frac + 1)
            lat, lon = _route(origine, port, t)
            ts = depart + dt.timedelta(hours=t * 24 * propagation)
            ev, vitesse, poids_ping = "EN_ROUTE", rng.randint(20, 70), ""
            if rng.random() < 0.06:
                ev = rng.weighted(EVENEMENTS)
                vitesse = 0
                poids_ping = ""
            note = ""
            if ev in ("ARRET", "FUMIGATION") or rng.random() < 0.10:
                note = rng.choice(NOTES)
            if ev == "FUMIGATION":
                poids_ping = poids
            lignes.append((ts, camion, lot_id, lat, lon, vitesse, ev, poids_ping, note))
        # ARRIVEE_PORT
        arrivee = depart + dt.timedelta(days=propagation, hours=rng.randint(0, 6))
        lignes.append((arrivee, camion, lot_id, port[0], port[1], 0, "ARRIVEE_PORT", poids,
                       rng.choice(NOTES)))

        path = out_dir / f"trajet_{i:05d}.log"
        with path.open("w", encoding="utf-8") as fh:
            for ts, cam, lot, lat, lon, vit, ev, p, note in lignes:
                fh.write(
                    f"{ts.strftime('%Y-%m-%dT%H:%M:%S')} {cam} {lot} "
                    f"{lat:.6f} {lon:.6f} {vit} {ev} {p} {note}\n"
                )
        total_pings += len(lignes)
        index.append(
            {
                "trajet": f"trajet_{i:05d}.log",
                "camion_id": camion,
                "lot_id": lot_id,
                "port": port_nom,
                "depart": depart.strftime("%Y-%m-%dT%H:%M:%S"),
                "arrivee": arrivee.strftime("%Y-%m-%dT%H:%M:%S"),
                "nb_pings": len(lignes),
                "poids_kg": poids,
            }
        )

    (out_dir / "_index.json").write_text(
        json.dumps({"snapshot": cfg.snapshot, "scale": cfg.scale, "seed": cfg.seed,
                    "trajets": len(index), "pings": total_pings, "trajets_detail": index},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return total_pings, len(index)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Génère les logs GPS de transport (logs texte).")
    parser.add_argument("--scale", type=float, default=None, help="0.01 (dev) .. 1.0 (complet)")
    parser.add_argument("--seed", type=int, default=None, help="graine aléatoire")
    parser.add_argument("--snapshot", default=None, help="millésime des référentiels")
    parser.add_argument("--out-dir", default=None, help="répertoire de sortie")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pings, trajets = generer(args.scale, args.seed, args.snapshot, args.out_dir)
    print(f"Trajets générés : {trajets}")
    print(f"Pings (lignes)  : {pings} dans data/inbox/transport")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())