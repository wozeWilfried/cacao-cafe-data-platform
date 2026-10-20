-- =============================================================================
-- DWH — Sorties Machine Learning (schéma ml) et NLP (schéma nlp).
-- Chaque modèle écrit ses prédictions ET ses métriques d'évaluation, avec le
-- run_id de la tâche ETL qui les a produits (guide, section 09).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- ML 1 · Prévision des tonnages par région, produit et mois.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml.prevision_tonnage (
    prevision_id  BIGSERIAL PRIMARY KEY,
    region        VARCHAR(40) NOT NULL,
    produit_sk    INT NOT NULL REFERENCES dwh.dim_produit(produit_sk),
    mois_cible    DATE NOT NULL,
    yhat          NUMERIC(12,2) NOT NULL,
    yhat_bas      NUMERIC(12,2),
    yhat_haut     NUMERIC(12,2),
    modele        VARCHAR(40) NOT NULL,
    run_id        BIGINT,
    calcule_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (region, produit_sk, mois_cible, modele)
);

-- ---------------------------------------------------------------------------
-- Métriques communes à tous les modèles.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml.metrique_modele (
    metrique_id   BIGSERIAL PRIMARY KEY,
    modele        VARCHAR(40) NOT NULL,
    cible         VARCHAR(60) NOT NULL,
    jeu           VARCHAR(20) NOT NULL,          -- validation, test
    metrique      VARCHAR(20) NOT NULL,          -- MAPE, WAPE, F1, PR_AUC...
    valeur        NUMERIC(12,4),
    reference     NUMERIC(12,4),                 -- valeur de la référence simple
    run_id        BIGINT,
    calcule_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (modele, cible, jeu, metrique)
);

-- ---------------------------------------------------------------------------
-- ML 2 · Score de rejet d'un lot.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml.score_rejet_lot (
    lot_sk        BIGINT NOT NULL REFERENCES dwh.fait_qualite_lot(qualite_sk),
    proba_rejet   NUMERIC(6,4) NOT NULL,
    classe_predite SMALLINT NOT NULL,
    seuil         NUMERIC(6,4) NOT NULL,
    modele        VARCHAR(40) NOT NULL,
    run_id        BIGINT,
    calcule_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (lot_sk, modele)
);

-- ---------------------------------------------------------------------------
-- ML 3 · Prévision du prix mondial.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml.prevision_prix (
    prevision_id  BIGSERIAL PRIMARY KEY,
    produit_sk    INT NOT NULL REFERENCES dwh.dim_produit(produit_sk),
    date_cible    DATE NOT NULL,
    yhat          NUMERIC(12,2) NOT NULL,
    yhat_bas      NUMERIC(12,2),
    yhat_haut     NUMERIC(12,2),
    modele        VARCHAR(40) NOT NULL,
    run_id        BIGINT,
    calcule_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (produit_sk, date_cible, modele)
);

-- ---------------------------------------------------------------------------
-- ML 3 · Scénarios de marge selon les paramètres choisis.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml.scenario_marge (
    scenario_id   BIGSERIAL PRIMARY KEY,
    scenario      VARCHAR(40) NOT NULL,
    parametres    JSONB NOT NULL,
    marge_pct     NUMERIC(6,2) NOT NULL,
    marge_fcfa    NUMERIC(18,2),
    run_id        BIGINT,
    calcule_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scenario)
);

-- ---------------------------------------------------------------------------
-- NLP 1 · Classification des observations qualité par type de défaut.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nlp.defaut_observation (
    observation_id BIGSERIAL PRIMARY KEY,
    lot_sk        BIGINT NOT NULL REFERENCES dwh.fait_qualite_lot(qualite_sk),
    defaut_code   VARCHAR(30) NOT NULL,
    proba         NUMERIC(6,4) NOT NULL,
    modele        VARCHAR(40) NOT NULL,
    run_id        BIGINT,
    calcule_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (lot_sk, defaut_code, modele)
);

-- ---------------------------------------------------------------------------
-- NLP 2 · Extraction des clauses, dates et volumes des contrats.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nlp.contrat_extraction (
    extraction_id BIGSERIAL PRIMARY KEY,
    contrat_bk    VARCHAR(30) NOT NULL,
    entite        VARCHAR(30) NOT NULL,          -- volume, date, penalite, incoterm...
    valeur        TEXT,
    debut         INT,                           -- position dans le texte
    fin           INT,
    modele        VARCHAR(40) NOT NULL,
    run_id        BIGINT,
    calcule_le    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_contrat_extraction_bk ON nlp.contrat_extraction (contrat_bk);
