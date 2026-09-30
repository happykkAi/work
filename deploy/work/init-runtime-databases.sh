#!/bin/sh
set -eu

psql --set=ON_ERROR_STOP=1 \
  --set=work_role="$WORK_CONTROL_ROLE" \
  --set=work_database="$WORK_CONTROL_DB" \
  --set=work_password="$(cat /run/secrets/work_control_password)" \
  --set=octop_role="$OCTOP_RUNTIME_ROLE" \
  --set=octop_database="$OCTOP_RUNTIME_DB" \
  --set=octop_password="$(cat /run/secrets/octop_runtime_password)" \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE :"work_role" LOGIN PASSWORD :'work_password';
-- The Work login never owns the authoritative database/schema/tables.
-- Migrate with the separate owner, then run provision_control.py principal.
CREATE DATABASE :"work_database" OWNER CURRENT_USER;
CREATE ROLE :"octop_role" LOGIN PASSWORD :'octop_password';
CREATE DATABASE :"octop_database" OWNER :"octop_role";
SQL
