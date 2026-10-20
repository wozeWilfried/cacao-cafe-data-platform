"""Chargement des dimensions : Type 1 (upsert) et SCD2 (historisation).

Les dimensions sont résolues AVANT les faits (cf. guide, étape 5). Les clés de
substitution sont retrouvées par jointure sur la clé métier au moment du
chargement des faits (voir etl/load/faits.py).

SCD2 (dim_cooperative, dim_producteur) :
  - hash_diff = md5 des attributs suivis ;
  - si l'attribut change : fermeture de la version courante
    (date_fin = date_effet - 1, est_courant = FALSE) puis insertion d'une
    nouvelle version (date_debut = date_effet, est_courant = TRUE) ;
  - clé unique partielle garantissant UNE seule version courante par bk.
"""

from __future__ import annotations

import hashlib

from etl.common.db import execute, query, scalar


def _md5(*parts) -> str:
    return hashlib.md5("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


# =============================================================================
# Type 1 : upsert sur la clé naturelle
# =============================================================================
def upsert_type1(conn, table: str, colonnes: list[str], cle: str, lignes: list[tuple]) -> int:
    """UPSERT générique Type 1. Retourne le nombre de lignes traitées."""
    if not lignes:
        return 0
    maj = ", ".join(f"{c} = EXCLUDED.{c}" for c in colonnes if c != cle)
    sql = (
        f"INSERT INTO dwh.{table} ({', '.join(colonnes)}) VALUES "
        f"({', '.join(['%s'] * len(colonnes))}) "
        f"ON CONFLICT ({cle}) DO UPDATE SET {maj}"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, lignes)
    return len(lignes)


def charger_geographie(conn, lignes: list[tuple]) -> int:
    return upsert_type1(
        conn, "dim_geographie",
        ["code_localite", "localite", "departement", "region", "pays", "latitude", "longitude", "station_meteo"],
        "code_localite", lignes,
    )


def charger_parcelle(conn, lignes: list[tuple]) -> int:
    return upsert_type1(
        conn, "dim_parcelle",
        ["parcelle_bk", "producteur_bk", "cooperative_bk", "culture", "variete",
         "surface_ha", "annee_plantation", "certification", "region", "geometry"],
        "parcelle_bk", lignes,
    )


def charger_acheteur(conn, lignes: list[tuple]) -> int:
    return upsert_type1(
        conn, "dim_acheteur",
        ["acheteur_bk", "raison_sociale", "pays", "type_acheteur"],
        "acheteur_bk", lignes,
    )


def charger_transporteur(conn, lignes: list[tuple]) -> int:
    return upsert_type1(
        conn, "dim_transporteur",
        ["transporteur_bk", "societe", "camion", "capacite_t"],
        "transporteur_bk", lignes,
    )


# =============================================================================
# SCD type 2
# =============================================================================
def charger_scd2(
    conn,
    table: str,
    nbk: str,
    attrs: list[str],
    lignes: list[dict],
    date_effet: str,
) -> tuple[int, int]:
    """Charge une dimension SCD2. Retourne (inserees, maj).

    `lignes` : dicts avec la clé naturelle (`nbk`) + les attributs suivis.
    """
    inserees = maj = 0
    for rec in lignes:
        bk = rec[nbk]
        hash_new = _md5(*[rec.get(a) for a in attrs])
        courant = query(
            conn,
            f"SELECT {nbk}, hash_diff FROM dwh.{table} WHERE {nbk} = %s AND est_courant",
            (bk,),
        )
        if not courant:
            cols = [nbk] + attrs + ["hash_diff", "date_debut", "date_fin", "est_courant"]
            vals = [bk] + [rec.get(a) for a in attrs] + [hash_new, date_effet, "9999-12-31", True]
            placeholders = ", ".join(["%s"] * len(cols))
            execute(conn, f"INSERT INTO dwh.{table} ({', '.join(cols)}) VALUES ({placeholders})", vals)
            inserees += 1
        elif courant[0][1] != hash_new:
            # Ferme la version courante la veille de la date d'effet.
            execute(
                conn,
                f"""UPDATE dwh.{table}
                    SET date_fin = (%s::date - INTERVAL '1 day')::date, est_courant = FALSE
                    WHERE {nbk} = %s AND est_courant""",
                (date_effet, bk),
            )
            cols = [nbk] + attrs + ["hash_diff", "date_debut", "date_fin", "est_courant"]
            vals = [bk] + [rec.get(a) for a in attrs] + [hash_new, date_effet, "9999-12-31", True]
            placeholders = ", ".join(["%s"] * len(cols))
            execute(conn, f"INSERT INTO dwh.{table} ({', '.join(cols)}) VALUES ({placeholders})", vals)
            maj += 1
    return inserees, maj


def charger_cooperative(conn, lignes: list[dict], date_effet: str) -> tuple[int, int]:
    return charger_scd2(
        conn, "dim_cooperative", "cooperative_bk",
        ["nom", "region", "departement", "ville", "capacite_stockage_t",
         "responsable", "certification", "statut"],
        lignes, date_effet,
    )


def charger_producteur(conn, lignes: list[dict], date_effet: str) -> tuple[int, int]:
    return charger_scd2(
        conn, "dim_producteur", "producteur_bk",
        ["nom", "sexe", "annee_naissance", "cooperative_bk", "culture",
         "region", "certification", "statut"],
        lignes, date_effet,
    )


# =============================================================================
# Résolution des clés de substitution (utilisée par les faits)
# =============================================================================
def cle_substitution(conn, table: str, sk: str, bk: str, valeur, date_iso: str | None = None):
    """Retourne la clé de substitution d'une dimension pour une clé métier.

    Pour les dimensions SCD2, la version valide à la date d'effet (`date_iso`,
    format AAAA-MM-JJ) est choisie : date_debut <= date <= date_fin.
    """
    if valeur in (None, ""):
        return None
    if date_iso and table in ("dim_cooperative", "dim_producteur"):
        rows = query(
            conn,
            f"""SELECT {sk} FROM dwh.{table}
                WHERE {bk} = %s AND %s::date BETWEEN date_debut AND date_fin
                ORDER BY date_debut DESC LIMIT 1""",
            (valeur, date_iso),
        )
        if rows:
            return rows[0][0]
    rows = query(conn, f"SELECT {sk} FROM dwh.{table} WHERE {bk} = %s LIMIT 1", (valeur,))
    return rows[0][0] if rows else None
