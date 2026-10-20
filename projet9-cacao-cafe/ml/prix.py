"""ML 3 · Prévision du prix mondial et simulation de marge.

Objectif  : prévoir le prix mondial à 1-3 mois puis mesurer la marge de la
            filière sous différents scénarios (prix, change, transport).
Référence : dernier prix observé (marche aléatoire).
Modèle    : ETS (statsmodels) avec repli tendance linéaire, par produit.
Évaluation: MAE, RMSE, MAPE en validation glissante vs dernier prix observé.
Sortie    : ml.prevision_prix + ml.scenario_marge + ml.metrique_modele.
"""

from __future__ import annotations

import warnings
from datetime import date

from ml.common import charger_dataframe

HORIZON = 3  # mois de prévision publiés (1 à 3 mois, guide ML 3)

# Taux de fret pour le proxy de coût transport (FCFA par tonne et par km).
TAUX_FRET_FCFA_T_KM = 45.0
# Frais de mise en marché (commission, manutention, agréage) en % du CA export.
TAUX_FRAIS_PCT = 6.0


def _serie_prix(conn):
    return charger_dataframe(
        conn,
        """
        SELECT p.code_produit,
               p.produit_sk,
               date_trunc('month', d.date_complete)::date AS mois,
               avg(pm.prix_fcfa) AS prix_fcfa
          FROM dwh.fait_prix_marche pm
          JOIN dwh.dim_produit p ON p.produit_sk = pm.produit_sk
          JOIN dwh.dim_date    d ON d.date_sk = pm.date_sk
         WHERE NOT pm.est_supprime AND pm.prix_fcfa IS NOT NULL
         GROUP BY p.code_produit, p.produit_sk, 3
         ORDER BY p.code_produit, 3
        """,
    )


def _erreurs(obs, pred):
    import numpy as np

    o = np.asarray(obs, dtype=float)
    p = np.asarray(pred, dtype=float)
    mae = float(np.mean(np.abs(o - p)))
    rmse = float(np.sqrt(np.mean((o - p) ** 2)))
    mask = o != 0
    mape = float(np.mean(np.abs((o[mask] - p[mask]) / o[mask])) * 100.0) if mask.any() else None
    return round(mae, 2), round(rmse, 2), (round(mape, 3) if mape is not None else None)


def _ajuste_prevoit(serie, horizon):
    """Ajuste un ETS (tendance, saisonnalité si assez de points) et prévoit."""
    import numpy as np
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    y = np.asarray(serie, dtype=float)
    saison = 12 if len(y) >= 30 else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = ExponentialSmoothing(
                y, trend="add", seasonal="add" if saison else None,
                seasonal_periods=saison, initialization_method="estimated",
            ).fit(optimized=True)
            prev = np.asarray(model.forecast(horizon), dtype=float)
            resid_std = float(np.std(model.resid)) if len(model.resid) else 0.0
            return prev, resid_std, "ETS"
        except Exception:  # noqa: BLE001 — repli robuste.
            coef = np.polyfit(np.arange(len(y)), y, 1)
            x = np.arange(len(y), len(y) + horizon)
            prev = np.asarray(np.polyval(coef, x), dtype=float)
            resid = y - np.polyval(coef, np.arange(len(y)))
            return prev, float(np.std(resid)), "LINEAIRE"


def prevoir(conn) -> int:
    """Prévisions de prix par produit + métriques vs dernier prix observé."""
    df = _serie_prix(conn)
    if df.empty:
        return 0

    lignes = []
    n_metriques = 0
    for (code, produit_sk), grp in df.groupby(["code_produit", "produit_sk"]):
        grp = grp.sort_values("mois")
        valeurs = grp["prix_fcfa"].astype(float).tolist()
        if len(valeurs) < 12:
            continue

        # --- évaluation glissante : référence = dernier prix connu ---
        test_n = min(12, len(valeurs) // 4)
        train, test = valeurs[:-test_n], valeurs[-test_n:]
        pred, _, _ = _ajuste_prevoit(train, test_n)
        ref = [train[-1]] * test_n
        mae, rmse, mape = _erreurs(test, pred)
        mae_r, rmse_r, mape_r = _erreurs(test, ref)
        cible = code
        from ml.common import ecrire_metrique
        for nom, val, r in (("MAE", mae, mae_r), ("RMSE", rmse, rmse_r), ("MAPE", mape, mape_r)):
            ecrire_metrique(conn, "ETS_prix", cible, "test", nom, val, reference=r)
            n_metriques += 1

        # --- prévision publiée sur l'horizon ---
        pred, sigma, modele = _ajuste_prevoit(valeurs, HORIZON)
        dernier = grp["mois"].max()
        for i in range(HORIZON):
            date_cible = _plus_mois(dernier, i + 1)
            yhat = float(max(0.0, pred[i]))
            lignes.append((int(produit_sk), date_cible, round(yhat, 2),
                           round(max(0.0, yhat - 1.96 * sigma), 2),
                           round(yhat + 1.96 * sigma, 2), modele))

    if lignes:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO ml.prevision_prix
                       (produit_sk, date_cible, yhat, yhat_bas, yhat_haut, modele)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (produit_sk, date_cible, modele)
                   DO UPDATE SET yhat = EXCLUDED.yhat, yhat_bas = EXCLUDED.yhat_bas,
                                 yhat_haut = EXCLUDED.yhat_haut, calcule_le = now()""",
                lignes,
            )
    return len(lignes) + n_metriques


def _couts(conn):
    """Coûts unitaires filière (FCFA/kg) ramenés au tonnage de la chaîne.

    On raisonne en équivalent unitaire (par kg livré à la filière) pour rester
    cohérent malgré des échelles de génération différentes entre les faits :
    le tonnage de référence est celui des livraisons (poids net).
    """
    tonnage_kg = float(charger_dataframe(
        conn,
        "SELECT coalesce(sum(poids_net_kg), 0) AS v FROM dwh.fait_livraison "
        "WHERE NOT est_supprime").iloc[0, 0])
    if not tonnage_kg:
        return None

    achats = float(charger_dataframe(
        conn,
        "SELECT coalesce(sum(montant_fcfa), 0) AS v FROM dwh.fait_paiement "
        "WHERE NOT est_supprime AND statut = 'PAYE'").iloc[0, 0])
    intrants = float(charger_dataframe(
        conn,
        "SELECT coalesce(sum(cout_fcfa), 0) AS v FROM dwh.fait_intrants "
        "WHERE NOT est_supprime").iloc[0, 0])
    transport_t_km = float(charger_dataframe(
        conn,
        """SELECT coalesce(sum(distance_km * coalesce(poids_arrivee_kg, 0) / 1000.0), 0) AS v
             FROM dwh.fait_transport WHERE NOT est_supprime""").iloc[0, 0])
    transport = transport_t_km * TAUX_FRET_FCFA_T_KM

    return {
        "achats_par_kg": achats / tonnage_kg,
        "intrants_par_kg": intrants / tonnage_kg,
        "transport_par_kg": transport / tonnage_kg,
    }


def _prix_export(conn):
    """Prix d'export moyen CA/kg (FCFA par kg)."""
    return float(charger_dataframe(
        conn,
        """SELECT coalesce(sum(montant_fcfa) / nullif(sum(volume_t) * 1000.0, 0), 0) AS v
             FROM dwh.fait_export WHERE NOT est_supprime""").iloc[0, 0])


def _marge_pct(prix_kg, couts):
    """Marge = CA export − (achats + intrants + transport + frais), en % du CA."""
    if not prix_kg or not couts:
        return None, None
    frais = prix_kg * TAUX_FRAIS_PCT / 100.0
    marge_kg = prix_kg - (couts["achats_par_kg"] + couts["intrants_par_kg"]
                          + couts["transport_par_kg"] + frais)
    return round(100.0 * marge_kg / prix_kg, 2), round(marge_kg, 2)


def scenarios(conn) -> int:
    """Simule la marge filière sous plusieurs scénarios (prix, change, transport)."""
    import json

    prix_kg = _prix_export(conn)
    couts = _couts(conn)
    if not prix_kg or not couts:
        return 0

    # Le CA (prix export/kg) suit le prix mondial et le change ; le transport est
    # le seul coût piloté directement par un facteur.
    scenarios_def = [
        ("BASE", 1.00, 1.00, 1.00),
        ("PRIX_MONDE_MOINS_10", 0.90, 0.95, 1.00),
        ("PRIX_MONDE_PLUS_10", 1.10, 1.05, 1.00),
        ("TRANSPORT_PLUS_15", 1.00, 1.00, 1.15),
        ("TOUS_DEFAVORABLES", 0.90, 0.95, 1.15),
    ]

    lignes = []
    for nom, f_prix, f_change, f_transport in scenarios_def:
        prix_s = prix_kg * f_prix * f_change
        couts_s = dict(couts)
        couts_s["transport_par_kg"] = couts["transport_par_kg"] * f_transport
        marge_pct, marge_kg = _marge_pct(prix_s, couts_s)
        params = json.dumps({
            "facteur_prix_monde": f_prix, "facteur_change": f_change,
            "facteur_transport": f_transport,
            "prix_export_fcfa_kg": round(prix_s, 2),
            "achats_fcfa_kg": round(couts_s["achats_par_kg"], 2),
            "intrants_fcfa_kg": round(couts_s["intrants_par_kg"], 2),
            "transport_fcfa_kg": round(couts_s["transport_par_kg"], 2),
            "frais_pct": TAUX_FRAIS_PCT,
        }, ensure_ascii=False)
        # marge_fcfa exprimée par tonne exportée (base unitaire).
        lignes.append((nom, params, marge_pct, round(marge_kg * 1000.0, 2)))

    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO ml.scenario_marge (scenario, parametres, marge_pct, marge_fcfa)
               VALUES (%s, %s::jsonb, %s, %s)
               ON CONFLICT (scenario)
               DO UPDATE SET parametres = EXCLUDED.parametres,
                             marge_pct = EXCLUDED.marge_pct,
                             marge_fcfa = EXCLUDED.marge_fcfa, calcule_le = now()""",
            lignes,
        )
    return len(lignes)


def executer(conn) -> int:
    return prevoir(conn) + scenarios(conn)


def _plus_mois(date_obj, n):
    y, m = date_obj.year, date_obj.month
    m2 = m - 1 + n
    return date(y + m2 // 12, m2 % 12 + 1, 1)
