#!/usr/bin/env bash
# Runs once, on the first primary only, right after initdb (before Patroni creates the
# permanent logical slot). Everything created here reaches replicas via physical replication.
set -euo pipefail

export PGHOST=/var/run/postgresql PGUSER=postgres

psql -v ON_ERROR_STOP=1 -d postgres <<SQL
CREATE ROLE app      LOGIN PASSWORD '${APP_PASSWORD}';
CREATE ROLE cdc_user LOGIN REPLICATION PASSWORD '${CDC_PASSWORD}';
CREATE ROLE exporter LOGIN PASSWORD '${EXPORTER_PASSWORD}';
GRANT pg_monitor TO exporter;
CREATE DATABASE ledger OWNER app;
SQL

psql -v ON_ERROR_STOP=1 -d ledger -f /sql/01_schema.sql
psql -v ON_ERROR_STOP=1 -d ledger -f /sql/02_seed.sql
psql -v ON_ERROR_STOP=1 -d ledger -f /sql/03_publication.sql
