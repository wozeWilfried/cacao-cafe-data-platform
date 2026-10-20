-- =============================================================================
-- ETL — schéma technique (journalisation, filigranes, rejets) et staging.
-- À exécuter une seule fois sur la base dwh (pg_dwh).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Journal des exécutions : une ligne par tâche ETL.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etl.run_log (
    run_id            BIGSERIAL PRIMARY KEY,
    dag_id            TEXT,
    task_id           TEXT,
    source_name       TEXT NOT NULL,
    mode              VARCHAR(8)  NOT NULL CHECK (mode IN ('FULL','INCR')),
    declencheur       VARCHAR(12) CHECK (declencheur IN ('PLANIFIE','FICHIER','EVENEMENT','MANUEL')),
    debut             TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin               TIMESTAMPTZ,
    statut            VARCHAR(10) NOT NULL DEFAULT 'RUNNING' CHECK (statut IN ('RUNNING','SUCCESS','FAILED')),
    lignes_lues       INT,
    lignes_inserees   INT,
    lignes_maj        INT,
    lignes_supprimees INT,
    lignes_rejetees   INT,
    watermark_avant   TEXT,
    watermark_apres   TEXT,
    message_erreur    TEXT
);
CREATE INDEX IF NOT EXISTS ix_run_log_source ON etl.run_log (source_name, debut DESC);

-- ---------------------------------------------------------------------------
-- Filigrane par source : dernière valeur traitée (updated_at, date, …).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etl.watermark (
    source_name     TEXT PRIMARY KEY,
    derniere_valeur TEXT NOT NULL,
    maj_le          TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Rejets : une ligne par enregistrement refusé, avec règle, clé et valeur.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etl.rejet (
    rejet_id      BIGSERIAL PRIMARY KEY,
    run_id        BIGINT REFERENCES etl.run_log,
    source_name   TEXT,
    cle_metier    TEXT,
    regle         VARCHAR(4),
    valeur_rejetee JSONB,
    cree_le       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_rejet_run ON etl.rejet (run_id);
CREATE INDEX IF NOT EXISTS ix_rejet_regle ON etl.rejet (regle);

-- ---------------------------------------------------------------------------
-- Fichiers traités : succès (archive) ou échec (quarantaine), par empreinte.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etl.fichier_traite (
    nom        TEXT PRIMARY KEY,
    hash_md5   CHAR(32),
    run_id     BIGINT,
    statut     VARCHAR(12) NOT NULL DEFAULT 'SUCCESS',   -- SUCCESS | QUARANTAINE
    traite_le  TIMESTAMPTZ DEFAULT now()
);

-- =============================================================================
-- STAGING — copie brute des sources, tracée par run_id et charge_le.
-- Les colonnes sont larges (TEXT) : aucune transformation à ce stade.
-- =============================================================================
CREATE TABLE IF NOT EXISTS stg.livraison (
    run_id         BIGINT,
    livraison_id   TEXT, producteur_id TEXT, cooperative_id TEXT, parcelle_id TEXT,
    produit        TEXT, date_livraison TEXT, poids_brut_kg TEXT, poids_net_kg TEXT,
    nb_sacs        TEXT, updated_at TEXT, charge_le TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.paiement (
    run_id       BIGINT,
    paiement_id  TEXT, livraison_id TEXT, producteur_id TEXT, operateur TEXT,
    montant_fcfa TEXT, frais_fcfa TEXT, statut TEXT, horodatage TEXT,
    charge_le    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.qualite (
    run_id       BIGINT,
    lot_id       TEXT, cooperative_id TEXT, date_reception TEXT, date_analyse TEXT,
    humidite_pct TEXT, nb_grains_comptes TEXT, grains_defectueux_pct TEXT,
    grade TEXT, decision TEXT, defaut_principal TEXT, observation TEXT,
    charge_le    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.transport (
    run_id      BIGINT,
    trajet_id   TEXT, cooperative_id TEXT, transporteur TEXT, camion TEXT,
    port TEXT, date_depart TEXT, date_arrivee TEXT, distance_km TEXT,
    nb_pings TEXT, pertes_kg TEXT, charge_le TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.contrat (
    run_id      BIGINT,
    contrat_id  TEXT, acheteur TEXT, pays TEXT, produit TEXT, volume_t TEXT,
    prix_fcfa_kg TEXT, date_contrat TEXT, date_debut TEXT, date_fin TEXT,
    incoterm TEXT, port_chargement TEXT, port_decharge TEXT, statut TEXT,
    avenant TEXT, clauses TEXT, charge_le TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.trafic_port (
    run_id        BIGINT,
    escale_id     TEXT, port TEXT, navire TEXT, date_arrivee TEXT, date_depart TEXT,
    conteneurs TEXT, tonnage_t TEXT, terminal TEXT, statut TEXT,
    charge_le     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.intrant (
    run_id            BIGINT,
    distribution_id   TEXT, producteur_id TEXT, cooperative_id TEXT,
    date_distribution TEXT, intrant_id TEXT, quantite TEXT, unite TEXT,
    cout_fcfa TEXT, campagne TEXT, charge_le TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.prix_marche (
    run_id    BIGINT,
    date_mois TEXT, produit TEXT, unite TEXT, prix TEXT,
    charge_le TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.faostat (
    run_id    BIGINT,
    pays TEXT, produit TEXT, element TEXT, annee TEXT, unite TEXT, valeur TEXT,
    charge_le TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.meteo (
    run_id    BIGINT,
    source TEXT, site TEXT, date_jour TEXT, temperature TEXT, pluie TEXT,
    charge_le TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.taux_change (
    run_id    BIGINT,
    date_jour TEXT, paire TEXT, taux TEXT,
    charge_le TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_stg_livraison_run ON stg.livraison (run_id);
CREATE INDEX IF NOT EXISTS ix_stg_paiement_run  ON stg.paiement (run_id);
CREATE INDEX IF NOT EXISTS ix_stg_qualite_run   ON stg.qualite (run_id);
