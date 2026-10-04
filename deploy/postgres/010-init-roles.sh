#!/bin/sh
set -eu
: "${SSO_RUNTIME_PASSWORD:?Set an independent runtime password}"
: "${SSO_MIGRATOR_PASSWORD:?Set an independent migration password}"
psql --no-psqlrc --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --file /opt/sso-init-roles.sql
