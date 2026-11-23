#!/usr/bin/env python3
"""Helpers for talking to the lab cluster from the host.

CLI:  python tests/cluster.py wait|leader|status
"""
import json
import os
import sys
import time
import urllib.request

import psycopg

REST_PORTS = {"pg1": 8008, "pg2": 8009, "pg3": 8010}
APP_PW = os.getenv("APP_PASSWORD", "app_pw")
ANALYTICS_PW = os.getenv("ANALYTICS_PASSWORD", "analytics_pw")

PRIMARY_DSN = f"host=localhost port=5000 dbname=ledger user=app password={APP_PW} connect_timeout=2"
ANALYTICS_DSN = f"host=localhost port=5433 dbname=analytics user=postgres password={ANALYTICS_PW} connect_timeout=2"


def get_cluster(exclude=()):
    """Return Patroni's /cluster view from the first reachable node (None if none answer)."""
    for name, port in REST_PORTS.items():
        if name in exclude:
            continue
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/cluster", timeout=2) as r:
                return json.load(r)
        except Exception:
            continue
    return None


def members(exclude=()):
    c = get_cluster(exclude)
    return c["members"] if c else []


def leader(exclude=()):
    for m in members(exclude):
        if m.get("role") == "leader" and m.get("state") in ("running", "streaming"):
            return m
    return None


def primary_writable():
    """True when a real write succeeds through HAProxy port 5000."""
    try:
        with psycopg.connect(PRIMARY_DSN, autocommit=True) as c:
            if c.execute("SELECT pg_is_in_recovery()").fetchone()[0]:
                return False
            c.execute("CREATE TEMP TABLE _probe (x int)")
            return True
    except Exception:
        return False


def subscription_running():
    try:
        with psycopg.connect(ANALYTICS_DSN, autocommit=True) as c:
            return c.execute("SELECT count(*) FROM pg_stat_subscription WHERE subname='ledger_sub' AND pid IS NOT NULL").fetchone()[0] > 0
    except Exception:
        return False


def wait_until(fn, timeout, interval=0.5):
    """Poll fn() until truthy. Returns (result, elapsed_seconds) or (None, elapsed) on timeout."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        r = fn()
        if r:
            return r, time.monotonic() - t0
        time.sleep(interval)
    return None, time.monotonic() - t0


def cluster_ready():
    ms = members()
    running = [m for m in ms if m.get("state") in ("running", "streaming")]
    leaders = [m for m in running if m.get("role") == "leader"]
    sync = [m for m in running if m.get("role") == "sync_standby"]
    return len(running) == 3 and len(leaders) == 1 and len(sync) >= 1 and primary_writable() and subscription_running()


def wait_ready(timeout=300):
    ok, elapsed = wait_until(cluster_ready, timeout, interval=2)
    if not ok:
        raise SystemExit(f"cluster not ready after {timeout}s: {json.dumps(members(), indent=2)}")
    return elapsed


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "wait":
        print(f"cluster ready after {wait_ready():.0f}s")
    elif cmd == "leader":
        m = leader()
        if not m:
            raise SystemExit("no leader")
        print(m["name"])
    else:
        for m in members():
            print(f'{m["name"]:5} {m["role"]:13} {m["state"]:10} tl={m.get("timeline")} lag={m.get("lag")}')
