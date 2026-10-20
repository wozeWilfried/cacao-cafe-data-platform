"""NLP 1 · Classification des observations de contrôle qualité par défaut.

Objectif  : transformer les remarques libres des analystes en types de défauts
            comptables (7 classes : 6 défauts + « aucun défaut »).
Données   : champ observation des contrôles qualité.
Méthode   : nettoyage (minuscules, accents), TF-IDF mots + paires de mots,
            régression logistique one-vs-rest.
Jeu       : ~3 000 observations pour l'entraînement, le reste pour l'évaluation.
Évaluation: F1 macro, rappel et précision par classe, matrice de confusion.
Sortie    : nlp.defaut_observation + ml.metrique_modele.
"""

from __future__ import annotations

import re
import unicodedata

from ml.common import charger_dataframe, ecrire_metrique

CLASSES = ["MOISISSURE", "GRAINS_ARDOISES", "INFESTATION", "HUMIDITE_ELEVEE",
           "ODEUR_FUMEE", "CORPS_ETRANGERS", "CONFORME"]
N_TRAIN = 3000
GRAINE = 42


def _nettoyer(texte: str) -> str:
    if not texte:
        return ""
    texte = texte.lower()
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[^a-z0-9%\s]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def _donnees(conn):
    df = charger_dataframe(
        conn,
        """
        SELECT fq.qualite_sk, fq.observation,
               coalesce(dd.code_defaut, 'CONFORME') AS defaut
          FROM dwh.fait_qualite_lot fq
          LEFT JOIN dwh.dim_defaut dd ON dd.defaut_sk = fq.defaut_sk
         WHERE NOT fq.est_supprime AND fq.observation IS NOT NULL
        """,
    )
    df["texte"] = df["observation"].map(_nettoyer)
    return df


def executer(conn) -> int:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report, f1_score
    from sklearn.pipeline import make_pipeline

    df = _donnees(conn)
    if df.empty:
        return 0

    # Découpage : échantillon d'entraînement fixe, reste = évaluation.
    train = df.sample(n=min(N_TRAIN, len(df)), random_state=GRAINE)
    test = df.drop(train.index)
    if test.empty or train["defaut"].nunique() < 2:
        return 0

    modele = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True),
        LogisticRegression(max_iter=1000, class_weight="balanced"),
    )
    modele.fit(train["texte"], train["defaut"])

    pred = modele.predict(test["texte"])
    classes = sorted(train["defaut"].unique())
    classes = [c for c in CLASSES if c in classes] + [c for c in classes if c not in CLASSES]

    f1_macro = round(float(f1_score(test["defaut"], pred, labels=classes,
                                    average="macro", zero_division=0)), 4)
    ecrire_metrique(conn, "TFIDF_defauts", "defaut", "test", "F1_MACRO", f1_macro)
    ecrits = 1

    rapport = classification_report(test["defaut"], pred, labels=classes,
                                    output_dict=True, zero_division=0)
    for c in classes:
        r = rapport.get(c, {})
        for nom, val in (("PRECISION", r.get("precision")), ("RAPPEL", r.get("recall")),
                         ("F1", r.get("f1-score"))):
            if val is not None:
                ecrire_metrique(conn, "TFIDF_defauts", c, "test", nom, round(float(val), 4))
                ecrits += 1
    ecrire_metrique(conn, "TFIDF_defauts", "defaut", "test", "N_TEST", int(len(test)))
    ecrire_metrique(conn, "TFIDF_defauts", "defaut", "train", "N_TRAIN", int(len(train)))
    ecrits += 2

    # Matrice de confusion globale (couple réel→prédit les plus fréquents).
    from sklearn.metrics import confusion_matrix
    import collections
    cm = confusion_matrix(test["defaut"], pred, labels=classes)
    for i, reel in enumerate(classes):
        for j, p in enumerate(classes):
            if cm[i, j] and reel != p:
                ecrire_metrique(conn, "TFIDF_defauts", f"{reel}->{p}", "test",
                                "CONFUSION", int(cm[i, j]))
                ecrits += 1

    # --- écriture des scores : une ligne par (lot, défaut prédit) avec proba ---
    probas = modele.predict_proba(test["texte"])
    classes_modele = list(modele.classes_)
    lignes = []
    seuil = 0.5
    for (sk, _), proba in zip(test[["qualite_sk", "texte"]].itertuples(index=False),
                              probas):
        for k, c in enumerate(classes_modele):
            if proba[k] >= seuil:
                lignes.append((int(sk), c, round(float(proba[k]), 4), "TFIDF_LOGREG"))
    if lignes:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO nlp.defaut_observation (lot_sk, defaut_code, proba, modele)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (lot_sk, defaut_code, modele)
                   DO UPDATE SET proba = EXCLUDED.proba, calcule_le = now()""",
                lignes,
            )
    return ecrits + len(lignes)
