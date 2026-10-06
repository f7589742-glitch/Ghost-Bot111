"""Shadow tenant worker (Phase 2 verification only).

Registers its PID + heartbeat in Supabase bot_instances every --interval
seconds. Performs ZERO game I/O: never touches accounts_fleet.json, never
opens sockets, never interferes with live sessions. Proves PID isolation,
per-tenant logs, and the heartbeat path before gradual cutover.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SERVER_NODE = os.environ.get("SERVER_NODE", "aws-ec2-primary-16-171-9-216")


def _req(method: str, path: str, body: dict | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        data=data,
        method=method,
        headers={
            "apikey": SERVICE_KEY,
            "Authorization": f"Bearer {SERVICE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation,resolution=merge-duplicates",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        text = res.read().decode()
        return json.loads(text) if text else []


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def register(tenant_id: str, instance_id: str) -> None:
    _req("POST", "bot_instances?on_conflict=id", {
        "id": instance_id,
        "user_id": tenant_id,
        "name": f"Shadow {instance_id}",
        "status": "shadow",
        "runtime_status": "shadow",
        "server_node": SERVER_NODE,
        "server_worker_id": str(os.getpid()),
        "last_heartbeat": now(),
    })


def heartbeat(instance_id: str) -> None:
    _req("PATCH", f"bot_instances?id=eq.{instance_id}", {
        "runtime_status": "shadow",
        "server_node": SERVER_NODE,
        "server_worker_id": str(os.getpid()),
        "last_heartbeat": now(),
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--instance-id", required=True)
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()
    if not SUPABASE_URL or not SERVICE_KEY:
        print("shadow: SUPABASE_URL / SUPABASE_SERVICE_KEY missing", flush=True)
        sys.exit(2)
    print(f"shadow: pid={os.getpid()} tenant={args.tenant_id} instance={args.instance_id}", flush=True)
    register(args.tenant_id, args.instance_id)
    print(f"shadow: registered, heartbeat every {args.interval}s", flush=True)
    while True:
        time.sleep(args.interval)
        try:
            heartbeat(args.instance_id)
            print(f"shadow: heartbeat {now()}", flush=True)
        except Exception as e:  # noqa: BLE001 - stay alive, retry next cycle
            print(f"shadow: heartbeat failed: {e}", flush=True)


if __name__ == "__main__":
    main()
