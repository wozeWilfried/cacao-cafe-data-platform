"""Les 10 règles de qualité (cf. guide, section 06).

Chaque fonction reçoit un enregistrement (dict) et retourne None si la ligne
est valide, ou un couple (regle, motif) si elle doit être rejetée. Les règles
sont réutilisées par les étapes de contrôle de chaque source.

Conventions :
  - R01 doublons            : détecté au niveau d'un lot (voir detecter_doublons)
  - R02 non-nullité         : champs obligatoires
  - R03 domaines de valeurs : bornes métier
  - R04 intégrité           : clés étrangères existantes (via callbacks)
  - R05 dates               : parse + normalisation ISO
  - R06 paiement            : montant > 0, statut REUSSI pour comptage
  - R07 cohérence temporelle: fin >= début
  - R08 GPS                 : boîte englobante du Cameroun, vitesse <= 120
  - R09 XSD                 : conformité XML (au niveau fichier)
  - R10 texte vide          : observation/clause -> NON_RENSEIGNE
"""

from __future__ import annotations

from datetime import datetime

# Boîte englobante approximative du Cameroun.
CAMEROUN_BBOX = {"lat_min": 1.6, "lat_max": 13.1, "lon_min": 8.4, "lon_max": 16.2}
VITESSE_MAX_KMH = 120.0
HUMIDITE_ALERTE = 15.0


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(v)[: len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except ValueError:
        return None


# --------------------------------------------------------------------------- R02
def r02_obligatoires(rec: dict, champs: list[str]):
    """Rejette si un champ obligatoire est nul ou vide."""
    for champ in champs:
        if rec.get(champ) in (None, ""):
            return ("R02", f"champ obligatoire vide: {champ}")
    return None


# --------------------------------------------------------------------------- R03
def r03_domaine_poids(rec: dict):
    """poids_net > 0 et poids_net <= poids_brut."""
    net = _to_float(rec.get("poids_net_kg"))
    brut = _to_float(rec.get("poids_brut_kg"))
    if net is None or net <= 0:
        return ("R03", "poids_net_kg <= 0")
    if brut is not None and net > brut:
        return ("R03", "poids_net_kg > poids_brut_kg")
    return None


def r03_domaine_humidite(rec: dict):
    """0 <= humidité <= 100 (alerte si > 15 % : signalée, non rejetée)."""
    h = _to_float(rec.get("humidite_pct"))
    if h is not None and not (0 <= h <= 100):
        return ("R03", f"humidite_pct hors [0,100]: {h}")
    return None


# --------------------------------------------------------------------------- R04
def r04_integrite(rec: dict, champs: list[str], exists_fn):
    """exists_fn(champ, valeur) -> bool. Rejette si une FK n'existe pas."""
    for champ in champs:
        val = rec.get(champ)
        if val in (None, ""):
            continue
        if not exists_fn(champ, val):
            return ("R04", f"clé étrangère absente: {champ}={val}")
    return None


# --------------------------------------------------------------------------- R05
def r05_date(rec: dict, champ: str):
    """Rejette si la date est absente ou non parsable."""
    if _to_date(rec.get(champ)) is None:
        return ("R05", f"date invalide: {champ}={rec.get(champ)!r}")
    return None


# --------------------------------------------------------------------------- R06
def r06_paiement(rec: dict):
    """Montant strictement positif ; le statut non-REUSSI est conservé mais exclu."""
    montant = _to_float(rec.get("montant_fcfa"))
    if montant is None or montant <= 0:
        return ("R06", "montant_fcfa <= 0")
    return None


# --------------------------------------------------------------------------- R07
def r07_ordre_temporel(rec: dict, champ_debut: str, champ_fin: str):
    """Rejette si date_fin < date_debut."""
    d1 = _to_date(rec.get(champ_debut))
    d2 = _to_date(rec.get(champ_fin))
    if d1 and d2 and d2 < d1:
        return ("R07", f"{champ_fin} < {champ_debut}")
    return None


# --------------------------------------------------------------------------- R08
def r08_gps(rec: dict):
    """Coordonnées dans la boîte englobante du pays ; vitesse <= 120 km/h."""
    lat = _to_float(rec.get("lat"))
    lon = _to_float(rec.get("lon"))
    vit = _to_float(rec.get("vitesse_kmh"))
    if lat is not None and not (CAMEROUN_BBOX["lat_min"] <= lat <= CAMEROUN_BBOX["lat_max"]):
        return ("R08", f"latitude hors Cameroun: {lat}")
    if lon is not None and not (CAMEROUN_BBOX["lon_min"] <= lon <= CAMEROUN_BBOX["lon_max"]):
        return ("R08", f"longitude hors Cameroun: {lon}")
    if vit is not None and vit > VITESSE_MAX_KMH:
        return ("R08", f"vitesse > {VITESSE_MAX_KMH}: {vit}")
    return None


# --------------------------------------------------------------------------- R10
def r10_texte(rec: dict, champ: str) -> bool:
    """Remplacer un texte vide/illisible par NON_RENSEIGNE. Renvoie True si remplacé."""
    val = rec.get(champ)
    if val is None or not str(val).strip():
        rec[champ] = "NON_RENSEIGNE"
        return True
    return False


# --------------------------------------------------------------------------- R01
def detecter_doublons(records: list[dict], cle: str):
    """R01 : sur la clé métier, garde l'enregistrement le plus récent (updated_at).

    Retourne (uniques, doublons) où doublons est la liste des enregistrements
    écartés.
    """
    meilleurs: dict[str, dict] = {}
    doublons: list[dict] = []
    for rec in records:
        k = rec.get(cle)
        if k not in meilleurs:
            meilleurs[k] = rec
            continue
        actuel = meilleurs[k]
        if str(rec.get("updated_at") or "") > str(actuel.get("updated_at") or ""):
            doublons.append(actuel)
            meilleurs[k] = rec
        else:
            doublons.append(rec)
    return list(meilleurs.values()), doublons
