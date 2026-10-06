"""Per-tenant filesystem layout helpers (Phase 2 tenant isolation).

/tenants/{user_uuid}/instances/{instance_id}/{fleet.json, config.json, worker.pid}
/tenants/{user_uuid}/logs/instance_{instance_id}.log
"""
from __future__ import annotations

import json
import os

BASE = os.environ.get("TENANTS_BASE", "/home/ubuntu/bot-backend/tenants")


def tenant_dir(user_uuid: str) -> str:
    return os.path.join(BASE, user_uuid)


def instance_dir(user_uuid: str, instance_id: str) -> str:
    return os.path.join(tenant_dir(user_uuid), "instances", instance_id)


def logs_dir(user_uuid: str) -> str:
    return os.path.join(tenant_dir(user_uuid), "logs")


def pid_file(user_uuid: str, instance_id: str) -> str:
    return os.path.join(instance_dir(user_uuid, instance_id), "worker.pid")


def log_file(user_uuid: str, instance_id: str) -> str:
    return os.path.join(logs_dir(user_uuid), f"instance_{instance_id}.log")


def ensure_layout(user_uuid: str, instance_id: str) -> dict:
    for p in (instance_dir(user_uuid, instance_id), logs_dir(user_uuid)):
        os.makedirs(p, exist_ok=True)
    for name in ("fleet.json", "config.json"):
        fp = os.path.join(instance_dir(user_uuid, instance_id), name)
        if not os.path.exists(fp):
            with open(fp, "w", encoding="utf-8") as f:
                json.dump({}, f)
    return {"instance": instance_dir(user_uuid, instance_id), "logs": logs_dir(user_uuid)}
