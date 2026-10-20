"""Générateur des contrats d'achat au format XML (source XML) + schéma XSD.

Un fichier XML par contrat dans data/inbox/contrats/, plus un schéma
contrat.xsd servant à la validation, et un index _index.json.

Ce générateur illustre la source XML du cahier des charges : l'ETL devra parser
du XML et en extraire clauses, dates et volumes (base du NLP2 « extraction des
clauses »). Quelques contrats sont marqués ANNULE (balise <statut>) et certains
portent un avenant, pour alimenter les scénarios de modification.

Exemples :
    python generate/contrats.py --scale 0.01
    python generate/contrats.py --scale 1.0
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
from xml.dom import minidom
from xml.etree import ElementTree as ET

try:
    from .common import (
        CONTRATS_DIR,
        PORTS,
        PRIX_REFC,
        Rng,
        date_campagne,
        ensure_dir,
        load_config,
        load_referentiels,
    )
except ImportError:
    from common import (
        CONTRATS_DIR,
        PORTS,
        PRIX_REFC,
        Rng,
        date_campagne,
        ensure_dir,
        load_config,
        load_referentiels,
    )

CONTRATS_FULL = 600

ACHETEURS = [
    ("Barry Callebaut", "Suisse"), ("Cargill", "États-Unis"),
    ("Olam International", "Singapour"), ("Touton", "France"),
    ("ECOM Agroindustrial", "Suisse"), ("Sucden", "France"),
    ("ETG / Export Trading Group", "Kenya"), ("Neumann Kaffee Gruppe", "Allemagne"),
    ("Intercontinental Coffee Trading", "États-Unis"), ("Sucafina", "Suisse"),
]
INCOTERMS = ["FOB", "CIF", "CFR", "EXW"]
CLAUSES = [
    "Le vendeur garantit un taux d'humidite inferieur a 8.5%.",
    "Le controleur independant sera designe d'un commun accord avant embarquement.",
    "Le paiement est execute sous 30 jours apres presentation des documents.",
    "Toute litige sera regi par les regles d'arbitrage de la Chambre de Commerce de Douala.",
    "Le poids net final est celui du certificat de pesage a l'embarquement.",
    "Le lot doit etre exempt d'insectes vivants et de corps etrangers.",
    "La qualite sera verifiee selon la methode de coupe ISO 1114.",
    "Le vendeur fournira un certificat d'origine et un certificat phytosanitaire.",
    "En cas de non-conformite, l'acheteur peut refuser le lot sans indemnite.",
    "Le fret maritime est a la charge de l'acheteur (incoterm FOB).",
]

XSD = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="contrat">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="contratId" type="xs:string"/>
        <xs:element name="acheteur" type="xs:string"/>
        <xs:element name="pays" type="xs:string"/>
        <xs:element name="produit" type="xs:string"/>
        <xs:element name="volumeTonnes" type="xs:decimal"/>
        <xs:element name="prixFcfaKg" type="xs:decimal"/>
        <xs:element name="dates">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="contrat" type="xs:date"/>
              <xs:element name="debut" type="xs:date"/>
              <xs:element name="fin" type="xs:date"/>
            </xs:sequence>
          </xs:complexType>
        </xs:element>
        <xs:element name="incoterm" type="xs:string"/>
        <xs:element name="ports">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="chargement" type="xs:string"/>
              <xs:element name="decharge" type="xs:string"/>
            </xs:sequence>
          </xs:complexType>
        </xs:element>
        <xs:element name="statut" type="xs:string"/>
        <xs:element name="avenant" type="xs:integer"/>
        <xs:element name="clauses" type="xs:string"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""


def _xml(record: dict) -> str:
    root = ET.Element("contrat")
    ET.SubElement(root, "contratId").text = record["contrat_id"]
    ET.SubElement(root, "acheteur").text = record["acheteur"]
    ET.SubElement(root, "pays").text = record["pays"]
    ET.SubElement(root, "produit").text = record["produit"]
    ET.SubElement(root, "volumeTonnes").text = f"{record['volume_t']:.3f}"
    ET.SubElement(root, "prixFcfaKg").text = f"{record['prix_fcfa_kg']:.2f}"
    dates = ET.SubElement(root, "dates")
    ET.SubElement(dates, "contrat").text = record["date_contrat"]
    ET.SubElement(dates, "debut").text = record["date_debut"]
    ET.SubElement(dates, "fin").text = record["date_fin"]
    ET.SubElement(root, "incoterm").text = record["incoterm"]
    ports = ET.SubElement(root, "ports")
    ET.SubElement(ports, "chargement").text = record["port_chargement"]
    ET.SubElement(ports, "decharge").text = record["port_decharge"]
    ET.SubElement(root, "statut").text = record["statut"]
    ET.SubElement(root, "avenant").text = str(record["avenant"])
    ET.SubElement(root, "clauses").text = record["clauses"]
    brut = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(brut).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def generer(scale: float, seed: int, snapshot: str, out_dir=None):
    from pathlib import Path
    out_dir = Path(out_dir) if out_dir else CONTRATS_DIR
    cfg = load_config(scale=scale, seed=seed, snapshot=snapshot)
    rng = Rng(cfg.seed)
    n = cfg.count(CONTRATS_FULL, minimum=30)

    ensure_dir(out_dir)
    for ancien in glob.glob(str(out_dir / "contrat_*.xml")):
        os.remove(ancien)
    (out_dir / "contrat.xsd").write_text(XSD, encoding="utf-8")

    index = []
    for i in range(1, n + 1):
        acheteur, pays = rng.choice(ACHETEURS)
        produit = rng.weighted([("CACAO", 0.65), ("CAFE", 0.35)])
        date_contrat = date_campagne(produit.lower(), rng)
        volume = round(rng.uniform(50, 3000), 3)
        prix = round(PRIX_REFC[produit] * rng.uniform(0.9, 1.15), 2)
        statut = rng.weighted([("ACTIF", 0.85), ("SUSPENDU", 0.08), ("ANNULE", 0.07)])
        avenant = 1 if rng.random() < 0.12 else 0
        record = {
            "contrat_id": f"CTR-{i:05d}",
            "acheteur": acheteur,
            "pays": pays,
            "produit": produit,
            "volume_t": volume,
            "prix_fcfa_kg": prix,
            "date_contrat": date_contrat.isoformat(),
            "date_debut": date_contrat.isoformat(),
            "date_fin": (date_contrat + dt.timedelta(days=365)).isoformat(),
            "incoterm": rng.choice(INCOTERMS),
            "port_chargement": rng.weighted([("Douala", 0.7), ("Kribi", 0.3)]),
            "port_decharge": rng.choice(["Rotterdam", "Anvers", "Hambourg", "Valence", "New York"]),
            "statut": statut,
            "avenant": avenant,
            "clauses": " ".join(rng.sample(CLAUSES, rng.randint(2, 4))),
        }
        (out_dir / f"contrat_{i:05d}.xml").write_text(_xml(record), encoding="utf-8")
        index.append({"fichier": f"contrat_{i:05d}.xml", **record})

    (out_dir / "_index.json").write_text(
        json.dumps({"snapshot": cfg.snapshot, "scale": cfg.scale, "seed": cfg.seed,
                    "contrats": n, "detail": index}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return n


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Génère les contrats d'achat (XML + XSD).")
    parser.add_argument("--scale", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--out-dir", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    n = generer(args.scale, args.seed, args.snapshot, args.out_dir)
    print(f"Contrats XML générés : {n} dans data/inbox/contrats (+ contrat.xsd)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())