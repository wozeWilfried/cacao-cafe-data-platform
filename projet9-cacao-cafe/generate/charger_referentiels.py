"""Charge les fichiers générés (CSV, GeoJSON, JSON, logs) dans les tables de
consultation de la base source : coop.cooperative, coop.producteur,
coop.parcelle, coop.lot_qualite, coop.paiement, coop.transport_ping.

La source officielle reste les fichiers de data/inbox (lue par l'ETL) ; ce
script ne sert qu'à pouvoir voir et contrôler les données en SQL.

Exemples :
    python generate/charger_referentiels.py --snapshot 2022-10-01
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from urllib.parse import urlparse

from psycopg.types.json import Json

try:
    from .common import (
        CONTRATS_DIR,
        PAIEMENTS_DIR,
        PAIEMENTS_GLOB,
        QUALITE_DIR,
        QUALITE_GLOB,
        PUBLIC_DIR,
        TRAFIC_DIR,
        TRANSPORT_DIR,
        load_config,
        load_env,
        load_referentiels,
    )
except ImportError:
    from common import (
        CONTRATS_DIR,
        PAIEMENTS_DIR,
        PAIEMENTS_GLOB,
        QUALITE_DIR,
        QUALITE_GLOB,
        PUBLIC_DIR,
        TRAFIC_DIR,
        TRANSPORT_DIR,
        load_config,
        load_env,
        load_referentiels,
    )

try:
    import psycopg
except ImportError:
    raise SystemExit("psycopg manquant. Installez-le :  pip install 'psycopg[binary]'")


def _connexion():
    load_env()
    url = urlparse(os.environ["SRC_URL"])
    return psycopg.connect(
        host=url.hostname, port=url.port, dbname=url.path.lstrip("/"),
        user=url.username, password=url.password,
    )


def _copier(conn, table: str, colonnes: list[str], lignes: list[tuple]) -> int:
    """Insertion massive et rejouable (table vidée puis COPY)."""
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE coop.{table}")
        with cur.copy(f"COPY coop.{table} ({','.join(colonnes)}) FROM STDIN") as cp:
            for ligne in lignes:
                cp.write_row(ligne)
        cur.execute(f"SELECT count(*) FROM coop.{table}")
        return cur.fetchone()[0]


def _charger_referentiels(conn, snapshot: str) -> None:
    refs = load_referentiels(snapshot)

    cooperatives = sorted(refs["cooperatives"].values(), key=lambda c: c["cooperative_id"])
    coop_lignes = [
        (
            c["cooperative_id"], c["nom"], c["region"], c["departement"], c["ville"],
            c["latitude"], c["longitude"], c["capacite_stockage_t"], c["responsable"],
            c["certification"], c["statut"], c["date_creation"], c["nb_adherents"],
            c["maj_le"],
        )
        for c in cooperatives
    ]
    n_coop = _copier(conn, "cooperative",
        ["cooperative_id", "nom", "region", "departement", "ville", "latitude",
         "longitude", "capacite_stockage_t", "responsable", "certification",
         "statut", "date_creation", "nb_adherents", "maj_le"], coop_lignes)

    producteurs = sorted(refs["producteurs"].values(), key=lambda p: p["producteur_id"])
    prod_lignes = [
        (
            p["producteur_id"], p["cooperative_id"], p["nom"], p["sexe"],
            int(p["annee_naissance"]) if p["annee_naissance"] else None,
            p["culture"], p["region"], p["certification"], p["statut"], p["maj_le"],
        )
        for p in producteurs
    ]
    n_prod = _copier(conn, "producteur",
        ["producteur_id", "cooperative_id", "nom", "sexe", "annee_naissance",
         "culture", "region", "certification", "statut", "maj_le"], prod_lignes)

    parc_lignes = []
    for f in refs["parcelles"]:
        pr = f["properties"]
        parc_lignes.append(
            (
                pr["parcelle_id"], pr["producteur_id"], pr["cooperative_id"],
                pr["culture"], pr.get("variete"), pr["surface_ha"],
                pr.get("annee_plantation"), pr["certification"], pr["region"],
                pr["statut"], pr["maj_le"], Json(f["geometry"]),
            )
        )
    n_parc = _copier(conn, "parcelle",
        ["parcelle_id", "producteur_id", "cooperative_id", "culture", "variete",
         "surface_ha", "annee_plantation", "certification", "region", "statut",
         "maj_le", "geometry"], parc_lignes)

    print(f"  coopératives   : {n_coop:>6}")
    print(f"  producteurs    : {n_prod:>6}")
    print(f"  parcelles      : {n_parc:>6}")


def _charger_qualite(conn) -> int:
    fichiers = sorted(glob.glob(str(QUALITE_DIR / QUALITE_GLOB)))
    lignes = []
    for path in fichiers:
        with open(path, encoding="utf-8") as fh:
            for r in json.load(fh):
                lignes.append(
                    (
                        r["lot_id"], r["cooperative_id"], r["date_reception"],
                        r["date_analyse"], r["humidite_pct"], r["nb_grains_comptes"],
                        r["grains_defectueux_pct"], r["grade"], r["decision"],
                        r["defaut_principal"], r["observation"],
                    )
                )
    n = _copier(conn, "lot_qualite",
        ["lot_id", "cooperative_id", "date_reception", "date_analyse", "humidite_pct",
         "nb_grains_comptes", "grains_defectueux_pct", "grade", "decision",
         "defaut_principal", "observation"], lignes)
    print(f"  lots qualité   : {n:>6}  ({len(fichiers)} fichiers JSON)")
    return n


def _charger_paiements(conn) -> int:
    fichiers = sorted(glob.glob(str(PAIEMENTS_DIR / PAIEMENTS_GLOB)))
    lignes = []
    for path in fichiers:
        with open(path, encoding="utf-8") as fh:
            for r in json.load(fh):
                lignes.append(
                    (
                        r["paiement_id"], r["livraison_id"], r["producteur_id"],
                        r["operateur"], r["montant_fcfa"], r["frais_fcfa"],
                        r["statut"], r["horodatage"],
                    )
                )
    n = _copier(conn, "paiement",
        ["paiement_id", "livraison_id", "producteur_id", "operateur", "montant_fcfa",
         "frais_fcfa", "statut", "horodatage"], lignes)
    print(f"  paiements      : {n:>6}  ({len(fichiers)} fichiers JSON)")
    return n


def _charger_transport(conn) -> int:
    fichiers = sorted(glob.glob(str(TRANSPORT_DIR / "trajet_*.log")))
    with conn.cursor() as cur:
        cur.execute("TRUNCATE coop.transport_ping")
        total = 0
        for path in fichiers:
            with open(path, encoding="utf-8") as fh, cur.copy(
                "COPY coop.transport_ping (horodatage, camion_id, lot_id, latitude, "
                "longitude, vitesse_kmh, evenement, poids_kg, notes) FROM STDIN"
            ) as cp:
                for ligne in fh:
                    parts = ligne.split(" ", 8)
                    if len(parts) < 8:
                        continue
                    ts, cam, lot, lat, lon, vit, ev, poids = parts[:8]
                    note = parts[8].strip() if len(parts) > 8 else ""
                    cp.write_row(
                        (
                            ts, cam, lot, float(lat), float(lon),
                            int(vit) if vit else None, ev,
                            float(poids) if poids else None, note,
                        )
                    )
                    total += 1
        cur.execute("SELECT count(*) FROM coop.transport_ping")
        n = cur.fetchone()[0]
    print(f"  pings GPS      : {n:>6}  ({len(fichiers)} trajets)")
    return n


def _charger_contrats(conn) -> int:
    from xml.etree import ElementTree as ET
    fichiers = sorted(glob.glob(str(CONTRATS_DIR / "contrat_*.xml")))
    lignes = []
    for path in fichiers:
        root = ET.parse(path).getroot()

        def txt(tag):
            el = root.find(tag)
            return el.text if el is not None else None

        dates = root.find("dates")
        ports = root.find("ports")
        lignes.append((
            txt("contratId"), txt("acheteur"), txt("pays"), txt("produit"),
            float(txt("volumeTonnes")), float(txt("prixFcfaKg")),
            dates.findtext("contrat"), dates.findtext("debut"), dates.findtext("fin"),
            txt("incoterm"), ports.findtext("chargement"), ports.findtext("decharge"),
            txt("statut"), int(txt("avenant") or 0), txt("clauses"),
        ))
    n = _copier(conn, "contrat",
        ["contrat_id", "acheteur", "pays", "produit", "volume_t", "prix_fcfa_kg",
         "date_contrat", "date_debut", "date_fin", "incoterm", "port_chargement",
         "port_decharge", "statut", "avenant", "clauses"], lignes)
    print(f"  contrats XML   : {n:>6}  ({len(fichiers)} fichiers)")
    return n


def _charger_trafic(conn) -> int:
    import csv as _csv
    fichiers = sorted(glob.glob(str(TRAFIC_DIR / "trafic_portuaire_*.csv")))
    lignes = []
    for path in fichiers:
        with open(path, encoding="utf-8") as fh:
            for r in _csv.DictReader(fh):
                lignes.append((
                    r["escale_id"], r["port"], r["navire"], r["date_arrivee"],
                    r["date_depart"], int(r["conteneurs"]), float(r["tonnage_t"]),
                    r["terminal"], r["statut"],
                ))
    n = _copier(conn, "trafic_port",
        ["escale_id", "port", "navire", "date_arrivee", "date_depart", "conteneurs",
         "tonnage_t", "terminal", "statut"], lignes)
    print(f"  trafic port    : {n:>6}  ({len(fichiers)} fichiers CSV)")
    return n


def _charger_intrants(conn) -> int:
    from openpyxl import load_workbook
    fichiers = sorted(glob.glob(str((PAIEMENTS_DIR.parent / "intrants") / "intrants_*.xlsx")))
    lignes = []
    for path in fichiers:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb["Distributions"]
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue
            lignes.append(tuple(row))
        wb.close()
    n = _copier(conn, "intrant_distribution",
        ["distribution_id", "producteur_id", "cooperative_id", "date_distribution",
         "intrant_id", "quantite", "unite", "cout_fcfa", "campagne"], lignes)
    print(f"  intrants Excel : {n:>6}  ({len(fichiers)} classeurs)")
    return n


def _charger_publiques(conn) -> int:
    import csv as _csv
    total = 0

    def lire(nom):
        p = PUBLIC_DIR / nom
        if not p.exists():
            return []
        with open(p, encoding="utf-8") as fh:
            return list(_csv.DictReader(fh))

    prix = []
    vus = set()
    for r in lire("prix_marches_mondiaux.csv"):
        cle = (r["date"], r["produit"])
        if cle in vus:
            continue
        vus.add(cle)
        prix.append((r["date"], r["produit"], r["unite"], float(r["prix"])))
    total += _copier(conn, "prix_marche", ["date_mois", "produit", "unite", "prix"], prix)

    fao = [(r["pays"], r["produit"], r["element"], int(r["annee"]), r["unite"],
            float(r["valeur"]) if r["valeur"] else None)
           for r in lire("faostat_production.csv")]
    total += _copier(conn, "faostat_production",
        ["pays", "produit", "element", "annee", "unite", "valeur"], fao)

    meteo = [("NASA", r["site"], r["date"], r["T2M"], r["PRECTOTCORR"])
             for r in lire("meteo_nasa.csv")]
    meteo += [("OPEN-METEO", r["site"], r["date"], r["temperature"], r["pluie"])
              for r in lire("meteo_openmeteo.csv")]
    total += _copier(conn, "meteo", ["source", "site", "date_jour", "temperature", "pluie"], meteo)

    change = [(r["date"], r["paire"], float(r["taux"]))
              for r in lire("taux_change.csv")]
    total += _copier(conn, "taux_change", ["date_jour", "paire", "taux"], change)

    print(f"  sources publiques: {total:>6} lignes (prix, faostat, météo, change)")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Charge les fichiers de data/inbox dans les tables de consultation."
    )
    parser.add_argument("--snapshot", default=None, help="millésime des référentiels (AAAA-MM-JJ)")
    args = parser.parse_args()

    cfg = load_config(snapshot=args.snapshot)
    with _connexion() as conn:
        print(f"Chargement des fichiers dans coop.* (référentiel {cfg.snapshot}) :")
        _charger_referentiels(conn, cfg.snapshot)
        _charger_qualite(conn)
        _charger_paiements(conn)
        _charger_transport(conn)
        _charger_contrats(conn)
        _charger_trafic(conn)
        _charger_intrants(conn)
        _charger_publiques(conn)
    print("OK — tout est visible via PostgreSQL (5433 / coop_source).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())