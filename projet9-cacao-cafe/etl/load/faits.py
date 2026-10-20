"""Chargement des faits : upsert idempotent sur la clé métier.

Chaque fait possède une clé métier unique (livraison_bk, paiement_bk, …) : un
ON CONFLICT DO UPDATE rend le chargement rejouable sans créer de doublon
(la clé de substitution reste stable).
"""

from __future__ import annotations


def _upsert(conn, table: str, colonnes: list[str], cle: str, lignes: list[tuple]) -> int:
    if not lignes:
        return 0
    maj = ", ".join(f"{c} = EXCLUDED.{c}" for c in colonnes if c != cle)
    sql = (
        f"INSERT INTO dwh.{table} ({', '.join(colonnes)}) VALUES "
        f"({', '.join(['%s'] * len(colonnes))}) "
        f"ON CONFLICT ({cle}) DO UPDATE SET {maj}, maj_le = now()"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, lignes)
    return len(lignes)


def upsert_livraison(conn, lignes: list[tuple]) -> int:
    return _upsert(conn, "fait_livraison",
        ["livraison_bk", "date_sk", "produit_sk", "cooperative_sk", "producteur_sk",
         "parcelle_sk", "geo_sk", "poids_brut_kg", "poids_net_kg", "nb_sacs", "etl_run_id"],
        "livraison_bk", lignes)


def upsert_paiement(conn, lignes: list[tuple]) -> int:
    return _upsert(conn, "fait_paiement",
        ["paiement_bk", "date_sk", "canal_sk", "producteur_sk", "cooperative_sk",
         "montant_fcfa", "frais_fcfa", "delai_jours", "statut", "etl_run_id"],
        "paiement_bk", lignes)


def upsert_qualite(conn, lignes: list[tuple]) -> int:
    return _upsert(conn, "fait_qualite_lot",
        ["lot_bk", "date_sk", "cooperative_sk", "produit_sk", "defaut_sk",
         "humidite_pct", "grains_defectueux_pct", "nb_grains_comptes", "grade",
         "decision", "observation", "etl_run_id"],
        "lot_bk", lignes)


def upsert_transport(conn, lignes: list[tuple]) -> int:
    return _upsert(conn, "fait_transport",
        ["trajet_bk", "date_sk", "cooperative_sk", "transporteur_sk", "port_sk",
         "distance_km", "duree_min", "nb_pings", "pertes_kg", "etl_run_id"],
        "trajet_bk", lignes)


def upsert_export(conn, lignes: list[tuple]) -> int:
    return _upsert(conn, "fait_export",
        ["contrat_bk", "date_sk", "produit_sk", "acheteur_sk", "port_sk",
         "volume_t", "prix_fcfa_kg", "montant_fcfa", "nb_conteneurs", "incoterm",
         "statut", "etl_run_id"],
        "contrat_bk", lignes)


def upsert_prix_marche(conn, lignes: list[tuple]) -> int:
    return _upsert(conn, "fait_prix_marche",
        ["prix_bk", "date_sk", "produit_sk", "source", "unite", "prix_usd",
         "prix_fcfa", "etl_run_id"],
        "prix_bk", lignes)


def upsert_meteo(conn, lignes: list[tuple]) -> int:
    return _upsert(conn, "fait_meteo",
        ["meteo_bk", "date_sk", "geo_sk", "source", "temperature", "pluie_mm", "etl_run_id"],
        "meteo_bk", lignes)


def upsert_intrants(conn, lignes: list[tuple]) -> int:
    return _upsert(conn, "fait_intrants",
        ["distribution_bk", "date_sk", "producteur_sk", "cooperative_sk", "intrant_sk",
         "quantite", "cout_fcfa", "campagne", "etl_run_id"],
        "distribution_bk", lignes)


def upsert_trafic_port(conn, lignes: list[tuple]) -> int:
    return _upsert(conn, "fait_trafic_port",
        ["escale_bk", "date_sk", "port_sk", "conteneurs", "tonnage_t", "attente_h",
         "duree_h", "statut", "etl_run_id"],
        "escale_bk", lignes)
