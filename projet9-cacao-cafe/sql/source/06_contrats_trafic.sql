-- =============================================================================
-- Base SOURCE — source XML (contrats d'achat) et source CSV (trafic portuaire).
-- Tables de CONSULTATION chargées depuis :
--   data/inbox/contrats/*.xml      (extraits XML + XSD de validation)
--   data/inbox/trafic/trafic_portuaire_YYYY-MM.csv
-- =============================================================================

-- Contrats (XML) — un fichier par contrat ; entités extraites à plat.
CREATE TABLE IF NOT EXISTS coop.contrat (
    contrat_id     VARCHAR(20) PRIMARY KEY,
    acheteur       VARCHAR(120),
    pays           VARCHAR(60),
    produit        VARCHAR(10),
    volume_t       NUMERIC(12,3),
    prix_fcfa_kg   NUMERIC(10,2),
    date_contrat   DATE,
    date_debut     DATE,
    date_fin       DATE,
    incoterm       VARCHAR(10),
    port_chargement VARCHAR(30),
    port_decharge  VARCHAR(60),
    statut         VARCHAR(12),   -- ACTIF, SUSPENDU, ANNULE
    avenant        SMALLINT DEFAULT 0,
    clauses        TEXT
);

-- Trafic portuaire (CSV mensuel) — mouvements de conteneurs / escales.
CREATE TABLE IF NOT EXISTS coop.trafic_port (
    escale_id      VARCHAR(24) PRIMARY KEY,
    port           VARCHAR(30),
    navire         VARCHAR(60),
    date_arrivee   TIMESTAMPTZ,
    date_depart    TIMESTAMPTZ,
    conteneurs     INTEGER,
    tonnage_t      NUMERIC(12,2),
    terminal       VARCHAR(60),
    statut         VARCHAR(15)   -- A_QUAI, EN_ATTENTE, CHARGE
);
CREATE INDEX IF NOT EXISTS ix_trafic_port ON coop.trafic_port (port);
CREATE INDEX IF NOT EXISTS ix_trafic_arrivee ON coop.trafic_port (date_arrivee);

-- Distributions d'intrants (source Excel .xlsx, feuille « Distributions »).
CREATE TABLE IF NOT EXISTS coop.intrant_distribution (
    distribution_id  VARCHAR(20) PRIMARY KEY,
    producteur_id    VARCHAR(20) NOT NULL,
    cooperative_id   VARCHAR(20) NOT NULL,
    date_distribution DATE,
    intrant_id       VARCHAR(10),
    quantite         INTEGER,
    unite            VARCHAR(15),
    cout_fcfa        BIGINT,
    campagne         VARCHAR(12)
);
CREATE INDEX IF NOT EXISTS ix_intrant_producteur ON coop.intrant_distribution (producteur_id);