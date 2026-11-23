#!/usr/bin/env bash
set -euo pipefail

: "${NODE_NAME:?NODE_NAME required}"
: "${CLUSTER_SCOPE:?CLUSTER_SCOPE required}"

mkdir -p /pgdata
chown postgres:postgres /pgdata
chmod 700 /pgdata

# Only substitute our own variables so nothing else in the template is touched.
envsubst '${NODE_NAME} ${CLUSTER_SCOPE} ${POSTGRES_PASSWORD} ${REPLICATOR_PASSWORD}' \
  < /etc/patroni.yml.tpl > /etc/patroni.yml
chown postgres:postgres /etc/patroni.yml

exec gosu postgres patroni /etc/patroni.yml
