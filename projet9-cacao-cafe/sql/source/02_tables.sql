-- =============================================================================
-- Base SOURCE — schéma coop (simulation du SI des coopératives)
-- Table des livraisons (source Postgres) et journal de changements (CDC).
--
-- Les référentiels (coopératives, producteurs, parcelles) ne sont PAS des
-- tables ici : ils sont déposés en fichiers (CSV + GeoJSON) dans
-- data/inbox/referentiels par generate/referentiels.py, comme le prévoit le
-- guide (source « Parcelles et producteurs » au format GeoJSON).
--
-- Ce fichier est exécuté au premier démarrage du conteneur pg_source
-- (monté dans /docker-entrypoint-initdb.d). Pour le rejouer :
--   docker compose rm -sf pg_source && docker compose up -d pg_source
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS coop;

-- ----------------------------------------------------------------------------
-- Livraisons des coopératives (≈ 300 000 lignes à l'échelle 1.0)
-- Colonnes conformes au guide ; updated_at sert de filigrane d'extraction.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS coop.livraison (
    livraison_id    BIGSERIAL     PRIMARY KEY,
    producteur_id   VARCHAR(20)   NOT NULL,          -- clé métier (PROD-...)
    cooperative_id  VARCHAR(20)   NOT NULL,          -- clé métier (COOP-...)
    parcelle_id     VARCHAR(20),                     -- clé métier (PARC-...)
    produit         VARCHAR(10)   NOT NULL CHECK (produit IN ('CACAO', 'CAFE')),
    date_livraison  DATE          NOT NULL,
    poids_brut_kg   NUMERIC(10,2) NOT NULL CHECK (poids_brut_kg >= 0),
    poids_net_kg    NUMERIC(10,2) NOT NULL CHECK (poids_net_kg >= 0),
    nb_sacs         INTEGER       NOT NULL CHECK (nb_sacs >= 0),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- Index utiles à l'extraction incrémentale et aux jointures de l'ETL.
CREATE INDEX IF NOT EXISTS ix_livraison_updated_at ON coop.livraison (updated_at);
CREATE INDEX IF NOT EXISTS ix_livraison_producteur ON coop.livraison (producteur_id);
CREATE INDEX IF NOT EXISTS ix_livraison_cooperative ON coop.livraison (cooperative_id);
CREATE INDEX IF NOT EXISTS ix_livraison_date ON coop.livraison (date_livraison);

COMMENT ON TABLE coop.livraison IS
    'Livraisons de cacao/café par producteur (source opérationnelle simulée).';
COMMENT ON COLUMN coop.livraison.updated_at IS
    'Horodatage de dernière modification ; filigrane de l''extraction incrémentale.';

-- ----------------------------------------------------------------------------
-- Journal de changements (CDC) : alimenté par un déclencheur sur coop.livraison
-- (mécanisme C, ajouté à l'étape « déclenchement »). Permet de détecter les
-- suppressions, qu'une simple lecture par filigrane ne peut pas voir.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS coop.cdc_journal (
    cdc_id      BIGSERIAL   PRIMARY KEY,
    table_nom   TEXT        NOT NULL,
    operation   CHAR(1)     NOT NULL CHECK (operation IN ('I', 'U', 'D')),
    cle_metier  TEXT,
    horodatage  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_cdc_journal_horodatage ON coop.cdc_journal (horodatage);

COMMENT ON TABLE coop.cdc_journal IS
    'Journal des insertions/mises à jour/suppressions (change data capture).';
