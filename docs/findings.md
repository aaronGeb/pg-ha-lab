# Findings (steps 1-4, local Docker run)

Hard-crash failovers (`docker kill` of the leader under ~50 tx/s ledger load, synchronous replication):

| Killed | Acked transactions | Client outage (s) |
|---|---|---|
| pg3 | 1182 | 32.9 |
| pg1 | 1363 | 28.7 |
| pg2 | 1414 | 27.5 |
| pg3 | 1564 | 24.7 |

After each run the primary's row count equalled the previous count plus two entries per acknowledged transaction, so no acknowledged write was lost.

## Finding: CDC subscription hung after failover when routed through HAProxy

Twice, the logical replication apply worker got stuck in `LibPQWalReceiverConnect` after the leader was killed, and analytics stopped following the primary. No `cdc_user` session existed on the new primary, and HAProxy showed open sessions not attached to any server. The cause is not confirmed; one hypothesis is a connection accepted by HAProxy while no backend was available.

Manual workaround: `pg_terminate_backend(<worker pid>)`. The replacement worker caught up with no data loss.

Change: the subscription now connects to `host=pg1,pg2,pg3 ... target_session_attrs=read-write` instead of HAProxy. One kill test (pg3) afterwards ran clean; a repeat is still pending.

## Other notes
- Patroni's permanent logical slot `cdc_slot` survived every failover.
- Old leaders rejoined as replicas automatically.
