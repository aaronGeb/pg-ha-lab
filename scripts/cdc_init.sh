#!/usr/bin/env bash
# One-shot: create the logical subscription on the analytics database.
# The slot (cdc_slot) already exists - Patroni created it as a permanent, failover-safe slot.
set -euo pipefail

# HAProxy is fine for a one-off readiness check ...
WAIT_CONN="host=haproxy port=5000 dbname=ledger user=cdc_user password=${CDC_PASSWORD} connect_timeout=5"
# ... but the long-lived subscription connects to the nodes directly and lets libpq pick the
# writable one. Through HAProxy the apply worker hung forever after a failover (see README).
SUB_CONN="host=pg1,pg2,pg3 port=5432,5432,5432 dbname=ledger user=cdc_user password=${CDC_PASSWORD} target_session_attrs=read-write connect_timeout=3"

echo "[cdc-init] waiting for primary + cdc_slot ..."
until psql "$WAIT_CONN" -Atc "SELECT 1 FROM pg_replication_slots WHERE slot_name = 'cdc_slot'" 2>/dev/null | grep -q 1; do
  sleep 3
done

export PGPASSWORD="${ANALYTICS_PASSWORD}"
if psql -h analytics -U postgres -d analytics -Atc "SELECT 1 FROM pg_subscription WHERE subname = 'ledger_sub'" | grep -q 1; then
  echo "[cdc-init] subscription already exists"
  exit 0
fi

psql -h analytics -U postgres -d analytics -v ON_ERROR_STOP=1 -c \
  "CREATE SUBSCRIPTION ledger_sub CONNECTION '${SUB_CONN}' PUBLICATION ledger_pub WITH (create_slot = false, slot_name = 'cdc_slot', copy_data = true)"
echo "[cdc-init] subscription created"
