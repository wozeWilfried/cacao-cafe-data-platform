-- =============================================================================
-- SOURCE — Change Data Capture (mécanisme C).
-- Un déclencheur sur coop.livraison renseigne updated_at, journalise l'opération
-- (I/U/D) dans coop.cdc_journal et émet un pg_notify('livraison_changee', …).
-- Un écouteur Python peut alors déclencher l'ETL (declencheur = EVENEMENT).
--
-- BEFORE : on peut fixer NEW.updated_at avant écriture.
-- =============================================================================

CREATE OR REPLACE FUNCTION coop.journaliser_livraison() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO coop.cdc_journal (table_nom, operation, cle_metier)
        VALUES ('livraison', 'D', OLD.livraison_id);
        PERFORM pg_notify('livraison_changee', OLD.livraison_id::text);
        RETURN OLD;
    END IF;

    NEW.updated_at := now();
    INSERT INTO coop.cdc_journal (table_nom, operation, cle_metier)
    VALUES ('livraison', 'U', NEW.livraison_id::text);
    PERFORM pg_notify('livraison_changee', NEW.livraison_id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_livraison ON coop.livraison;
CREATE TRIGGER trg_livraison
    BEFORE UPDATE OR DELETE ON coop.livraison
    FOR EACH ROW EXECUTE FUNCTION coop.journaliser_livraison();

-- Sur INSERT, on journalise l'opération « I » sans toucher updated_at (le
-- générateur fournit un horodatage d'historique cohérent avec les campagnes).
CREATE OR REPLACE FUNCTION coop.journaliser_livraison_insert() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := COALESCE(NEW.updated_at, now());
    INSERT INTO coop.cdc_journal (table_nom, operation, cle_metier)
    VALUES ('livraison', 'I', NEW.livraison_id::text);
    PERFORM pg_notify('livraison_changee', NEW.livraison_id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_livraison_insert ON coop.livraison;
CREATE TRIGGER trg_livraison_insert
    BEFORE INSERT ON coop.livraison
    FOR EACH ROW EXECUTE FUNCTION coop.journaliser_livraison_insert();

COMMENT ON FUNCTION coop.journaliser_livraison() IS
    'CDC (UPDATE/DELETE) : fixe updated_at, journalise U/D et émet pg_notify.';
COMMENT ON FUNCTION coop.journaliser_livraison_insert() IS
    'CDC (INSERT) : journalise I et émet pg_notify, préserve updated_at fourni.';
