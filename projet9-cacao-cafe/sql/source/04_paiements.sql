-- =============================================================================
-- Base SOURCE — paiements Mobile Money / virements / espèces (source JSON)
-- Table de CONSULTATION chargée par generate/charger_referentiels.py à partir
-- des fichiers data/inbox/paiements/paiements_YYYY-MM-DD.json.
-- =============================================================================

CREATE TABLE IF NOT EXISTS coop.paiement (
    paiement_id   VARCHAR(20) PRIMARY KEY,
    livraison_id  BIGINT      NOT NULL,
    producteur_id VARCHAR(20) NOT NULL,
    operateur     VARCHAR(15) NOT NULL,   -- MTN_MOMO, ORANGE_MONEY, VIREMENT, ESPECES
    montant_fcfa  BIGINT      NOT NULL,
    frais_fcfa    BIGINT      NOT NULL DEFAULT 0,
    statut        VARCHAR(12) NOT NULL DEFAULT 'PAYE',
    horodatage    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_paiement_livraison ON coop.paiement (livraison_id);
CREATE INDEX IF NOT EXISTS ix_paiement_producteur ON coop.paiement (producteur_id);
CREATE INDEX IF NOT EXISTS ix_paiement_horodatage ON coop.paiement (horodatage);