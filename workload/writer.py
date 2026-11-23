#!/usr/bin/env python3
"""Ledger load generator for the failover test.

Each logical transaction posts a balanced pair of entries (one debit, one credit) in a single
database transaction. The client-generated txn_id makes retries idempotent, so a commit whose
acknowledgement was lost during failover is safely re-sent.

A transaction is written to --acked-file ONLY after COMMIT returned successfully. The test then
checks that every acknowledged transaction exists on the new primary: that is the zero-data-loss claim.
"""
import argparse
import json
import os
import random
import signal
import time
import uuid

import psycopg

DEFAULT_DSN = (
    f"host=localhost port=15000 dbname=ledger user=app "
    f"password={os.getenv('APP_PASSWORD', 'app_pw')} connect_timeout=2 "
    f"options='-c statement_timeout=5000' keepalives=1 keepalives_idle=2 keepalives_interval=1 keepalives_count=2"
)

INSERT = (
    "INSERT INTO ledger_entries (entry_id, txn_id, account_id, direction, amount_cents) "
    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (entry_id) DO NOTHING"
)

stop = False


def _handle(signum, frame):
    global stop
    stop = True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", default=os.getenv("WRITER_DSN", DEFAULT_DSN))
    ap.add_argument("--rate", type=float, default=50.0, help="target transactions per second")
    ap.add_argument("--duration", type=float, default=0, help="seconds to run (0 = until SIGINT/SIGTERM)")
    ap.add_argument("--acked-file", default="results/acked.log")
    ap.add_argument("--summary-file", default="results/writer_summary.json")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    os.makedirs(os.path.dirname(args.acked_file) or ".", exist_ok=True)

    interval = 1.0 / args.rate
    started = time.monotonic()
    acked = errors = 0
    outages = []          # client-observed unavailability windows, in seconds
    outage_start = None
    conn = None

    with open(args.acked_file, "w", buffering=1) as acked_log:
        while not stop and (not args.duration or time.monotonic() - started < args.duration):
            loop_start = time.monotonic()
            txn_id = uuid.uuid4()
            debit_id, credit_id = uuid.uuid5(txn_id, "debit"), uuid.uuid5(txn_id, "credit")
            src, dst = random.sample(range(1, 101), 2)
            amount = random.randint(100, 50_000)

            # Retry the SAME txn_id until it is acknowledged (or we are told to stop).
            while not stop:
                try:
                    if conn is None or conn.closed:
                        conn = psycopg.connect(args.dsn)
                    with conn.transaction():
                        conn.execute(INSERT, (debit_id, txn_id, src, "debit", amount))
                        conn.execute(INSERT, (credit_id, txn_id, dst, "credit", amount))
                    acked_log.write(f"{debit_id} {credit_id}\n")
                    acked += 1
                    if outage_start is not None:
                        outages.append(round(time.monotonic() - outage_start, 3))
                        outage_start = None
                    break
                except (psycopg.Error, OSError):
                    errors += 1
                    if outage_start is None:
                        outage_start = loop_start
                    try:
                        if conn is not None:
                            conn.close()
                    except Exception:
                        pass
                    conn = None
                    time.sleep(0.2)

            sleep_for = interval - (time.monotonic() - loop_start)
            if sleep_for > 0:
                time.sleep(sleep_for)

    summary = {
        "acked_transactions": acked,
        "errors": errors,
        "outage_windows_seconds": outages,
        "max_client_outage_seconds": max(outages) if outages else 0.0,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    with open(args.summary_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
