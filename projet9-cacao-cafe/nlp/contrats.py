"""NLP 2 · Extraction des clauses, dates et volumes des contrats d'exportation.

Objectif  : lire le texte libre des clauses d'un contrat et en extraire les
            engagements : date limite d'expédition, volume, incoterm, port,
            pénalité de retard.
Méthode   : règles (regex) sur le texte libre ; les balises structurées du
            contrat servent de vérité terrain pour mesurer l'extraction.
Évaluation: précision, rappel et F1 par type d'entité.
Sortie    : nlp.contrat_extraction + ml.metrique_modele.
"""

from __future__ import annotations

import re
import unicodedata

from ml.common import charger_dataframe, ecrire_metrique, source_conn

MOIS_FR = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}
MOIS_RE = "|".join(MOIS_FR)

INCOTERMS = ["FOB", "CIF", "CFR", "EXW", "FCA", "CPT", "CIP", "DAP"]


def _sans_accents(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in t if not unicodedata.combining(c))


def _extrait_date(texte: str):
    t = _sans_accents(texte).lower()
    # Forme 1 : « 15 novembre 2025 »
    m = re.search(rf"(\d{{1,2}})\s+({MOIS_RE})\s+(\d{{4}})", t)
    if m and m.group(2) in MOIS_FR:
        j, mo, a = int(m.group(1)), MOIS_FR[m.group(2)], int(m.group(3))
        return f"{a:04d}-{mo:02d}-{j:02d}", m.group(0)
    # Forme 2 : « 15/11/2025 » ou « 15-11-2025 »
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", t)
    if m:
        j, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{a:04d}-{mo:02d}-{j:02d}", m.group(0)
    return None, None


def _extrait_volume(texte: str):
    t = re.sub(r"\s+", " ", texte)
    m = re.search(r"(\d[\d\s\u202f.,]*)\s*(?:tonnes?|t)\b", t, re.IGNORECASE)
    if not m:
        return None, None
    nombre = m.group(1).replace(" ", "").replace("\u202f", "").replace(",", ".")
    nombre = nombre.rstrip(".")
    try:
        return round(float(nombre), 3), m.group(0)
    except ValueError:
        return None, None


def _extrait_incoterm(texte: str):
    for inc in INCOTERMS:
        m = re.search(rf"\b{inc}\b", texte)
        if m:
            return inc, m.group(0)
    return None, None


def _extrait_port(texte: str):
    for port in ("Douala", "Kribi"):
        m = re.search(rf"\b{port}\b", texte, re.IGNORECASE)
        if m:
            return port, m.group(0)
    return None, None


def _extrait_penalite(texte: str):
    t = _sans_accents(texte).lower()
    m = re.search(r"penalite\s*(?:de|:)?\s*([\d.,]+)\s*%", t)
    if m:
        val = m.group(1).replace(",", ".")
        try:
            return round(float(val), 3), m.group(0)
        except ValueError:
            return None, None
    return None, None


def _extraire(texte: str) -> dict:
    date, _ = _extrait_date(texte)
    vol, _ = _extrait_volume(texte)
    inc, _ = _extrait_incoterm(texte)
    port, _ = _extrait_port(texte)
    pen, _ = _extrait_penalite(texte)
    return {"DATE_LIMITE": date, "VOLUME_T": vol, "INCOTERM": inc,
            "PORT": port, "PENALITE_PCT": pen}


def _theta(preds, verites, entite=None):
    """Précision / rappel / F1 sur couples (id, entité) correctement extraits.

    Pour les volumes, la comparaison tolère ±2 % (le texte arrondit la valeur,
    et la clause elle-même stipule une tolérance de +/- 2 %).
    """
    def _bon(pred, verite):
        if pred is None or verite is None:
            return False
        if entite == "VOLUME_T":
            try:
                return abs(float(pred) - float(verite)) <= 0.02 * float(verite)
            except (TypeError, ValueError):
                return False
        return str(pred) == str(verite)

    tp = sum(1 for k, v in preds.items() if _bon(v, verites.get(k)))
    fp = sum(1 for k, v in preds.items() if v is not None and not _bon(v, verites.get(k)))
    fn = sum(1 for k in verites if verites.get(k) is not None and not _bon(preds.get(k), verites.get(k)))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    rappel = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * rappel / (precision + rappel) if (precision + rappel) else 0.0
    return round(100 * precision, 2), round(100 * rappel, 2), round(100 * f1, 2)


def executer(conn) -> int:
    with source_conn() as src:
        df = charger_dataframe(
            src,
            """
            SELECT contrat_id, clauses, date_fin::text AS date_fin, volume_t,
                   incoterm, port_chargement
              FROM coop.contrat
             WHERE clauses IS NOT NULL AND btrim(clauses) <> ''
            """,
        )
    if df.empty:
        return 0

    lignes = []
    preds = {"DATE_LIMITE": {}, "VOLUME_T": {}, "INCOTERM": {}, "PORT": {}, "PENALITE_PCT": {}}
    verites = {k: {} for k in preds}

    for r in df.itertuples(index=False):
        cid = r.contrat_id
        ext = _extraire(r.clauses)
        for entite, valeur in ext.items():
            surface, d, f = _positions(r.clauses, valeur)
            lignes.append((cid, entite, str(valeur) if valeur is not None else None,
                           d, f, "REGEX_CLAUSES"))
            preds[entite][cid] = valeur

        verites["DATE_LIMITE"][cid] = r.date_fin
        verites["VOLUME_T"][cid] = round(float(r.volume_t), 3) if r.volume_t is not None else None
        verites["INCOTERM"][cid] = r.incoterm
        verites["PORT"][cid] = r.port_chargement
        verites["PENALITE_PCT"][cid] = None  # non structuré : pas de vérité terrain

    with conn.cursor() as cur:
        cur.execute("DELETE FROM nlp.contrat_extraction WHERE modele = %s", ("REGEX_CLAUSES",))
        cur.executemany(
            """INSERT INTO nlp.contrat_extraction
                   (contrat_bk, entite, valeur, debut, fin, modele)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            lignes,
        )

    ecrits = len(lignes)
    for entite in ("DATE_LIMITE", "VOLUME_T", "INCOTERM", "PORT"):
        p, r_, f1 = _theta(preds[entite], verites[entite], entite)
        ecrire_metrique(conn, "REGEX_CLAUSES", entite, "test", "PRECISION", p)
        ecrire_metrique(conn, "REGEX_CLAUSES", entite, "test", "RAPPEL", r_)
        ecrire_metrique(conn, "REGEX_CLAUSES", entite, "test", "F1", f1)
        ecrits += 3
    ecrire_metrique(conn, "REGEX_CLAUSES", "CONTRATS", "test", "N", int(len(df)))
    return ecrits + 1


def _positions(texte, valeur):
    """Retourne (surface, debut, fin) de la valeur dans le texte (best effort)."""
    if valeur is None:
        return None, None, None
    cible = str(valeur)
    d = texte.find(cible)
    if d >= 0:
        return cible, d, d + len(cible)
    return cible, None, None
