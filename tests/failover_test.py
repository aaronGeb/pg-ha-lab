#!/usr/bin/env python3
"""End-to-end failover test.

1. Wait for a healthy cluster (3 nodes, 1 sync standby, analytics subscription running).
2. Start the ledger writer through HAProxy and sample replication lag under load.
3. `docker kill` the current primary (hard crash, no graceful shutdown).
4. Measure: time to a new Patroni leader, time until HAProxy accepts writes, client-observed outage.
5. Keep writing, stop the writer, then assert:
     - every acknowledged transaction exists on the new primary (zero loss)
     - debits == credits (no half-applied transaction)
     - the analytics database converges to the same row count via logical replication
     - the killed node rejoins as a replica
Exit code 0 only if all assertions pass. Results land in results/latest.{json,md}.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time

import psycopg

import tests.cluster as cluster

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")


def sh(*cmd):
    return subprocess.run(
        cmd, check=True, capture_output=True, text=True
    ).stdout.strip()


def numeric_lag(members):
    vals = [m["lag"] for m in members if isinstance(m.get("lag"), (int, float))]
    return max(vals) if vals else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=50)
    ap.add_argument(
        "--warmup", type=float, default=15, help="seconds of load before the kill"
    )
    ap.add_argument(
        "--after", type=float, default=25, help="seconds of load after the kill"
    )
    ap.add_argument("--max-failover-seconds", type=float, default=60)
    ap.add_argument("--max-lag-bytes", type=float, default=16 * 1024 * 1024)
    args = ap.parse_args()

    os.makedirs(RESULTS, exist_ok=True)
    acked_file = os.path.join(RESULTS, "acked.log")
    summary_file = os.path.join(RESULTS, "writer_summary.json")
    checks, out = {}, {}

    print("[1/6] waiting for healthy cluster ...")
    out["time_to_ready_seconds"] = round(cluster.wait_ready(), 1)
    old = cluster.leader()
    old_tl = old["timeline"]
    out["old_leader"] = old["name"]
    print(f"      leader={old['name']} timeline={old_tl}")

    print("[2/6] starting writer and sampling lag ...")
    writer = subprocess.Popen(
        [
            sys.executable,
            os.path.join(ROOT, "workload", "writer.py"),
            "--rate",
            str(args.rate),
            "--acked-file",
            acked_file,
            "--summary-file",
            summary_file,
        ],
        cwd=ROOT,
    )
    max_lag = 0
    t_end = time.monotonic() + args.warmup
    while time.monotonic() < t_end:
        max_lag = max(max_lag, numeric_lag(cluster.members()))
        time.sleep(1)
    out["max_replica_lag_bytes_under_load"] = max_lag

    print(f"[3/6] killing primary {old['name']} (docker kill) ...")
    t_kill = time.monotonic()
    sh("docker", "kill", old["name"])

    new, _ = cluster.wait_until(
        lambda: cluster.leader(exclude=(old["name"],)), args.max_failover_seconds, 0.25
    )
    out["failover_seconds_new_leader"] = (
        round(time.monotonic() - t_kill, 2) if new else None
    )
    writable, _ = cluster.wait_until(
        cluster.primary_writable, args.max_failover_seconds, 0.25
    )
    out["failover_seconds_writes_resume"] = (
        round(time.monotonic() - t_kill, 2) if writable else None
    )
    print(
        f"      new leader after {out['failover_seconds_new_leader']}s, writes resume after {out['failover_seconds_writes_resume']}s"
    )

    print(f"[4/6] load continues for {args.after}s, then stop writer ...")
    time.sleep(args.after)
    writer.send_signal(signal.SIGTERM)
    writer.wait(timeout=30)
    wsum = json.load(open(summary_file))
    out["writer"] = wsum

    print("[5/6] verifying data ...")
    acked_ids = []
    for line in open(acked_file):
        acked_ids.extend(line.split())
    with psycopg.connect(cluster.PRIMARY_DSN, autocommit=True) as c:
        present = c.execute(
            "SELECT count(*) FROM ledger_entries WHERE entry_id = ANY(%s::uuid[])",
            (acked_ids,),
        ).fetchone()[0]
        balanced = c.execute(
            "SELECT COALESCE(sum(amount_cents) FILTER (WHERE direction='debit'),0) = "
            "COALESCE(sum(amount_cents) FILTER (WHERE direction='credit'),0) FROM ledger_entries"
        ).fetchone()[0]
        primary_rows = c.execute("SELECT count(*) FROM ledger_entries").fetchone()[0]
    new_leader = cluster.leader()
    out.update(
        acked_entries=len(acked_ids),
        acked_entries_found=present,
        primary_rows=primary_rows,
        new_leader=new_leader["name"],
        new_timeline=new_leader["timeline"],
    )

    def analytics_converged():
        with psycopg.connect(cluster.ANALYTICS_DSN, autocommit=True) as a:
            return (
                a.execute("SELECT count(*) FROM ledger_entries").fetchone()[0]
                == primary_rows
            )

    converged, secs = cluster.wait_until(lambda: _safe(analytics_converged), 90, 1)
    out["analytics_convergence_seconds"] = round(secs, 1) if converged else None

    print(f"[6/6] restarting {old['name']} and waiting for rejoin ...")
    sh("docker", "start", old["name"])

    def rejoined():
        for m in cluster.members():
            if (
                m["name"] == old["name"]
                and m["state"] in ("running", "streaming")
                and m["role"] in ("replica", "sync_standby")
            ):
                return True
        return False

    ok, secs = cluster.wait_until(rejoined, 180, 2)
    out["rejoin_seconds"] = round(secs, 1) if ok else None

    checks["new_leader_elected"] = new is not None and new["name"] != old["name"]
    checks["failover_within_limit"] = (
        out["failover_seconds_writes_resume"] is not None
        and out["failover_seconds_writes_resume"] <= args.max_failover_seconds
    )
    checks["timeline_incremented"] = new_leader["timeline"] > old_tl
    checks["zero_acknowledged_loss"] = present == len(acked_ids) and len(acked_ids) > 0
    checks["ledger_balanced"] = bool(balanced)
    checks["lag_bounded_under_load"] = max_lag <= args.max_lag_bytes
    checks["analytics_converged"] = bool(converged)
    checks["old_primary_rejoined_as_replica"] = bool(ok)
    out["checks"] = checks

    json.dump(out, open(os.path.join(RESULTS, "latest.json"), "w"), indent=2)
    with open(os.path.join(RESULTS, "latest.md"), "w") as f:
        f.write("| Metric | Value |\n|---|---|\n")
        for k, v in out.items():
            if k not in ("checks", "writer"):
                f.write(f"| {k} | {v} |\n")
        f.write(
            f"| client_max_outage_seconds | {wsum['max_client_outage_seconds']} |\n"
        )
        f.write(f"| acknowledged_transactions | {wsum['acked_transactions']} |\n\n")
        for k, v in checks.items():
            f.write(f"- {'PASS' if v else 'FAIL'}  {k}\n")

    print(json.dumps(out, indent=2))
    failed = [k for k, v in checks.items() if not v]
    if failed:
        print("FAILED:", ", ".join(failed))
        sys.exit(1)
    print("ALL CHECKS PASSED")


def _safe(fn):
    try:
        return fn()
    except Exception:
        return False


if __name__ == "__main__":
    main()
