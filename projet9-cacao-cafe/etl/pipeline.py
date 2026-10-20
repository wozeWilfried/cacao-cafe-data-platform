"""ETL — orchestration des six étapes pour chaque source.

Cycle (cf. guide, section 06) :
  1. extraire   : lire la source (fichier ou base, depuis le filigrane)
  2. stager     : copier tel quel dans stg.* avec run_id et charge_le
  3. contrôler  : appliquer les 10 règles ; rejets -> etl.rejet
  4. transformer: normaliser, dériver (FCFA/kg, hachages), résoudre les clés
  5. charger    : dimensions puis faits, en transaction, upsert idempotent
  6. journaliser: fermer run_log, avancer le filigrane, archiver/quarantaine

Tout se déroule dans UNE transaction par source : en cas d'échec, rien n'est à
moitié écrit et le filigrane n'a pas bougé (reprise sur incident).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "generate"))

from common import (  # noqa: E402
    CONTRATS_DIR,
    INBOX_DIR,
    PAIEMENTS_DIR,
    PAIEMENTS_GLOB,
    PUBLIC_DIR,
    QUALITE_DIR,
    QUALITE_GLOB,
    TRAFIC_DIR,
    TRANSPORT_DIR,
    ensure_dir,
)

from etl.common.db import dwh_conn, execute, query, scalar  # noqa: E402
from etl.common import journal  # noqa: E402
from etl.load import dimensions as dim  # noqa: E402
from etl.load import faits as fts  # noqa: E402
from etl.quality import regles  # noqa: E402

ARCHIVE_DIR = ensure_dir(PROJECT_ROOT / "data" / "archive")
QUARANTAINE_DIR = ensure_dir(PROJECT_ROOT / "data" / "quarantaine")


# -----------------------------------------------------------------------------
# Aides fichier
# -----------------------------------------------------------------------------
def _hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _deplacer(source: Path, dossier: Path) -> None:
    """Déplace un fichier traité vers archive ou quarantaine."""
    if source.exists():
        cible = dossier / source.name
        if cible.exists():
            cible.unlink()
        shutil.move(str(source), str(cible))


# -----------------------------------------------------------------------------
# Démonstration de la reprise sur incident
# -----------------------------------------------------------------------------
class PanneSimulee(Exception):
    """Levée volontairement pour montrer la reprise sur incident (run 4)."""


def _point_de_panne(etape: str, echouer: bool) -> None:
    if echouer:
        raise PanneSimulee(f"échec volontaire à l'étape « {etape} »")


# -----------------------------------------------------------------------------
# Pipeline générique : staging + chargement des dimensions de référence
# -----------------------------------------------------------------------------
def _stager_lignes(conn, table: str, colonnes: list[str], lignes: list[tuple], run_id: int) -> None:
    """Copie brute en staging (append) avec run_id. Purge d'abord le run courant."""
    execute(conn, f"DELETE FROM stg.{table} WHERE run_id = %s", (run_id,))
    cols = ["run_id"] + colonnes
    placeholders = ", ".join(["%s"] * len(cols))
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO stg.{table} ({', '.join(cols)}) VALUES ({placeholders})", 
            [(run_id, *l) for l in lignes],
        )


# =============================================================================
# SOURCE 1 : référentiels (coopératives, producteurs, parcelles)
# =============================================================================
def etl_referentiels(conn, snapshot: str, echouer: bool = False) -> journal.RunLog:
    from common import load_referentiels

    ref = load_referentiels(snapshot)
    run = journal.ouvrir_run(conn, "referentiels", "FULL", declencheur="FICHIER")
    try:
        # Tout le travail est dans UNE transaction : en cas d'échec, rien de partiel.
        with conn.transaction():
            _charger_referentiels_tx(conn, ref, snapshot, run, echouer)
            journal.fermer_run(conn, run, watermark_apres=snapshot)
    except Exception as exc:  # noqa: BLE001
        journal.echec_run(conn, run, exc)
        raise
    return run


def _charger_referentiels_tx(conn, ref, snapshot, run, echouer):
        # Dimensions SCD2 : coopératives puis producteurs.
        coops = [
            {
                "cooperative_bk": c["cooperative_id"], "nom": c["nom"], "region": c["region"],
                "departement": c.get("departement"), "ville": c.get("ville"),
                "capacite_stockage_t": _int(c.get("capacite_stockage_t")),
                "responsable": c.get("responsable"), "certification": c.get("certification"),
                "statut": c.get("statut"),
            }
            for c in ref["cooperatives"].values()
        ]
        insc, maj = dim.charger_cooperative(conn, coops, snapshot)
        run.ajouter("inserees", insc)
        run.ajouter("maj", maj)

        _point_de_panne("chargement producteurs", echouer)

        prods = [
            {
                "producteur_bk": p["producteur_id"], "nom": p.get("nom"), "sexe": p.get("sexe"),
                "annee_naissance": _int(p.get("annee_naissance")),
                "cooperative_bk": p.get("cooperative_id"), "culture": p.get("culture"),
                "region": p.get("region"), "certification": p.get("certification"),
                "statut": p.get("statut"),
            }
            for p in ref["producteurs"].values()
        ]
        insc, maj = dim.charger_producteur(conn, prods, snapshot)
        run.ajouter("inserees", insc)
        run.ajouter("maj", maj)

        # Type 1 : géographie (par région/département) et parcelles.
        geo = {}
        for c in ref["cooperatives"].values():
            cle = f"{c['region']}|{c.get('departement','')}"
            geo[cle] = (
                cle, c.get("ville"), c.get("departement"), c.get("region"), "Cameroun",
                _float(c.get("latitude")), _float(c.get("longitude")), None,
            )
        dim.charger_geographie(conn, list(geo.values()))

        parcelles = []
        for f in ref["parcelles"]:
            pr = f["properties"]
            parcelles.append((
                pr["parcelle_id"], pr["producteur_id"], pr.get("cooperative_id"),
                pr.get("culture"), pr.get("variete"), _float(pr.get("surface_ha")),
                _int(pr.get("annee_plantation")), pr.get("certification"),
                pr.get("region"), _json(f.get("geometry")),
            ))
        dim.charger_parcelle(conn, parcelles)

        # Staging (copie brute tracée).
        _stager_lignes(conn, "livraison", ["livraison_id"], [], run.run_id)


# =============================================================================
# SOURCE 2 : livraisons (depuis la base source, full ou incrémental)
# =============================================================================
def etl_livraisons(conn, mode: str = "FULL", echouer: bool = False) -> journal.RunLog:
    # EXTRAIRE — depuis coop.livraison (base source).
    from etl.common.db import source_conn

    where, params = "", ()
    wm = journal.lire_watermark(conn, "livraison")
    if mode == "INCR" and wm:
        where = "WHERE updated_at > %s"
        params = (wm,)
    with source_conn() as src:
        rows = query(
            src,
            f"""SELECT livraison_id, producteur_id, cooperative_id, parcelle_id, produit,
                       date_livraison, poids_brut_kg, poids_net_kg, nb_sacs, updated_at
                FROM coop.livraison {where} ORDER BY updated_at""",
            params,
        )
    lignes = [
        {
            "livraison_id": str(r[0]), "producteur_id": r[1], "cooperative_id": r[2],
            "parcelle_id": r[3], "produit": r[4], "date_livraison": r[5].isoformat(),
            "poids_brut_kg": r[6], "poids_net_kg": r[7], "nb_sacs": r[8],
            "updated_at": r[9].isoformat(),
        }
        for r in rows
    ]

    run = journal.ouvrir_run(conn, "livraison", mode, declencheur="PLANIFIE")
    try:
        run.ajouter("lues", len(lignes))

        # Tout le travail (staging, contrôles, chargement, filigrane) est dans UNE
        # transaction : un échec annule tout, le filigrane ne bouge pas.
        with conn.transaction():
            # STAGER
            _stager_lignes(
                conn, "livraison",
                ["livraison_id", "producteur_id", "cooperative_id", "parcelle_id", "produit",
                 "date_livraison", "poids_brut_kg", "poids_net_kg", "nb_sacs", "updated_at"],
                [(l["livraison_id"], l["producteur_id"], l["cooperative_id"], l["parcelle_id"],
                  l["produit"], l["date_livraison"], str(l["poids_brut_kg"]), str(l["poids_net_kg"]),
                  str(l["nb_sacs"]), l["updated_at"]) for l in lignes],
                run.run_id,
            )

            # CONTRÔLER — R01 doublons, R02, R03, R05.
            uniques, doublons = regles.detecter_doublons(lignes, "livraison_id")
            for d in doublons:
                journal.rejeter(conn, run, d["livraison_id"], "R01", d)

            valides = []
            for l in uniques:
                for controle in (
                    regles.r02_obligatoires(l, ["livraison_id", "producteur_id", "date_livraison", "poids_net_kg"]),
                    regles.r03_domaine_poids(l),
                    regles.r05_date(l, "date_livraison"),
                ):
                    if controle:
                        journal.rejeter(conn, run, l["livraison_id"], controle[0], {"motif": controle[1], **l})
                        break
                else:
                    valides.append(l)

            _point_de_panne("chargement faits", echouer)

            # CHARGER — résolution des clés puis upsert idempotent.
            cache_prod = _cache_bk(conn, "dim_producteur", "producteur_sk", "producteur_bk")
            cache_coop = _cache_bk(conn, "dim_cooperative", "cooperative_sk", "cooperative_bk")
            cache_parc = _cache_bk(conn, "dim_parcelle", "parcelle_sk", "parcelle_bk")

            fait_rows = []
            for l in valides:
                date_iso = l["date_livraison"][:10]
                date_sk = int(date_iso.replace("-", ""))
                fait_rows.append((
                    l["livraison_id"], date_sk, 1 if l["produit"] == "CACAO" else 2,
                    cache_coop.get(l["cooperative_id"]), cache_prod.get(l["producteur_id"]),
                    cache_parc.get(l["parcelle_id"]), None,
                    _float(l["poids_brut_kg"]), _float(l["poids_net_kg"]), _int(l["nb_sacs"]),
                    run.run_id,
                ))
            insc = fts.upsert_livraison(conn, fait_rows)
            run.ajouter("inserees", insc)

            # JOURNALISER — filigrane avancé DANS la transaction de chargement.
            wm_apres = max((l["updated_at"] for l in lignes), default=wm)
            if wm_apres:
                journal.ecrire_watermark(conn, "livraison", wm_apres)
            journal.fermer_run(conn, run, watermark_apres=wm_apres)
    except Exception as exc:  # noqa: BLE001
        # Hors transaction : le statut FAILED doit rester visible dans le journal.
        journal.echec_run(conn, run, exc)
        raise
    return run


# -----------------------------------------------------------------------------
# Helpers de conversion
# -----------------------------------------------------------------------------
def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _json(v):
    import json
    return json.dumps(v) if v is not None else None


def _cache_bk(conn, table: str, sk: str, bk: str) -> dict:
    """Dictionnaire {clé_métier: clé_substitution} (version courante)."""
    if table in ("dim_cooperative", "dim_producteur"):
        rows = query(conn, f"SELECT {bk}, {sk} FROM dwh.{table} WHERE est_courant")
    else:
        rows = query(conn, f"SELECT {bk}, {sk} FROM dwh.{table}")
    return {r[0]: r[1] for r in rows}


def _cache_geo(conn, table: str, sk: str, bk: str) -> dict:
    return _cache_bk(conn, table, sk, bk)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="ETL Projet 9 — orchestration des sources.")
    parser.add_argument("--source", default="referentiels",
                        choices=["referentiels", "livraisons"])
    parser.add_argument("--snapshot", default="2022-10-01")
    parser.add_argument("--mode", default="FULL", choices=["FULL", "INCR"])
    parser.add_argument("--panne", action="store_true", help="simuler un échec (run 4)")
    args = parser.parse_args()

    with dwh_conn(autocommit=True) as conn:
        if args.source == "referentiels":
            run = etl_referentiels(conn, args.snapshot, echouer=args.panne)
        else:
            run = etl_livraisons(conn, mode=args.mode, echouer=args.panne)
        print(f"run {run.run_id} ({run.source_name}) — {run.compteurs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
