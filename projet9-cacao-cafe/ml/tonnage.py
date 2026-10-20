"""ML 1 · Prévision des tonnages mensuels par région et produit.

Objectif  : anticiper les tonnages par région pour planifier collecte et transport.
Référence : valeur du même mois un an plus tôt (saisonnière naïve).
Modèle    : lissage exponentiel saisonnier (statsmodels ETS) par série
            région × produit.
Évaluation: validation à origine glissante ; MAPE, WAPE et gain vs référence.
Sortie    : ml.prevision_tonnage + ml.metrique_modele.
"""

from __future__ import annotations

import warnings
from datetime import date

from ml.common import execute, charger_dataframe, ecrire_metrique

HORIZON = 6  # mois de prévision publiés


def _serie(conn):
    return charger_dataframe(
        conn,
        """
        SELECT c.region,
               p.code_produit,
               date_trunc('month', d.date_complete)::date AS mois,
               sum(l.poids_net_kg) / 1000.0 AS tonnage_t
          FROM dwh.fait_livraison l
          JOIN dwh.dim_cooperative c ON c.cooperative_sk = l.cooperative_sk
          JOIN dwh.dim_produit     p ON p.produit_sk = l.produit_sk
          JOIN dwh.dim_date        d ON d.date_sk = l.date_sk
         WHERE NOT l.est_supprime
         GROUP BY c.region, p.code_produit, 3
         ORDER BY c.region, p.code_produit, 3
        """,
    )


def _mape(obs, pred):
    obs = [o for o in obs if o]
    if not obs:
        return None
    import statistics
    erreurs = [abs((o - p) / o) for o, p in zip(obs, pred) if o]
    return round(100.0 * statistics.mean(erreurs), 3) if erreurs else None


def _wape(obs, pred):
    denom = sum(abs(o) for o in obs)
    if not denom:
        return None
    return round(100.0 * sum(abs(o - p) for o, p in zip(obs, pred)) / denom, 3)


def _ajuste_prevoit(serie, horizon):
    """Ajuste un ETS additif saisonnier (période 12) et prévoit `horizon` mois."""
    import numpy as np
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    y = np.asarray(serie, dtype=float)
    saison = 12 if len(y) >= 24 else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = ExponentialSmoothing(
                y, trend="add", seasonal="add" if saison else None,
                seasonal_periods=saison, initialization_method="estimated",
            ).fit(optimized=True)
            prev = model.forecast(horizon)
            resid_std = float(np.std(model.resid)) if len(model.resid) else 0.0
            return np.asarray(prev, dtype=float), resid_std, "ETS"
        except Exception:  # noqa: BLE001 — repli robuste.
            # Repli : tendance linéaire simple.
            x = np.arange(len(y))
            coef = np.polyfit(x, y, 1)
            prev = np.polyval(coef, np.arange(len(y), len(y) + horizon))
            return np.asarray(prev, dtype=float), float(np.std(y - np.polyval(coef, x))), "LINEAIRE"


def executer(conn) -> int:
    """Calcule et persiste les prévisions + métriques. Retourne le nombre d'écrits."""
    df = _serie(conn)
    if df.empty:
        return 0

    lignes = []
    n_metriques = 0
    seuil_histo_min = 18  # au moins 18 mois pour évaluer proprement

    for (region, produit), grp in df.groupby(["region", "code_produit"]):
        grp = grp.sort_values("mois")
        valeurs = grp["tonnage_t"].astype(float).tolist()
        if len(valeurs) < 6:
            continue

        # --- évaluation à origine glissante (dernier points en test) ---
        if len(valeurs) >= seuil_histo_min:
            test_n = min(6, len(valeurs) // 4)
            train, test = valeurs[:-test_n], valeurs[-test_n:]
            pred, _, _ = _ajuste_prevoit(train, test_n)
            ref = [_valeur_an_dernier(train, i, test_n) for i in range(test_n)]
            n_metriques += 1
            _ref_val = _mape(test, ref)
            ecrire_metrique(conn, "ETS_tonnage", f"{region}/{produit}", "test", "MAPE",
                            _mape(test, pred), reference=_ref_val)
            ecrire_metrique(conn, "ETS_tonnage", f"{region}/{produit}", "test", "WAPE",
                            _wape(test, pred), reference=_wape(test, ref))
            if _ref_val and _mape(test, pred):
                gain = round(100.0 * (_ref_val - _mape(test, pred)) / _ref_val, 2)
                ecrire_metrique(conn, "ETS_tonnage", f"{region}/{produit}", "test",
                                "GAIN_MAPE_PCT", gain, reference=0.0)

        # --- prévision publiée sur l'horizon ---
        pred, sigma, nom = _ajuste_prevoit(valeurs, HORIZON)
        produit_sk = int(charger_dataframe(
            conn, "SELECT produit_sk FROM dwh.dim_produit WHERE code_produit = %s",
            (produit,)).iloc[0, 0])
        dernier_mois = grp["mois"].max()
        for i in range(HORIZON):
            mois_cible = _plus_mois(dernier_mois, i + 1)
            yhat = float(max(0.0, pred[i]))
            lignes.append((region, produit_sk, mois_cible, round(yhat, 2),
                           round(max(0.0, yhat - 1.96 * sigma), 2),
                           round(yhat + 1.96 * sigma, 2), nom))

    if lignes:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO ml.prevision_tonnage
                       (region, produit_sk, mois_cible, yhat, yhat_bas, yhat_haut, modele)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (region, produit_sk, mois_cible, modele)
                   DO UPDATE SET yhat = EXCLUDED.yhat, yhat_bas = EXCLUDED.yhat_bas,
                                 yhat_haut = EXCLUDED.yhat_haut, calcule_le = now()""",
                lignes,
            )
    return len(lignes) + n_metriques


def _valeur_an_dernier(train, i, test_n):
    """Référence saisonnière naïve : le même mois l'année précédente."""
    k = len(train) - 12 + i
    return train[k] if 0 <= k < len(train) else train[-1]


def _plus_mois(date_obj, n):
    y, m = date_obj.year, date_obj.month
    m2 = m - 1 + n
    return date(y + m2 // 12, m2 % 12 + 1, 1)
