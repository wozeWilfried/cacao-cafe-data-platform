-- =============================================================================
-- Base SOURCE — sources PUBLIQUES (prix mondiaux, FAOSTAT, météo, change).
-- Tables de CONSULTATION chargées depuis data/inbox/public/*.csv.
-- =============================================================================

-- Prix des marchés mondiaux (World Bank Pink Sheet) : cacao, café arabica/robusta.
CREATE TABLE IF NOT EXISTS coop.prix_marche (
    date_mois  DATE        NOT NULL,
    produit    VARCHAR(20) NOT NULL,
    unite      VARCHAR(12),
    prix       NUMERIC(12,4),
    PRIMARY KEY (date_mois, produit)
);

-- Production / superficie / rendement cacao & café par pays (FAOSTAT).
CREATE TABLE IF NOT EXISTS coop.faostat_production (
    pays     VARCHAR(80) NOT NULL,
    produit  VARCHAR(30) NOT NULL,
    element  VARCHAR(30) NOT NULL,
    annee    SMALLINT    NOT NULL,
    unite    VARCHAR(12),
    valeur   NUMERIC(16,2),
    PRIMARY KEY (pays, produit, element, annee)
);

-- Météo journalière par station (NASA POWER et Open-Meteo réunis).
CREATE TABLE IF NOT EXISTS coop.meteo (
    source      VARCHAR(12) NOT NULL,   -- NASA | OPEN-METEO
    site        VARCHAR(40) NOT NULL,
    date_jour   DATE        NOT NULL,
    temperature NUMERIC(6,2),
    pluie       NUMERIC(8,2),
    PRIMARY KEY (source, site, date_jour)
);
CREATE INDEX IF NOT EXISTS ix_meteo_site ON coop.meteo (site);

-- Taux de change (Frankfurter/BCE + parité XAF).
CREATE TABLE IF NOT EXISTS coop.taux_change (
    date_jour DATE        NOT NULL,
    paire     VARCHAR(12) NOT NULL,
    taux      NUMERIC(16,6),
    PRIMARY KEY (date_jour, paire)
);