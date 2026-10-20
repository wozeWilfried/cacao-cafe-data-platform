#!/bin/sh
# Utilisateur lecture seule pour Metabase / Power BI (jamais les identifiants dwh)
set -e

psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<EOSQL
CREATE ROLE ${READONLY_USER} LOGIN PASSWORD '${READONLY_PASSWORD}';
GRANT USAGE ON SCHEMA stg, dwh, etl, ml, nlp TO ${READONLY_USER};
GRANT SELECT ON ALL TABLES IN SCHEMA stg, dwh, etl, ml, nlp TO ${READONLY_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA stg, dwh, etl, ml, nlp GRANT SELECT ON TABLES TO ${READONLY_USER};
EOSQL

echo "Utilisateur lecture seule ${READONLY_USER} créé."
