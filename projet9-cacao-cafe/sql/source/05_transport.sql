-- =============================================================================
-- Base SOURCE — pings GPS de transport (source : logs texte).
-- Table de CONSULTATION chargée depuis data/inbox/transport/*.log.
-- Un « ping » = une ligne : horodatage, camion, lot, position, vitesse,
-- événement et notes d'incident. Les trajets se reconstituent au-dessus.
-- =============================================================================

CREATE TABLE IF NOT EXISTS coop.transport_ping (
    ping_id     BIGSERIAL   PRIMARY KEY,
    horodatage  TIMESTAMPTZ NOT NULL,
    camion_id   VARCHAR(12) NOT NULL,
    lot_id      VARCHAR(20),
    latitude    NUMERIC(9,6),
    longitude   NUMERIC(9,6),
    vitesse_kmh SMALLINT,
    evenement   VARCHAR(12),   -- DEPART, ARRET, ARRIVEE_PORT (+ FUMIGATION)
    poids_kg    NUMERIC(10,2),
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS ix_ping_camion ON coop.transport_ping (camion_id);
CREATE INDEX IF NOT EXISTS ix_ping_lot ON coop.transport_ping (lot_id);
CREATE INDEX IF NOT EXISTS ix_ping_horodatage ON coop.transport_ping (horodatage);