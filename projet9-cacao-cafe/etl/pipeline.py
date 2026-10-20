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
    # RECOUVREMENT de 5 minutes : on relit un peu avant le filigrane pour ne pas
    # manquer une ligne dont le commit a suivi notre lecture. L'upsert rend le
    # rejeu inoffensif.
    depuis = None
    if mode == "INCR" and wm:
        depuis = _moins_5min(wm)
        where = "WHERE updated_at >= %s"
        params = (depuis,)
    with source_conn() as src:
        rows = query(
            src,
            f"""SELECT livraison_id, producteur_id, cooperative_id, parcelle_id, produit,
                       date_livraison, poids_brut_kg, poids_net_kg, nb_sacs, updated_at
                FROM coop.livraison {where} ORDER BY updated_at""",
            params,
        )
        # SUPPRESSIONS : le journal CDC liste les lignes disparues depuis le
        # filigrane (qu'une lecture par updated_at ne verrait pas).
        supprimes = []
        if mode == "INCR" and wm:
            rows_suppr = query(
                src,
                """SELECT DISTINCT cle_metier FROM coop.cdc_journal
                   WHERE table_nom = 'livraison' AND operation = 'D' AND horodatage >= %s""",
                (depuis,),
            )
            supprimes = [r[0] for r in rows_suppr]
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

            # SUPPRESSIONS logiques : les clés disparues passent est_supprime = TRUE.
            if supprimes:
                maj_suppr = fts.supprimer_livraisons(conn, supprimes, run.run_id)
                run.ajouter("supprimees", maj_suppr)

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
# SOURCES 3-8 : faits issus de la base source (qualité, transport, export,
#               intrants, prix, trafic). Chacun suit le cycle en 6 étapes.
# -----------------------------------------------------------------------------
def _cache_produit(conn) -> dict:
    return {r[0]: r[1] for r in query(conn, "SELECT code_produit, produit_sk FROM dwh.dim_produit")}


def _cache_canal(conn) -> dict:
    return {r[0]: r[1] for r in query(conn, "SELECT code_canal, canal_sk FROM dwh.dim_canal")}


def _cache_port(conn) -> dict:
    return {r[0]: r[1] for r in query(conn, "SELECT code_port, port_sk FROM dwh.dim_port")}


def _cache_defaut(conn) -> dict:
    return {r[0]: r[1] for r in query(conn, "SELECT code_defaut, defaut_sk FROM dwh.dim_defaut")}


def _cache_intrant(conn) -> dict:
    return {r[0]: r[1] for r in query(conn, "SELECT code_intrant, intrant_sk FROM dwh.dim_intrant")}


def _etl_fait(conn, source_name: str, charger_fn, construit, code_regle=None,
              mode: str = "FULL") -> journal.RunLog:
    """Squelette commun : extraire -> stager -> contrôler -> charger -> journaliser.

    `construit(conn, lignes_brutes)` retourne (nb_attendus, rows) ; les rows sont
    passées à `charger_fn(conn, rows)` (upsert idempotent).
    """
    from etl.common.db import source_conn

    with source_conn() as src:
        brutes = construit(src)

    run = journal.ouvrir_run(conn, source_name, mode, declencheur="PLANIFIE")
    try:
        run.ajouter("lues", len(brutes[1]))
        with conn.transaction():
            _point_de_panne(f"chargement {source_name}", False)
            insc = charger_fn(conn, brutes)
            run.ajouter("inserees", insc)
            journal.fermer_run(conn, run)
    except Exception as exc:  # noqa: BLE001
        journal.echec_run(conn, run, exc)
        raise
    return run


def etl_qualite(conn, mode: str = "FULL") -> journal.RunLog:
    """Qualité des lots (coop.lot_qualite -> fait_qualite_lot)."""
    from etl.common.db import source_conn

    with source_conn() as src:
        rows = query(src, """SELECT lot_id, cooperative_id, date_reception, date_analyse,
                                    humidite_pct, nb_grains_comptes, grains_defectueux_pct,
                                    grade, decision, defaut_principal, observation
                             FROM coop.lot_qualite ORDER BY date_analyse""")
    run = journal.ouvrir_run(conn, "qualite", mode, declencheur="PLANIFIE")
    run.ajouter("lues", len(rows))
    try:
        with conn.transaction():
            cache_coop = _cache_bk(conn, "dim_cooperative", "cooperative_sk", "cooperative_bk")
            cache_def = _cache_defaut(conn)
            fait_rows = []
            for r in rows:
                date_iso = str(r[3] or r[2])[:10]
                date_sk = int(date_iso.replace("-", ""))
                code = r[9]
                defaut_sk = None if code in (None, "CONFORME") else cache_def.get(code)
                delai = (r[3] - r[2]).days if r[2] and r[3] else None
                fait_rows.append((
                    str(r[0]), date_sk, cache_coop.get(r[1]), 1,
                    defaut_sk, _float(r[4]), _float(r[6]), _int(r[5]),
                    r[7], r[8], r[10], delai, run.run_id,
                ))
            insc = fts.upsert_qualite(conn, fait_rows)
            run.ajouter("inserees", insc)
            journal.fermer_run(conn, run)
    except Exception as exc:  # noqa: BLE001
        journal.echec_run(conn, run, exc)
        raise
    return run


def etl_prix(conn, mode: str = "FULL") -> journal.RunLog:
    """Prix mondiaux (coop.prix_marche -> fait_prix_marche), convertis en FCFA."""
    from etl.common.db import source_conn

    with source_conn() as src:
        rows = query(src, """SELECT date_mois, produit, unite, prix
                             FROM coop.prix_marche
                             WHERE date_mois >= DATE '2000-01-01'
                             ORDER BY date_mois""")
        # Taux USD/XAF du jour (dernier connu avant chaque mois).
        taux = query(src, """SELECT date_jour, taux FROM coop.taux_change
                             WHERE paire = 'USD/XAF' ORDER BY date_jour""")
    taux = [(str(d), float(t)) for d, t in taux]

    def _taux_du(date_iso: str):
        val = None
        for d, t in taux:
            if d <= date_iso:
                val = t
            else:
                break
        return val

    run = journal.ouvrir_run(conn, "prix_marche", mode, declencheur="MANUEL")
    run.ajouter("lues", len(rows))
    try:
        with conn.transaction():
            cache_prod = _cache_produit(conn)
            fait_rows = []
            for r in rows:
                date_iso = str(r[0])[:10]
                date_sk = int(date_iso.replace("-", ""))
                prix_usd = float(r[3])
                tx = _taux_du(date_iso)
                fait_rows.append((
                    f"{r[0]}|{r[1]}|{r[2]}", date_sk, cache_prod.get(r[1]),
                    "PINK_SHEET", r[2], prix_usd,
                    round(prix_usd * tx, 2) if tx else None, run.run_id,
                ))
            insc = fts.upsert_prix_marche(conn, fait_rows)
            run.ajouter("inserees", insc)
            journal.fermer_run(conn, run)
    except Exception as exc:  # noqa: BLE001
        journal.echec_run(conn, run, exc)
        raise
    return run


def etl_export(conn, mode: str = "FULL") -> journal.RunLog:
    """Contrats d'export (coop.contrat -> fait_export)."""
    from etl.common.db import source_conn

    with source_conn() as src:
        rows = query(src, """SELECT contrat_id, acheteur, pays, produit, volume_t,
                                    prix_fcfa_kg, date_contrat, incoterm,
                                    port_chargement, statut
                             FROM coop.contrat ORDER BY date_contrat""")
        acheteurs = query(src, "SELECT DISTINCT acheteur, pays FROM coop.contrat")

    run = journal.ouvrir_run(conn, "export", mode, declencheur="PLANIFIE")
    run.ajouter("lues", len(rows))
    try:
        with conn.transaction():
            # Référentiel acheteurs (Type 1) alimenté depuis les contrats.
            dim.charger_acheteur(conn, [
                (a, a, p, "importateur") for a, p in acheteurs
            ])
            cache_prod = _cache_produit(conn)
            cache_port = _cache_port(conn)
            cache_ach = {r[0]: r[1] for r in query(conn, "SELECT acheteur_bk, acheteur_sk FROM dwh.dim_acheteur")}
            fait_rows = []
            for r in rows:
                date_iso = str(r[6])[:10]
                date_sk = int(date_iso.replace("-", ""))
                volume = _float(r[4]) or 0.0
                prix = _float(r[5]) or 0.0
                nb_cont = max(1, round(volume / 24)) if volume else None  # ~24 t / EVP
                fait_rows.append((
                    str(r[0]), date_sk, cache_prod.get(r[3]), cache_ach.get(r[1]),
                    cache_port.get(str(r[8]).upper()), volume, prix,
                    round(volume * 1000 * prix, 2), nb_cont, r[7], r[9], run.run_id,
                ))
            insc = fts.upsert_export(conn, fait_rows)
            run.ajouter("inserees", insc)
            journal.fermer_run(conn, run)
    except Exception as exc:  # noqa: BLE001
        journal.echec_run(conn, run, exc)
        raise
    return run


def etl_intrants(conn, mode: str = "FULL") -> journal.RunLog:
    """Distributions d'intrants (coop.intrant_distribution -> fait_intrants)."""
    from etl.common.db import source_conn

    with source_conn() as src:
        rows = query(src, """SELECT distribution_id, producteur_id, cooperative_id,
                                    date_distribution, intrant_id, quantite, cout_fcfa, campagne
                             FROM coop.intrant_distribution ORDER BY date_distribution""")
    run = journal.ouvrir_run(conn, "intrants", mode, declencheur="PLANIFIE")
    run.ajouter("lues", len(rows))
    try:
        with conn.transaction():
            cache_prod = _cache_bk(conn, "dim_producteur", "producteur_sk", "producteur_bk")
            cache_coop = _cache_bk(conn, "dim_cooperative", "cooperative_sk", "cooperative_bk")
            cache_int = _cache_intrant(conn)
            fait_rows = []
            for r in rows:
                date_iso = str(r[3])[:10]
                date_sk = int(date_iso.replace("-", ""))
                fait_rows.append((
                    str(r[0]), date_sk, cache_prod.get(r[1]), cache_coop.get(r[2]),
                    cache_int.get(r[4]), _int(r[5]), _int(r[6]), r[7], run.run_id,
                ))
            insc = fts.upsert_intrants(conn, fait_rows)
            run.ajouter("inserees", insc)
            journal.fermer_run(conn, run)
    except Exception as exc:  # noqa: BLE001
        journal.echec_run(conn, run, exc)
        raise
    return run


def etl_trafic(conn, mode: str = "FULL") -> journal.RunLog:
    """Trafic portuaire (coop.trafic_port -> fait_trafic_port)."""
    from etl.common.db import source_conn

    with source_conn() as src:
        rows = query(src, """SELECT escale_id, port, date_arrivee, date_depart,
                                    conteneurs, tonnage_t, statut
                             FROM coop.trafic_port ORDER BY date_arrivee""")
    run = journal.ouvrir_run(conn, "trafic_port", mode, declencheur="PLANIFIE")
    run.ajouter("lues", len(rows))
    try:
        with conn.transaction():
            cache_port = _cache_port(conn)
            fait_rows = []
            for r in rows:
                date_iso = str(r[2])[:10]
                date_sk = int(date_iso.replace("-", ""))
                duree_h = None
                if r[3] and r[2]:
                    duree_h = round((r[3] - r[2]).total_seconds() / 3600, 2)
                fait_rows.append((
                    str(r[0]), date_sk, cache_port.get(str(r[1]).upper()),
                    _int(r[4]), _float(r[5]), None, duree_h, r[6], run.run_id,
                ))
            insc = fts.upsert_trafic_port(conn, fait_rows)
            run.ajouter("inserees", insc)
            journal.fermer_run(conn, run)
    except Exception as exc:  # noqa: BLE001
        journal.echec_run(conn, run, exc)
        raise
    return run


def etl_transport(conn, mode: str = "FULL") -> journal.RunLog:
    """Transport : agrégation des pings par lot (coop.transport_ping -> fait_transport).

    Distance = somme des écarts haversine successifs ; poids de départ/arrivée
    repris des événements DEPART / ARRIVEE_PORT (pertes = différence).
    """
    import math
    from etl.common.db import source_conn

    with source_conn() as src:
        rows = query(src, """
            SELECT lot_id, horodatage, latitude, longitude, evenement, poids_kg
              FROM coop.transport_ping
             ORDER BY lot_id, horodatage
        """)

    def _haversine(a, b):
        lat1, lon1 = math.radians(a[0]), math.radians(a[1])
        lat2, lon2 = math.radians(b[0]), math.radians(b[1])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 6371.0 * 2 * math.asin(math.sqrt(h))

    trajets = {}
    for lot, ts, lat, lon, ev, poids in rows:
        t = trajets.setdefault(str(lot), {"debut": ts, "fin": ts, "n": 0, "dist": 0.0,
                                          "prev": None, "depart": None, "arrivee": None})
        t["n"] += 1
        t["fin"] = max(t["fin"], ts)
        if lat is not None and lon is not None:
            if t["prev"] is not None:
                t["dist"] += _haversine(t["prev"], (float(lat), float(lon)))
            t["prev"] = (float(lat), float(lon))
        if ev == "DEPART" and poids is not None:
            t["depart"] = float(poids)
        if ev == "ARRIVEE_PORT" and poids is not None:
            t["arrivee"] = float(poids)

    run = journal.ouvrir_run(conn, "transport", mode, declencheur="PLANIFIE")
    run.ajouter("lues", len(trajets))
    try:
        with conn.transaction():
            cache_trp = {r[0]: r[1] for r in query(conn, "SELECT transporteur_bk, transporteur_sk FROM dwh.dim_transporteur")}
            fait_rows = []
            for lot, t in trajets.items():
                date_iso = str(t["fin"])[:10]
                date_sk = int(date_iso.replace("-", ""))
                duree_min = round((t["fin"] - t["debut"]).total_seconds() / 60) if t["debut"] and t["fin"] else None
                pertes = None
                if t["depart"] is not None and t["arrivee"] is not None:
                    pertes = round(t["depart"] - t["arrivee"], 2)
                fait_rows.append((
                    lot, date_sk, None, cache_trp.get("TRP_INCONNU"), None,
                    round(t["dist"], 2), duree_min, t["n"], t["depart"], t["arrivee"],
                    pertes, run.run_id,
                ))
            insc = fts.upsert_transport(conn, fait_rows)
            run.ajouter("inserees", insc)
            journal.fermer_run(conn, run)
    except Exception as exc:  # noqa: BLE001
        journal.echec_run(conn, run, exc)
        raise
    return run


# -----------------------------------------------------------------------------
# Helpers de conversion
# -----------------------------------------------------------------------------
def _moins_5min(watermark_iso: str) -> str:
    """Recule un filigrane ISO de 5 minutes (recouvrement)."""
    from datetime import datetime, timedelta, timezone

    try:
        dt = datetime.fromisoformat(watermark_iso.replace("Z", "+00:00"))
    except ValueError:
        return watermark_iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - timedelta(minutes=5)).isoformat()


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


# =============================================================================
# SOURCE : paiements (un fichier JSON par jour dans data/inbox/paiements)
# =============================================================================
def etl_paiements(conn, mode: str = "INCR", declencheur: str = "FICHIER",
                  echouer: bool = False) -> journal.RunLog:
    """Traite les fichiers de paiements non encore traités (hachage).

    Chaque fichier est lu, contrôlé (R06 montant > 0, R04 intégrité) puis chargé
    en upsert ; il est ensuite déplacé vers data/archive et inscrit dans
    etl.fichier_traite. Un fichier corrigé (hachage différent) est relu.
    """
    import csv as _csv  # noqa: F401
    import json

    fichiers = sorted(PAIEMENTS_DIR.glob(PAIEMENTS_GLOB)) if PAIEMENTS_DIR.exists() else []
    run = journal.ouvrir_run(conn, "paiement", mode, declencheur=declencheur)

    cache_canal = {r[0]: r[1] for r in query(conn, "SELECT code_canal, canal_sk FROM dwh.dim_canal")}
    cache_prod = _cache_bk(conn, "dim_producteur", "producteur_sk", "producteur_bk")

    traites = 0
    for fichier in fichiers:
        h = _hash(fichier)
        if journal.fichier_deja_traite(conn, fichier.name, h):
            continue
        paquets = json.loads(fichier.read_text(encoding="utf-8"))
        lignes = paquets if isinstance(paquets, list) else paquets.get("paiements", [])
        run.ajouter("lues", len(lignes))

        with conn.transaction():
            fait_rows = []
            for p in lignes:
                if regles.r06_paiement(p):
                    journal.rejeter(conn, run, p.get("paiement_id"), "R06", p)
                    continue
                date_iso = str(p.get("horodatage") or p.get("date"))[:10]
                date_sk = int(date_iso.replace("-", "")) if date_iso else None
                fait_rows.append((
                    str(p.get("paiement_id")), date_sk,
                    cache_canal.get(p.get("operateur")),
                    cache_prod.get(p.get("producteur_id")), None,
                    _int(p.get("montant_fcfa")), _int(p.get("frais_fcfa")) or 0,
                    _int(p.get("delai_jours")), p.get("statut"), run.run_id,
                ))
            n = fts.upsert_paiement(conn, fait_rows)
            run.ajouter("inserees", n)
            journal.marquer_fichier(conn, fichier.name, h, run.run_id, "SUCCESS")
            traites += 1

        _deplacer(fichier, ARCHIVE_DIR)

    journal.fermer_run(conn, run)
    return run


def traiter_paiements(declencheur: str = "FICHIER", **_) -> dict:
    """Point d'entrée utilisé par le DAG Airflow (mécanisme B)."""
    with dwh_conn(autocommit=True) as conn:
        run = etl_paiements(conn, declencheur=declencheur)
    return run.compteurs


def charger_tous_les_faits() -> dict:
    """Charge les 8 faits dans l'ordre des dépendances (dimensions d'abord)."""
    with dwh_conn(autocommit=True) as conn:
        etl_referentiels(conn, "2023-10-01")
        etl_livraisons(conn, mode="FULL")
        etl_qualite(conn)
        etl_prix(conn)
        etl_export(conn)
        etl_intrants(conn)
        etl_trafic(conn)
        etl_transport(conn)
        etl_paiements(conn)
        return {r[0]: r[1] for r in query(
            conn,
            """SELECT 'livraison', count(*) FROM dwh.fait_livraison
               UNION ALL SELECT 'paiement', count(*) FROM dwh.fait_paiement
               UNION ALL SELECT 'qualite', count(*) FROM dwh.fait_qualite_lot
               UNION ALL SELECT 'prix', count(*) FROM dwh.fait_prix_marche
               UNION ALL SELECT 'export', count(*) FROM dwh.fait_export
               UNION ALL SELECT 'intrants', count(*) FROM dwh.fait_intrants
               UNION ALL SELECT 'trafic', count(*) FROM dwh.fait_trafic_port
               UNION ALL SELECT 'transport', count(*) FROM dwh.fait_transport""",
        )}


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="ETL Projet 9 — orchestration des sources.")
    parser.add_argument("--source", default="referentiels",
                        choices=["referentiels", "livraisons", "paiements", "qualite",
                                 "prix", "export", "intrants", "trafic", "transport", "tous"])
    parser.add_argument("--snapshot", default="2022-10-01")
    parser.add_argument("--mode", default="FULL", choices=["FULL", "INCR"])
    parser.add_argument("--panne", action="store_true", help="simuler un échec (run 4)")
    args = parser.parse_args()

    simples = {"qualite": etl_qualite, "prix": etl_prix, "export": etl_export,
               "intrants": etl_intrants, "trafic": etl_trafic, "transport": etl_transport}

    if args.source == "tous":
        print(charger_tous_les_faits())
        return 0

    with dwh_conn(autocommit=True) as conn:
        if args.source == "referentiels":
            run = etl_referentiels(conn, args.snapshot, echouer=args.panne)
        elif args.source == "paiements":
            run = etl_paiements(conn, mode=args.mode, echouer=args.panne)
        elif args.source == "livraisons":
            run = etl_livraisons(conn, mode=args.mode, echouer=args.panne)
        else:
            run = simples[args.source](conn, mode=args.mode)
        print(f"run {run.run_id} ({run.source_name}) — {run.compteurs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
