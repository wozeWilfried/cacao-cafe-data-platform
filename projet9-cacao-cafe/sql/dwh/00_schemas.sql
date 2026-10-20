-- Base ENTREPÔT : création des 5 schémas
--   stg : staging (copies brutes horodatées)
--   dwh : modèle décisionnel (dimensions + faits)
--   etl : pilotage (run_log, watermark, rejet, fichier_traite)
--   ml  : sorties Machine Learning
--   nlp : sorties traitement du langage

CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS dwh;
CREATE SCHEMA IF NOT EXISTS etl;
CREATE SCHEMA IF NOT EXISTS ml;
CREATE SCHEMA IF NOT EXISTS nlp;

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- md5/digest pour les hash_diff (SCD2)
