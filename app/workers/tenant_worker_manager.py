"""Spawn / stop / status isolated tenant workers (Phase 2).

Each instance runs as its own OS process bound to its tenant directory.
Stopping one PID never touches other tenants.

CLI:
  python -m app.workers.tenant_worker_manager spawn --tenant-id UUID --instance-id ID [--mode shadow]
  python -m app.workers.tenant_worker_manager stop --tenant-id UUID --instance-id ID
  python -m app.workers.tenant_worker_manager status --tenant-id UUID --instance-id ID
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys

from app.workers.tenant_layout import ensure_layout, log_file, pid_file

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, OverflowError):
        return False


def read_pid(user_uuid: str, instance_id: str) -> int | None:
    try:
        with open(pid_file(user_uuid, instance_id), encoding="utf-8") as f:
            pid = int(f.read().strip())
        return pid if _pid_alive(pid) else None
    except (OSError, ValueError):
        return None


def spawn(user_uuid: str, instance_id: str, mode: str = "shadow") -> dict:
    ensure_layout(user_uuid, instance_id)
    existing = read_pid(user_uuid, instance_id)
    if existing:
        return {"ok": True, "pid": existing, "note": "already running"}
    log = open(log_file(user_uuid, instance_id), "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", f"app.workers.{mode}_worker",
         "--tenant-id", user_uuid, "--instance-id", instance_id],
        cwd=APP_ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ},
    )
    with open(pid_file(user_uuid, instance_id), "w", encoding="utf-8") as f:
        f.write(str(proc.pid))
    return {"ok": True, "pid": proc.pid, "log": log_file(user_uuid, instance_id)}


def stop(user_uuid: str, instance_id: str) -> dict:
    pid = read_pid(user_uuid, instance_id)
    if not pid:
        try:
            os.remove(pid_file(user_uuid, instance_id))
        except OSError:
            pass
        return {"ok": True, "note": "not running"}
    os.kill(pid, signal.SIGTERM)
    try:
        os.remove(pid_file(user_uuid, instance_id))
    except OSError:
        pass
    return {"ok": True, "stopped_pid": pid}


def status(user_uuid: str, instance_id: str) -> dict:
    pid = read_pid(user_uuid, instance_id)
    return {"running": pid is not None, "pid": pid, "log": log_file(user_uuid, instance_id)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["spawn", "stop", "status"])
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--instance-id", required=True)
    ap.add_argument("--mode", default="shadow")
    args = ap.parse_args()
    if args.action == "spawn":
        print(json.dumps(spawn(args.tenant_id, args.instance_id, args.mode)))
    elif args.action == "stop":
        print(json.dumps(stop(args.tenant_id, args.instance_id)))
    else:
        print(json.dumps(status(args.tenant_id, args.instance_id)))


if __name__ == "__main__":
    main()
