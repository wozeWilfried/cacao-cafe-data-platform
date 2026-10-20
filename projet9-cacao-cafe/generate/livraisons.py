"""Générateur des livraisons de cacao/café (insertion dans coop.livraison).

Base plein : ~304 200 livraisons réparties sur 4 campagnes (octobre → septembre)
de 2022/23 à 2025/26, avec saisonnalité par culture (cacao / café) et des
producteurs référentiels issus du GeoJSON généré par referentiels.py.

Reproductible : graine fixe + échelle => contenu identique. Rejouable : la table
est vidée avant repopulation (idempotence locale).

Exemples :
    python generate/livraisons.py --scale 0.01        # ~3 042 lignes (dev)
    python generate/livraisons.py --scale 1.0         # ~304 200 lignes
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from urllib.parse import urlparse

try:
    from .common import (
        Rng,
        date_campagne,
        load_config,
        load_env,
        load_referentiels,
    )
except ImportError:
    from common import (
        Rng,
        date_campagne,
        load_config,
        load_env,
        load_referentiels,
    )

try:
    import psycopg
except ImportError:
    raise SystemExit(
        "psycopg manquant. Installez-le :  pip install 'psycopg[binary]'"
    )

# Volumétrie cible (run 0 dans le guide : 304 200 livraisons).
LIVRAISONS_FULL = 304_200

SAC_KG = 60.0  # poids nominal d'un sac de 60 kg


def _connect():
    load_env()
    url = os.environ["SRC_URL"]
    u = urlparse(url)
    return url, u


def generer(scale: float, seed: int, snapshot: str, limit: int | None = None):
    cfg = load_config(scale=scale, seed=seed, snapshot=snapshot)
    refs = load_referentiels(cfg.snapshot)
    n = cfg.count(LIVRAISONS_FULL, minimum=500) if limit is None else limit

    producteurs = [p for p in refs["producteurs"].values() if p["statut"] == "ACTIF"]
    if not producteurs:
        raise SystemExit("Aucun producteur ACTIF dans le référentiel.")

    rng = Rng(cfg.seed)

    # Intensité de production par producteur (hétérogénéité réaliste).
    poids = [rng.uniform(0.3, 3.0) for _ in producteurs]
    ids = [p["producteur_id"] for p in producteurs]
    choix = rng.choices(ids, weights=poids, k=n)

    dates: list[tuple[str, str]] = []  # (produit, date)
    for pid in choix:
        prod = refs["producteurs"][pid]
        dates.append((prod["culture"], date_campagne(prod["culture"], rng)))

    # Tri chronologique pour un chargement naturel.
    dates.sort(key=lambda t: t[1])

    url, u = _connect()
    lignes = 0
    with psycopg.connect(
        host=u.hostname, port=u.port, dbname=u.path.lstrip("/"),
        user=u.username, password=u.password,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE coop.livraison")
            with cur.copy(
                "COPY coop.livraison "
                "(producteur_id, cooperative_id, parcelle_id, produit, date_livraison, "
                " poids_brut_kg, poids_net_kg, nb_sacs, updated_at) FROM STDIN"
            ) as copy:
                for pid, (produit, d) in zip(choix, dates):
                    prod = refs["producteurs"][pid]
                    parcelle = rng.choice(prod["parcelles"])
                    sacs = max(1, int(round(abs(rng.gauss(12, 7)))))
                    if sacs > 60:
                        sacs = 60
                    brut = round(sacs * SAC_KG + rng.uniform(-8, 8), 2)
                    tare = rng.uniform(0.02, 0.05)
                    net = round(brut * (1 - tare), 2)
                    heure = rng.randint(6, 19)
                    moment = dt.datetime.combine(d, dt.time(heure, rng.randint(0, 59)))
                    ts = moment.replace(tzinfo=dt.timezone.utc)
                    copy.write_row(
                        [
                            pid,
                            prod["cooperative_id"],
                            parcelle["parcelle_id"],
                            produit.upper(),
                            d,
                            brut,
                            net,
                            sacs,
                            ts,
                        ]
                    )
                    lignes += 1
    return cfg, url, n, lignes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Génère les livraisons dans coop.livraison.")
    parser.add_argument("--scale", type=float, default=None, help="0.01 (dev) .. 1.0 (complet)")
    parser.add_argument("--seed", type=int, default=None, help="graine aléatoire (défaut 42)")
    parser.add_argument("--snapshot", default=None, help="millésime des référentiels (AAAA-MM-JJ)")
    parser.add_argument("--limit", type=int, default=None, help="nombre exact de livraisons")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg, url, n, lignes = generer(args.scale, args.seed, args.snapshot, args.limit)
    print(f"Livraisons insérées : {lignes} / prévues {n}")
    print(f"Base cible          : {url}")
    print(f"Référentiel         : {cfg.snapshot} (échelle {cfg.scale}, graine {cfg.seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())