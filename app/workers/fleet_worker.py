"""Tenant-scoped fleet worker (Phase 2).

Resolves the tenant's fleet.json emails against the engine DB and runs one
cycle for the enabled characters only. Other tenants are never touched.

  --dry-run (default): resolve + print the execution plan. No sockets.
  --once: execute one live cycle. ARMED ONLY with FLEET_WORKER_LIVE=1 in the
    environment, otherwise it refuses — this is the pilot gate that prevents
    accidental double-login alongside the global scheduler.

CLI:
  python -m app.workers.fleet_worker --tenant-id UUID --instance-id ID [--dry-run]
  FLEET_WORKER_LIVE=1 python -m app.workers.fleet_worker --tenant-id UUID --instance-id ID --once
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid as uuid_mod

from app.workers.tenant_layout import ensure_layout, instance_dir


def load_plan(user_uuid: str, instance_id: str) -> dict:
    ensure_layout(user_uuid, instance_id)
    fp = os.path.join(instance_dir(user_uuid, instance_id), "fleet.json")
    try:
        with open(fp, encoding="utf-8") as f:
            emails = (json.load(f) or {}).get("emails", [])
    except Exception:
        emails = []
    from app.models import AccountDAO, CharacterDAO
    plan = {"tenant": user_uuid, "instance": instance_id, "characters": []}
    for email in emails:
        acc = next((a for a in AccountDAO.get_all(user_uuid)
                    if str(a.get("email", "")).lower() == str(email).lower()), None)
        if not acc:
            plan["characters"].append({"email": email, "error": "not in engine DB"})
            continue
        for c in CharacterDAO.get_by_account_id(acc["id"]):
            if c.get("enabled", 1) != 1:
                continue
            plan["characters"].append({
                "email": email,
                "role_id": str(c["role_id"]),
                "name": c.get("name"),
                "kingdom_id": c.get("kingdom_id"),
            })
    return plan


async def run_once(plan: dict) -> dict:
    from app.models import TaskLogDAO
    from app.services.socket_worker import GameSocketWorker
    try:
        from app.workers.shadow_worker import heartbeat
    except Exception:
        heartbeat = None
    done, failed = 0, []
    for ch in plan["characters"]:
        if "error" in ch:
            failed.append(ch)
            continue
        tid = f"task_{uuid_mod.uuid4().hex[:12]}"
        try:
            from app.models import CharacterDAO
            db_c = CharacterDAO.get_by_role_id(ch["role_id"], plan["tenant"])
            TaskLogDAO.create(task_id=tid, role_id=ch["role_id"],
                              task_type="sync_full", status="RUNNING",
                              details={}, character_id=db_c["id"] if db_c else None)
            await GameSocketWorker.run_character_task(tid, ch["role_id"], "sync_full", user_id=plan["tenant"])
            done += 1
        except Exception as e:  # noqa: BLE001
            failed.append({**ch, "error": str(e)})
        if heartbeat:
            try:
                heartbeat(plan["instance"])
            except Exception:
                pass
    return {"done": done, "failed": failed}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--instance-id", required=True)
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--once", action="store_true", default=False)
    args = ap.parse_args()
    plan = load_plan(args.tenant_id, args.instance_id)
    if args.once:
        if os.environ.get("FLEET_WORKER_LIVE") != "1":
            print("fleet_worker: --once refused (pilot gate: set FLEET_WORKER_LIVE=1). Plan was:")
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            sys.exit(3)
        args.dry_run = False
    if args.dry_run:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return
    print(json.dumps(asyncio.run(run_once(plan)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
