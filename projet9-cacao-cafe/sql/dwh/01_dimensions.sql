-- =============================================================================
-- ENTREPÔT DWH — Dimensions conformes (constellation)
-- Dim 0 : dim_date (générée). Les dimensions Type 1 et SCD2 suivent.
-- =============================================================================
SET search_path = dwh, public;

-- ---------------------------------------------------------------------------
-- dim_date — calendrier 2000→2030, campagne commerciale octobre→septembre.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_date (
    date_sk       INT          PRIMARY KEY,      -- YYYYMMDD
    date_complete DATE         NOT NULL UNIQUE,
    annee         SMALLINT     NOT NULL,
    mois          SMALLINT     NOT NULL,
    nom_mois      VARCHAR(12)  NOT NULL,
    trimestre     SMALLINT     NOT NULL,
    jour_semaine  SMALLINT     NOT NULL,          -- isodow 1=lundi
    nom_jour      VARCHAR(12)  NOT NULL,
    campagne      VARCHAR(9)   NOT NULL,          -- ex. « 2022/2023 »
    est_weekend   BOOLEAN      NOT NULL
);

INSERT INTO dwh.dim_date
    (date_sk, date_complete, annee, mois, nom_mois, trimestre,
     jour_semaine, nom_jour, campagne, est_weekend)
SELECT
    to_char(d, 'YYYYMMDD')::int,
    d::date,
    EXTRACT(year  FROM d)::smallint,
    EXTRACT(month FROM d)::smallint,
    to_char(d, 'TMMonth'),
    EXTRACT(quarter FROM d)::smallint,
    EXTRACT(isodow FROM d)::smallint,
    to_char(d, 'TMDay'),
    CASE WHEN EXTRACT(month FROM d) >= 10
         THEN EXTRACT(year FROM d)::int || '/' || (EXTRACT(year FROM d)::int + 1)
         ELSE (EXTRACT(year FROM d)::int - 1) || '/' || EXTRACT(year FROM d)::int
    END,
    EXTRACT(isodow FROM d) >= 6
FROM generate_series('2000-01-01'::date, '2030-12-31'::date, interval '1 day') AS g(d)
ON CONFLICT (date_sk) DO NOTHING;

-- ---------------------------------------------------------------------------
-- dim_produit — Type 1. CACAO / CAFE, variété et famille.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_produit (
    produit_sk   SERIAL       PRIMARY KEY,
    code_produit VARCHAR(10)  NOT NULL UNIQUE,   -- CACAO, CAFE
    libelle      VARCHAR(40)  NOT NULL,
    famille      VARCHAR(20),                    -- fève, café vert
    variete      VARCHAR(30)                     -- arabica, robusta (café)
);

-- ---------------------------------------------------------------------------
-- dim_geographie — Type 1. Localité → région, station météo, coordonnées.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_geographie (
    geo_sk        SERIAL      PRIMARY KEY,
    code_localite VARCHAR(30) NOT NULL UNIQUE,
    localite      VARCHAR(60),
    departement   VARCHAR(60),
    region        VARCHAR(30),
    pays          VARCHAR(40) DEFAULT 'Cameroun',
    latitude      NUMERIC(9,6),
    longitude     NUMERIC(9,6),
    station_meteo VARCHAR(40)
);

-- ---------------------------------------------------------------------------
-- dim_cooperative — SCD type 2.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_cooperative (
    cooperative_sk     BIGSERIAL PRIMARY KEY,
    cooperative_bk     VARCHAR(20) NOT NULL,
    nom                VARCHAR(120),
    region             VARCHAR(30),
    departement        VARCHAR(60),
    ville              VARCHAR(60),
    capacite_stockage_t INT,
    responsable        VARCHAR(120),
    certification      VARCHAR(40),
    statut             VARCHAR(15) NOT NULL DEFAULT 'ACTIF',
    hash_diff          CHAR(32)    NOT NULL,
    date_debut         DATE        NOT NULL,
    date_fin           DATE        NOT NULL DEFAULT '9999-12-31',
    est_courant        BOOLEAN     NOT NULL DEFAULT TRUE
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_cooperative_courant
    ON dwh.dim_cooperative (cooperative_bk) WHERE est_courant;

-- ---------------------------------------------------------------------------
-- dim_producteur — SCD type 2 (cf. guide).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_producteur (
    producteur_sk   BIGSERIAL PRIMARY KEY,
    producteur_bk   VARCHAR(20)  NOT NULL,
    nom             VARCHAR(120),
    sexe            CHAR(1),
    annee_naissance SMALLINT,
    cooperative_bk  VARCHAR(20),
    culture         VARCHAR(10),
    region          VARCHAR(30),
    certification   VARCHAR(40),
    statut          VARCHAR(15)  NOT NULL DEFAULT 'ACTIF',
    hash_diff       CHAR(32)     NOT NULL,
    date_debut      DATE         NOT NULL,
    date_fin        DATE         NOT NULL DEFAULT '9999-12-31',
    est_courant     BOOLEAN      NOT NULL DEFAULT TRUE
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_producteur_courant
    ON dwh.dim_producteur (producteur_bk) WHERE est_courant;

-- ---------------------------------------------------------------------------
-- dim_parcelle — Type 1. Surface, culture, géométrie.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_parcelle (
    parcelle_sk      BIGSERIAL PRIMARY KEY,
    parcelle_bk      VARCHAR(20) NOT NULL UNIQUE,
    producteur_bk    VARCHAR(20),
    cooperative_bk   VARCHAR(20),
    culture          VARCHAR(10),
    variete          VARCHAR(30),
    surface_ha       NUMERIC(8,2),
    annee_plantation SMALLINT,
    certification    VARCHAR(40),
    region           VARCHAR(30),
    geometry         JSONB
);

-- ---------------------------------------------------------------------------
-- dim_canal — Type 1. Canaux de paiement mobile/cash.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_canal (
    canal_sk  SERIAL      PRIMARY KEY,
    code_canal VARCHAR(20) NOT NULL UNIQUE,      -- MTN_MOMO, ORANGE_MONEY...
    libelle    VARCHAR(60),
    famille    VARCHAR(20)                        -- mobile_money, banque, especes
);

-- ---------------------------------------------------------------------------
-- dim_acheteur — Type 1. Négociant / torréfacteur.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_acheteur (
    acheteur_sk   SERIAL      PRIMARY KEY,
    acheteur_bk   VARCHAR(60) NOT NULL UNIQUE,    -- raison sociale
    raison_sociale VARCHAR(120),
    pays          VARCHAR(60),
    type_acheteur VARCHAR(30)                      -- negociant, torrefacteur
);

-- ---------------------------------------------------------------------------
-- dim_transporteur — Type 1. Société, camion, capacité.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_transporteur (
    transporteur_sk    SERIAL      PRIMARY KEY,
    transporteur_bk    VARCHAR(40) NOT NULL UNIQUE,
    societe            VARCHAR(120),
    camion             VARCHAR(40),
    capacite_t         NUMERIC(8,2)
);

-- ---------------------------------------------------------------------------
-- dim_port — Type 1. Douala, Kribi, terminal.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_port (
    port_sk   SERIAL      PRIMARY KEY,
    code_port VARCHAR(20) NOT NULL UNIQUE,
    nom       VARCHAR(60),
    terminal  VARCHAR(60),
    pays      VARCHAR(40) DEFAULT 'Cameroun'
);

-- ---------------------------------------------------------------------------
-- dim_defaut — Type 1. Défauts qualité identifiés au contrôle.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_defaut (
    defaut_sk   SERIAL      PRIMARY KEY,
    code_defaut VARCHAR(30) NOT NULL UNIQUE,
    libelle     VARCHAR(80),
    famille     VARCHAR(30),                     -- champignon, insecte, matière...
    gravite     VARCHAR(10)                      -- MAJEUR, MINEUR
);

-- ---------------------------------------------------------------------------
-- dim_intrant — Type 1. Famille, nom, unité.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwh.dim_intrant (
    intrant_sk  SERIAL      PRIMARY KEY,
    code_intrant VARCHAR(20) NOT NULL UNIQUE,
    nom         VARCHAR(80),
    famille     VARCHAR(30),
    unite       VARCHAR(15)
);
