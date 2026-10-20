-- =============================================================================
-- ENTREPÔT DWH — 9 tables de faits (constellation, dimensions conformes).
-- Chaque fait porte : clé de substitution, clé métier (upsert idempotent),
-- clés étrangères vers les dimensions, mesures, et traçabilité ETL.
-- =============================================================================
SET search_path = dwh, public;

-- 1 · Une livraison d'un producteur à une coopérative.
CREATE TABLE IF NOT EXISTS dwh.fait_livraison (
    livraison_sk   BIGSERIAL PRIMARY KEY,
    livraison_bk   VARCHAR(30) NOT NULL UNIQUE,
    date_sk        INT    NOT NULL REFERENCES dwh.dim_date,
    produit_sk     INT    REFERENCES dwh.dim_produit,
    cooperative_sk BIGINT REFERENCES dwh.dim_cooperative,
    producteur_sk  BIGINT REFERENCES dwh.dim_producteur,
    parcelle_sk    BIGINT REFERENCES dwh.dim_parcelle,
    geo_sk         INT    REFERENCES dwh.dim_geographie,
    poids_brut_kg  NUMERIC(10,2),
    poids_net_kg   NUMERIC(10,2),
    nb_sacs        INT,
    est_supprime   BOOLEAN NOT NULL DEFAULT FALSE,
    etl_run_id     BIGINT,
    maj_le         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_livraison_date ON dwh.fait_livraison (date_sk);
CREATE INDEX IF NOT EXISTS ix_livraison_coop ON dwh.fait_livraison (cooperative_sk);
CREATE INDEX IF NOT EXISTS ix_livraison_prod ON dwh.fait_livraison (producteur_sk);

-- 2 · Un paiement unitaire rattaché à une livraison.
CREATE TABLE IF NOT EXISTS dwh.fait_paiement (
    paiement_sk    BIGSERIAL PRIMARY KEY,
    paiement_bk    VARCHAR(30) NOT NULL UNIQUE,
    date_sk        INT    NOT NULL REFERENCES dwh.dim_date,
    canal_sk       INT    REFERENCES dwh.dim_canal,
    producteur_sk  BIGINT REFERENCES dwh.dim_producteur,
    cooperative_sk BIGINT REFERENCES dwh.dim_cooperative,
    montant_fcfa   BIGINT,
    frais_fcfa     BIGINT DEFAULT 0,
    delai_jours    INT,                             -- livraison → paiement
    statut         VARCHAR(12),
    est_supprime   BOOLEAN NOT NULL DEFAULT FALSE,
    etl_run_id     BIGINT,
    maj_le         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_paiement_date ON dwh.fait_paiement (date_sk);

-- 3 · Une analyse de lot (humidité, défauts, grade, décision).
CREATE TABLE IF NOT EXISTS dwh.fait_qualite_lot (
    qualite_sk     BIGSERIAL PRIMARY KEY,
    lot_bk         VARCHAR(30) NOT NULL UNIQUE,
    date_sk        INT    NOT NULL REFERENCES dwh.dim_date,
    cooperative_sk BIGINT REFERENCES dwh.dim_cooperative,
    produit_sk     INT    REFERENCES dwh.dim_produit,
    defaut_sk      INT    REFERENCES dwh.dim_defaut,
    humidite_pct   NUMERIC(5,2),
    grains_defectueux_pct NUMERIC(5,2),
    nb_grains_comptes INT,
    grade          VARCHAR(10),
    decision       VARCHAR(10),
    observation    TEXT,
    est_supprime   BOOLEAN NOT NULL DEFAULT FALSE,
    etl_run_id     BIGINT,
    maj_le         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_qualite_date ON dwh.fait_qualite_lot (date_sk);

-- 4 · Un trajet camion coopérative → port (pings GPS agrégés).
CREATE TABLE IF NOT EXISTS dwh.fait_transport (
    transport_sk      BIGSERIAL PRIMARY KEY,
    trajet_bk         VARCHAR(40) NOT NULL UNIQUE,
    date_sk           INT    NOT NULL REFERENCES dwh.dim_date,
    cooperative_sk    BIGINT REFERENCES dwh.dim_cooperative,
    transporteur_sk   INT    REFERENCES dwh.dim_transporteur,
    port_sk           INT    REFERENCES dwh.dim_port,
    distance_km       NUMERIC(10,2),
    duree_min         INT,
    nb_pings          INT,
    pertes_kg         NUMERIC(10,2),
    est_supprime      BOOLEAN NOT NULL DEFAULT FALSE,
    etl_run_id        BIGINT,
    maj_le            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_transport_date ON dwh.fait_transport (date_sk);

-- 5 · Une ligne de contrat expédiée (volume, prix, montant).
CREATE TABLE IF NOT EXISTS dwh.fait_export (
    export_sk       BIGSERIAL PRIMARY KEY,
    contrat_bk      VARCHAR(30) NOT NULL UNIQUE,
    date_sk         INT    NOT NULL REFERENCES dwh.dim_date,
    produit_sk      INT    REFERENCES dwh.dim_produit,
    acheteur_sk     INT    REFERENCES dwh.dim_acheteur,
    port_sk         INT    REFERENCES dwh.dim_port,
    volume_t        NUMERIC(12,3),
    prix_fcfa_kg    NUMERIC(10,2),
    montant_fcfa    NUMERIC(16,2),
    nb_conteneurs   INT,
    incoterm        VARCHAR(10),
    statut          VARCHAR(12),
    est_supprime    BOOLEAN NOT NULL DEFAULT FALSE,
    etl_run_id      BIGINT,
    maj_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_export_date ON dwh.fait_export (date_sk);

-- 6 · Un prix par jour, produit et source.
CREATE TABLE IF NOT EXISTS dwh.fait_prix_marche (
    prix_sk    BIGSERIAL PRIMARY KEY,
    prix_bk    VARCHAR(60) NOT NULL UNIQUE,        -- source|produit|date
    date_sk    INT    NOT NULL REFERENCES dwh.dim_date,
    produit_sk INT    REFERENCES dwh.dim_produit,
    source     VARCHAR(30),
    unite      VARCHAR(12),
    prix_usd   NUMERIC(12,4),
    prix_fcfa  NUMERIC(14,2),                      -- dérivé (taux du jour)
    est_supprime BOOLEAN NOT NULL DEFAULT FALSE,
    etl_run_id BIGINT,
    maj_le     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prix_date ON dwh.fait_prix_marche (date_sk);

-- 7 · Un jour et un site climatique.
CREATE TABLE IF NOT EXISTS dwh.fait_meteo (
    meteo_sk    BIGSERIAL PRIMARY KEY,
    meteo_bk    VARCHAR(60) NOT NULL UNIQUE,       -- source|site|date
    date_sk     INT    NOT NULL REFERENCES dwh.dim_date,
    geo_sk      INT    REFERENCES dwh.dim_geographie,
    source      VARCHAR(15),
    temperature NUMERIC(6,2),
    pluie_mm    NUMERIC(8,2),
    est_supprime BOOLEAN NOT NULL DEFAULT FALSE,
    etl_run_id  BIGINT,
    maj_le      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_meteo_date ON dwh.fait_meteo (date_sk);

-- 8 · Une distribution d'intrant à un producteur.
CREATE TABLE IF NOT EXISTS dwh.fait_intrants (
    intrant_fait_sk BIGSERIAL PRIMARY KEY,
    distribution_bk VARCHAR(30) NOT NULL UNIQUE,
    date_sk         INT    NOT NULL REFERENCES dwh.dim_date,
    producteur_sk   BIGINT REFERENCES dwh.dim_producteur,
    cooperative_sk  BIGINT REFERENCES dwh.dim_cooperative,
    intrant_sk      INT    REFERENCES dwh.dim_intrant,
    quantite        INT,
    cout_fcfa       BIGINT,
    campagne        VARCHAR(12),
    est_supprime    BOOLEAN NOT NULL DEFAULT FALSE,
    etl_run_id      BIGINT,
    maj_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_intrants_date ON dwh.fait_intrants (date_sk);

-- 9 · Un mouvement de conteneur ou une escale portuaire.
CREATE TABLE IF NOT EXISTS dwh.fait_trafic_port (
    trafic_sk     BIGSERIAL PRIMARY KEY,
    escale_bk     VARCHAR(40) NOT NULL UNIQUE,
    date_sk       INT    NOT NULL REFERENCES dwh.dim_date,
    port_sk       INT    REFERENCES dwh.dim_port,
    conteneurs    INT,
    tonnage_t     NUMERIC(12,2),
    attente_h     NUMERIC(8,2),                    -- attente à quai
    duree_h       NUMERIC(8,2),
    statut        VARCHAR(15),
    est_supprime  BOOLEAN NOT NULL DEFAULT FALSE,
    etl_run_id    BIGINT,
    maj_le        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_trafic_date ON dwh.fait_trafic_port (date_sk);
