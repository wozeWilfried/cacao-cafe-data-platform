-- =============================================================================
-- Base SOURCE — tables de CONSULTATION des données par fichiers
-- (coopératives CSV, producteurs+parcelles GeoJSON, contrôles qualité JSON)
--
-- Attention : la source OFFICIELLE reste les fichiers déposés dans
-- data/inbox (c'est ce que lit l'ETL, comme le prévoit le guide). Ces tables
-- sont chargées par generate/charger_referentiels.py afin de pouvoir interroger
-- et contrôler les données directement en SQL. Elles ne font pas partie du SI
-- simulé.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS coop;

-- Coopératives (depuis cooperatives_<date>.csv)
CREATE TABLE IF NOT EXISTS coop.cooperative (
    cooperative_id      VARCHAR(20) PRIMARY KEY,
    nom                 VARCHAR(120) NOT NULL,
    region              VARCHAR(30)  NOT NULL,
    departement         VARCHAR(60),
    ville               VARCHAR(60),
    latitude            NUMERIC(9,6),
    longitude           NUMERIC(9,6),
    capacite_stockage_t INTEGER,
    responsable         VARCHAR(120),
    certification       VARCHAR(40),
    statut              VARCHAR(15),
    date_creation       DATE,
    nb_adherents        INTEGER,
    maj_le              TIMESTAMPTZ
);

-- Producteurs (depuis producteurs_parcelles_<date>.geojson)
CREATE TABLE IF NOT EXISTS coop.producteur (
    producteur_id   VARCHAR(20) PRIMARY KEY,
    cooperative_id  VARCHAR(20) NOT NULL,
    nom             VARCHAR(120) NOT NULL,
    sexe            CHAR(1),
    annee_naissance SMALLINT,
    culture         VARCHAR(10),
    region          VARCHAR(30),
    certification   VARCHAR(40),
    statut          VARCHAR(15),
    maj_le          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_producteur_cooperative ON coop.producteur (cooperative_id);

-- Parcelles (une entité GeoJSON = une parcelle)
CREATE TABLE IF NOT EXISTS coop.parcelle (
    parcelle_id      VARCHAR(20) PRIMARY KEY,
    producteur_id    VARCHAR(20) NOT NULL,
    cooperative_id   VARCHAR(20) NOT NULL,
    culture          VARCHAR(10),
    variete          VARCHAR(30),
    surface_ha       NUMERIC(8,2),
    annee_plantation SMALLINT,
    certification    VARCHAR(40),
    region           VARCHAR(30),
    statut           VARCHAR(15),
    maj_le           TIMESTAMPTZ,
    geometry         JSONB                -- géométrie GeoJSON (polygone)
);
CREATE INDEX IF NOT EXISTS ix_parcelle_producteur ON coop.parcelle (producteur_id);

-- Contrôles qualité (depuis controles_qualite_YYYY-MM.json)
CREATE TABLE IF NOT EXISTS coop.lot_qualite (
    lot_id               VARCHAR(20) PRIMARY KEY,
    cooperative_id       VARCHAR(20) NOT NULL,
    date_reception       DATE,
    date_analyse         DATE,
    humidite_pct         NUMERIC(5,2),
    nb_grains_comptes    INTEGER,
    grains_defectueux_pct NUMERIC(5,2),
    grade                VARCHAR(10),
    decision             VARCHAR(10),
    defaut_principal     VARCHAR(20),
    observation          TEXT
);
CREATE INDEX IF NOT EXISTS ix_qualite_analyse ON coop.lot_qualite (date_analyse);
CREATE INDEX IF NOT EXISTS ix_qualite_cooperative ON coop.lot_qualite (cooperative_id);