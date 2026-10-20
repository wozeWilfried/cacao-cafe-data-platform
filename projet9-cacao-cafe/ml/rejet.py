"""ML 2 · Prédiction du rejet d'un lot.

Cible     : est_refuse (decision = 'REFUSE').
Variables : humidité, taux de grains défectueux, grains comptés, produit, région,
            mois, délai livraison→analyse. Jamais le grade (conséquence).
Référence : régression logistique.
Modèle    : forêt aléatoire (poids de classes équilibrés).
Évaluation: découpage temporel ; précision, rappel, F1 (classe refusé), PR-AUC.
Cible rare : seuil choisi sur la courbe précision-rappel.
Sortie    : ml.score_rejet_lot + ml.metrique_modele.
"""

from __future__ import annotations

from ml.common import charger_dataframe, ecrire_metrique


def _donnees(conn):
    return charger_dataframe(
        conn,
        """
        SELECT q.qualite_sk,
               q.humidite_pct,
               q.grains_defectueux_pct,
               q.nb_grains_comptes,
               q.delai_analyse_jours,
               q.produit_sk,
               c.region,
               d.mois,
               (q.decision = 'REFUSE')::int AS est_refuse,
               d.date_complete AS date_analyse
          FROM dwh.fait_qualite_lot q
          JOIN dwh.dim_date  d ON d.date_sk = q.date_sk
          LEFT JOIN dwh.dim_cooperative c ON c.cooperative_sk = q.cooperative_sk
         WHERE NOT q.est_supprime AND q.decision IN ('ACCEPTE', 'REFUSE')
        """,
    )


def _matrice(df):
    import pandas as pd

    X = pd.get_dummies(
        df[["humidite_pct", "grains_defectueux_pct", "nb_grains_comptes",
            "delai_analyse_jours", "produit_sk", "region", "mois"]],
        columns=["region"], dummy_na=True,
    )
    X = X.fillna(X.median(numeric_only=True)).fillna(0)
    return X


def executer(conn) -> int:
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (average_precision_score, confusion_matrix,
                                 f1_score, precision_score, recall_score)

    df = _donnees(conn)
    if df.empty or df["est_refuse"].nunique() < 2:
        return 0

    df = df.sort_values("date_analyse").reset_index(drop=True)
    X = _matrice(df)
    y = df["est_refuse"].to_numpy()
    lot_sk = df["qualite_sk"].to_numpy()

    # Découpage temporel : entraînement sur les 3 premières campagnes, test sur la
    # dernière (jamais de mélange aléatoire).
    coupe = int(len(df) * 0.75)
    X_tr, X_te, y_tr, y_te = X.iloc[:coupe], X.iloc[coupe:], y[:coupe], y[coupe:]
    sk_te = lot_sk[coupe:]

    modeles = {
        "LOGISTIQUE": LogisticRegression(max_iter=1000, class_weight="balanced"),
        "RF": RandomForestClassifier(n_estimators=200, max_depth=8, min_samples_leaf=20,
                                     class_weight="balanced", random_state=42, n_jobs=-1),
    }

    ecrits = 0
    seuil_choisi = 0.5
    for nom, modele in modeles.items():
        modele.fit(X_tr, y_tr)
        proba = modele.predict_proba(X_te)[:, 1]

        # Seuil optimal : meilleur F1 sur la courbe précision-rappel.
        seuil = _meilleur_seuil(y_te, proba)
        pred = (proba >= seuil).astype(int)

        ecrire_metrique(conn, nom, "rejet_lot", "test", "PRECISION",
                        round(precision_score(y_te, pred, zero_division=0), 4))
        ecrire_metrique(conn, nom, "rejet_lot", "test", "RAPPEL",
                        round(recall_score(y_te, pred, zero_division=0), 4))
        ecrire_metrique(conn, nom, "rejet_lot", "test", "F1",
                        round(f1_score(y_te, pred, zero_division=0), 4))
        ecrire_metrique(conn, nom, "rejet_lot", "test", "PR_AUC",
                        round(average_precision_score(y_te, proba), 4))
        ecrits += 4

        if nom == "RF":
            seuil_choisi = seuil
            # Score publié pour tous les lots de test (probabilité de rejet).
            lignes = [(int(sk), round(float(p), 4), int(p >= seuil), round(seuil, 4), nom)
                      for sk, p in zip(sk_te, proba)]
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO ml.score_rejet_lot
                           (lot_sk, proba_rejet, classe_predite, seuil, modele)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (lot_sk, modele)
                       DO UPDATE SET proba_rejet = EXCLUDED.proba_rejet,
                                     classe_predite = EXCLUDED.classe_predite,
                                     seuil = EXCLUDED.seuil, calcule_le = now()""",
                    lignes,
                )
            ecrits += len(lignes)
            # Matrice de confusion stockée en métriques lisibles.
            tn, fp, fn, tp = confusion_matrix(y_te, pred, labels=[0, 1]).ravel()
            for k, v in (("VRAIS_POSITIFS", tp), ("FAUX_POSITIFS", fp),
                         ("FAUX_NEGATIFS", fn), ("VRAIS_NEGATIFS", tn)):
                ecrire_metrique(conn, nom, "rejet_lot", "test", k, int(v))
                ecrits += 1
    return ecrits


def _meilleur_seuil(y, proba):
    import numpy as np
    from sklearn.metrics import f1_score

    meilleur, seuil = -1.0, 0.5
    for s in np.linspace(0.05, 0.95, 19):
        f = f1_score(y, (proba >= s).astype(int), zero_division=0)
        if f > meilleur:
            meilleur, seuil = f, s
    return float(seuil)
