"""Utilitaires partagés par les générateurs de données du Projet 9.

Aucune dépendance externe (bibliothèque standard uniquement) : la génération est
donc reproductible, rapide à installer et testable partout.

Reproductibilité :
  - une graine fixe (RANDOM_SEED, défaut 42) rend toute exécution identique ;
  - un facteur d'échelle (SCALE, défaut 0.01 en développement, 1.0 en complet)
    réduit les volumes pour le développement sur portable.

Exemple :
    from common import load_config
    cfg = load_config()
    print(cfg.scale, cfg.seed)
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INBOX_DIR = DATA_DIR / "inbox"
REFERENCE_DIR = DATA_DIR / "reference"

# Répertoire de dépôt des référentiels (coopératives, producteurs, parcelles).
REFERENTIELS_DIR = INBOX_DIR / "referentiels"

# Répertoire de dépôt des contrôles qualité (un JSON par mois).
QUALITE_DIR = INBOX_DIR / "qualite"

# Motif des fichiers JSON de contrôles qualité.
QUALITE_GLOB = "controles_qualite_*.json"

# Répertoire de dépôt des paiements (un JSON par jour).
PAIEMENTS_DIR = INBOX_DIR / "paiements"

# Motif des fichiers JSON de paiements.
PAIEMENTS_GLOB = "paiements_*.json"

# Prix de référence indicatifs des producteurs (FCFA/kg) par produit.
PRIX_REFC = {"CACAO": 3000.0, "CAFE": 2500.0}

# Répertoire de dépôt des logs GPS de transport (un fichier texte par lot).
TRANSPORT_DIR = INBOX_DIR / "transport"

# Répertoires des sources XML (contrats) et CSV (trafic portuaire).
CONTRATS_DIR = INBOX_DIR / "contrats"
TRAFIC_DIR = INBOX_DIR / "trafic"

# Dossiers des sources publiques : cache brut et repli hors-ligne.
PUBLIC_DIR = INBOX_DIR / "public"
CACHE_DIR = DATA_DIR / "cache"

# Stations météo suivies (lieu, lat, lon) pour NASA POWER / Open-Meteo.
STATIONS = [
    ("Yaoundé-Nsimalen", 3.72, 11.55),
    ("Douala", 4.05, 9.70),
    ("Ebolowa", 2.90, 11.15),
    ("Bertoua", 4.58, 13.68),
    ("Bafoussam", 5.48, 10.42),
    ("Bamenda", 5.96, 10.15),
    ("Kribi", 2.94, 9.91),
]

# Paires de change suivies (base EUR via la BCE, USD/XAF dérivé).
PAIRES_DEVISE = ["USD", "GBP", "XAF"]

# Ports d'export (Cameroun) : point de départ (hinterland) → port.
PORTS = {
    "Douala": {"lat": 4.05, "lon": 9.70, "terminal": "Terminal à conteneurs Douala-Bonabéri"},
    "Kribi":  {"lat": 2.94, "lon": 9.91, "terminal": "Port en eau profonde de Kribi"},
}


# -----------------------------------------------------------------------------
# Configuration (variables d'environnement, fichier .env facultatif)
# -----------------------------------------------------------------------------
def load_env(path: Path | None = None) -> None:
    """Charge un fichier .env dans os.environ sans écraser l'existant."""
    env_path = path or (PROJECT_ROOT / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Config:
    scale: float
    seed: int
    snapshot: str  # date ISO du millésime (AAAA-MM-JJ)

    def count(self, full: int, minimum: int = 0) -> int:
        """Nombre d'entités à générer à l'échelle courante (jamais zéro)."""
        return max(minimum, round(full * self.scale))


def load_config(
    scale: float | None = None,
    seed: int | None = None,
    snapshot: str | None = None,
) -> Config:
    load_env()
    if scale is None:
        scale = float(os.environ.get("SCALE", "1.0"))
    if seed is None:
        seed = int(os.environ.get("RANDOM_SEED", "42"))
    if snapshot is None:
        snapshot = date.today().isoformat()
    return Config(scale=scale, seed=seed, snapshot=snapshot)


# -----------------------------------------------------------------------------
# Géographie de référence — Cameroun (bassins cacao & café)
# lat/lon = centroïde ; spread = dispersion approximative en degrés.
# -----------------------------------------------------------------------------
REGIONS: dict[str, dict] = {
    "Centre": {
        "lat": 3.87, "lon": 11.52, "spread": 0.55,
        "departements": ["Méfou-et-Afamba", "Lekié", "Nyong-et-So'o", "Haute-Sanaga"],
        "villes": ["Yaoundé", "Mbalmayo", "Obala", "Nanga Eboko", "Bafia"],
        "cultures": {"cacao": 1.0},
    },
    "Sud": {
        "lat": 2.90, "lon": 11.15, "spread": 0.60,
        "departements": ["Mvila", "Océan", "Dja-et-Lobo", "Vallée-du-Ntem"],
        "villes": ["Ebolowa", "Kribi", "Sangmélima", "Ambam", "Mvangan"],
        "cultures": {"cacao": 0.85, "cafe": 0.15},
    },
    "Sud-Ouest": {
        "lat": 4.15, "lon": 9.24, "spread": 0.45,
        "departements": ["Fako", "Memé", "Ndian", "Kupe-Manengouba"],
        "villes": ["Buea", "Kumba", "Mamfe", "Limbe", "Mundemba"],
        "cultures": {"cacao": 1.0},
    },
    "Est": {
        "lat": 4.58, "lon": 13.68, "spread": 0.90,
        "departements": ["Lom-et-Djérem", "Kadey", "Boumba-et-Ngoko", "Haut-Nyong"],
        "villes": ["Bertoua", "Batouri", "Yokadouma", "Abong-Mbang", "Doumé"],
        "cultures": {"cacao": 0.9, "cafe": 0.1},
    },
    "Littoral": {
        "lat": 4.05, "lon": 9.70, "spread": 0.40,
        "departements": ["Wouri", "Moungo", "Nkam", "Sanaga-Maritime"],
        "villes": ["Douala", "Nkongsamba", "Edéa", "Mbanga", "Dizangué"],
        "cultures": {"cafe": 0.7, "cacao": 0.3},
    },
    "Ouest": {
        "lat": 5.48, "lon": 10.42, "spread": 0.35,
        "departements": ["Mifi", "Menoua", "Bamboutos", "Koung-Khi"],
        "villes": ["Bafoussam", "Dschang", "Mbouda", "Bafang", "Bandjoun"],
        "cultures": {"cafe": 1.0},
    },
    "Nord-Ouest": {
        "lat": 5.96, "lon": 10.15, "spread": 0.45,
        "departements": ["Mezam", "Bui", "Donga-Mantung", "Boyo"],
        "villes": ["Bamenda", "Kumbo", "Wum", "Nkambe", "Fundong"],
        "cultures": {"cafe": 1.0},
    },
}

# Variétés par culture.
VARIETES = {
    "cacao": ["Forastero", "Trinitario", "Criollo"],
    "cafe": ["Arabica", "Robusta"],
}

# Certifications (Aucune majoritaire).
CERTIFICATIONS = [
    ("Aucune", 0.62),
    ("Rainforest Alliance", 0.13),
    ("UTZ", 0.09),
    ("Fairtrade", 0.08),
    ("Bio", 0.05),
    ("Fairtrade + Bio", 0.03),
]

STATUTS_PRODUCTEUR = [("ACTIF", 0.92), ("INACTIF", 0.06), ("RADIE", 0.02)]
STATUTS_COOPERATIVE = [("ACTIVE", 0.85), ("SUSPENDUE", 0.10), ("DISSOUTE", 0.05)]

NOMS = [
    "Atangana", "Ateba", "Abena", "Bella", "Bilong", "Biya", "Ebode", "Efoua",
    "Ekani", "Ekwalla", "Essomba", "Etoa", "Eyenga", "Fouda", "Kamdem", "Kenne",
    "Kouam", "Makon", "Manga", "Mballa", "Mbarga", "Mbouda", "Mefire", "Mendo",
    "Mouelle", "Mvondo", "Nana", "Ndam", "Ndongo", "Ndzana", "Ngando", "Ngo",
    "Ngono", "Nguema", "Nkodo", "Nkolo", "Nkoulou", "Nomo", "Ntamack", "Nyobe",
    "Obiang", "Olinga", "Onana", "Owona", "Sadi", "Tchoua", "Tchoumi", "Tiotsop",
    "Wandji", "Yemda", "Zamcho", "Zebaze", "Zoua",
]

PRENOMS_H = [
    "Jean", "Paul", "Pierre", "Emmanuel", "Marc", "André", "Blaise", "Célestin",
    "Daniel", "Étienne", "François", "Gabriel", "Hervé", "Isaac", "Jacques",
    "Joseph", "Justin", "Landry", "Luc", "Mathieu", "Michel", "Marcel",
    "Norbert", "Olivier", "Pascal", "Raphaël", "Robert", "Samuel", "Serge",
    "Simon", "Thomas", "Vincent", "Yannick", "Bertrand", "Clément", "Désiré",
    "Ernest", "Félix", "Ghislain", "Honoré",
]

PRENOMS_F = [
    "Marie", "Joséphine", "Alice", "Béatrice", "Carine", "Chantal", "Christine",
    "Cécile", "Delphine", "Édith", "Émilienne", "Estelle", "Florence",
    "Georgette", "Hélène", "Hortense", "Irène", "Jacqueline", "Jeanne",
    "Julienne", "Laure", "Madeleine", "Marguerite", "Marthe", "Monique",
    "Nadine", "Nicole", "Odile", "Pauline", "Renée", "Rosine", "Sylvie",
    "Thérèse", "Valentine", "Véronique", "Yvonne", "Adèle", "Bernadette",
    "Colette", "Diane",
]


# -----------------------------------------------------------------------------
# Générateur pseudo-aléatoire déterministe
# -----------------------------------------------------------------------------
class Rng:
    """Enveloppe de random.Random avec des tirages pondérés pratiques."""

    def __init__(self, seed: int) -> None:
        self._r = random.Random(seed)

    def __getattr__(self, name):  # délègue randint, choice, uniform, ...
        return getattr(self._r, name)

    def weighted(self, options: list[tuple], default=None):
        """Tirage pondéré sur une liste [(valeur, poids), ...]."""
        values = [v for v, _ in options]
        weights = [w for _, w in options]
        return self._r.choices(values, weights=weights, k=1)[0]

    def plate(self, options: list[tuple]) -> str:
        """Nom complet lisible : 'Prénom Nom' (sexe optionnel non renvoyé ici)."""
        return str(self.weighted(options))


def person(rng: Rng) -> tuple[str, str, str]:
    """Renvoie (prenom, nom, sexe) de façon déterministe."""
    sexe = rng.weighted([("M", 0.70), ("F", 0.30)])
    prenom = rng.choice(PRENOMS_H if sexe == "M" else PRENOMS_F)
    nom = rng.choice(NOMS)
    return prenom, nom, sexe


# -----------------------------------------------------------------------------
# Aides géographiques
# -----------------------------------------------------------------------------
def jitter_point(region: str, rng: Rng) -> tuple[float, float]:
    """Point (lat, lon) autour du centroïde d'une région."""
    info = REGIONS[region]
    lat = info["lat"] + rng.uniform(-info["spread"], info["spread"])
    lon = info["lon"] + rng.uniform(-info["spread"], info["spread"])
    return round(lat, 6), round(lon, 6)


def polygon_around(lat: float, lon: float, surface_ha: float, rng: Rng) -> list[list[float]]:
    """Polygone GeoJSON approximatif (anneau fermé) d'une parcelle.

    La surface (ha) est convertie en côté de carré en degrés, puis légèrement
    déformée pour un rendu naturel.
    """
    area_km2 = max(surface_ha, 0.1) / 100.0
    side_km = math.sqrt(area_km2)
    side_deg = side_km / 111.0
    # 4 sommets + fermeture ; petite rotation pour éviter l'effet « grille ».
    angle = rng.uniform(0, math.pi / 2)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    half = side_deg / 2.0
    corners = [(-half, -half), (half, -half), (half, half), (-half, half)]
    ring = []
    for x, y in corners + [corners[0]]:
        rx = x * cos_a - y * sin_a
        ry = x * sin_a + y * cos_a
        ring.append([round(lon + rx, 6), round(lat + ry, 6)])
    return ring


# -----------------------------------------------------------------------------
# Entrées / sorties de fichiers
# -----------------------------------------------------------------------------
def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_geojson(path: Path, features: list[dict]) -> None:
    """FeatureCollection déterministe (clés triées) et UTF-8 explicite."""
    ensure_dir(path.parent)
    collection = {"type": "FeatureCollection", "features": features}
    path.write_text(
        json.dumps(collection, ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8",
    )


def iso_ts(value: date | str) -> str:
    """Instant UTC ISO à partir d'une date (AAAA-MM-JJ) ou d'un datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dates_between(start: date, end: date, rng: Rng) -> date:
    """Date aléatoire uniforme dans [start, end]."""
    span = (end - start).days
    if span <= 0:
        return start
    return start + timedelta(days=rng.randint(0, span))


# -----------------------------------------------------------------------------
# Saisonnalité de la collecte (campagne octobre → septembre)
# Poids mensuel d'activité par culture (mois civils 1..12).
# -----------------------------------------------------------------------------
SAISONNALITE = {
    "cacao": {1: 9, 2: 7, 3: 5, 4: 4, 5: 6, 6: 9, 7: 13, 8: 11, 9: 10, 10: 14, 11: 17, 12: 13},
    "cafe": {1: 12, 2: 9, 3: 7, 4: 5, 5: 4, 6: 3, 7: 3, 8: 4, 9: 6, 10: 15, 11: 17, 12: 14},
}

DEBUT_CAMPAGNE = date(2022, 10, 1)
FIN_CAMPAGNE = date(2026, 9, 30)


def date_campagne(
    produit: str,
    rng: Rng,
    debut: date = DEBUT_CAMPAGNE,
    fin: date = FIN_CAMPAGNE,
) -> date:
    """Date tirée selon la saisonnalité d'un produit, dans une campagne oct→sep."""
    poids = SAISONNALITE[produit]
    mois = list(poids.keys())
    m = rng.weighted([(mois[i], poids[mois[i]]) for i in range(len(mois))])
    # La campagne démarre en octobre de l'année tirée.
    annee_debut = rng.randint(debut.year, fin.year - 1)
    if m >= 10:  # octobre, novembre, décembre -> 1er, 2e, 3e mois de la campagne
        base = date(annee_debut, m, 1)
    else:        # janvier..septembre -> 4e..12e mois (année suivante)
        base = date(annee_debut + 1, m, 1)
    dernier = (base.replace(month=base.month % 12 + 1, day=1) - timedelta(days=1)).day
    jour = rng.randint(1, dernier)
    d = date(base.year, base.month, jour)
    fin_camp = date(annee_debut + 1, 9, 30)
    d = min(d, fin_camp)
    return max(d, debut)


# -----------------------------------------------------------------------------
# Chargement des référentiels générés (coopératives, producteurs, parcelles)
# -----------------------------------------------------------------------------
def load_referentiels(snapshot: str, directory=REFERENTIELS_DIR) -> dict:
    """Lit un instantané des référentiels (CSV coopératives + GeoJSON parcelles).

    Renvoie :
      {
        "snapshot": ...,
        "cooperatives": {cooperative_id -> dict},
        "parcelles": [feature dict, ...],          # triées par parcelle_id
        "producteurs": {producteur_id -> dict},    # avec la liste "parcelles"
      }
    """
    coop_path = directory / f"cooperatives_{snapshot}.csv"
    geo_path = directory / f"producteurs_parcelles_{snapshot}.geojson"
    if not coop_path.exists() or not geo_path.exists():
        raise FileNotFoundError(
            f"Référentiels absents pour l'instantané {snapshot}. "
            f"Lancez : python generate/referentiels.py --snapshot {snapshot}"
        )

    cooperatives: dict[str, dict] = {}
    with coop_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cooperatives[row["cooperative_id"]] = row

    geo = json.loads(geo_path.read_text(encoding="utf-8"))
    parcelles = list(geo["features"])

    producteurs: dict[str, dict] = {}
    for feature in sorted(parcelles, key=lambda f: f["id"]):
        props = dict(feature["properties"])
        pid = props["producteur_id"]
        prod = producteurs.setdefault(
            pid, {"producteur_id": pid, "parcelles": [], **{k: props[k] for k in props if k != "parcelle_id"}}
        )
        prod["parcelles"].append(
            {
                "parcelle_id": props["parcelle_id"],
                "culture": props["culture"],
                "surface_ha": float(props["surface_ha"]),
                "variete": props.get("variete"),
                "annee_plantation": props.get("annee_plantation"),
            }
        )

    return {
        "snapshot": snapshot,
        "cooperatives": cooperatives,
        "parcelles": parcelles,
        "producteurs": producteurs,
    }
