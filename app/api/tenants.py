"""Tenant workspace endpoints (Phase 2 production wiring).

Filesystem + config bookkeeping only — no game I/O, no socket work.
Mounted behind the same stealth + API-key gate as the main router.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.workers.tenant_layout import ensure_layout, instance_dir

router = APIRouter(prefix="/api/tenants", tags=["tenants"])

UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")
INST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,64}$")


def _check(user_uuid: str, instance_id: str) -> None:
    if not UUID_RE.match(user_uuid or ""):
        raise HTTPException(status_code=400, detail="bad tenant id")
    if not INST_RE.match(instance_id or ""):
        raise HTTPException(status_code=400, detail="bad instance id")


class EnsureBody(BaseModel):
    user_uuid: str
    slots: int = 5
    defaults: Dict[str, Any] = {}


class FleetBody(BaseModel):
    user_uuid: str
    emails: List[str] = []


class ConfigBody(BaseModel):
    user_uuid: str
    settings: Dict[str, Any] = {}


@router.post("/{instance_id}/ensure")
def ensure_workspace(instance_id: str, body: EnsureBody):
    """Create the isolated tenant workspace on purchase (dirs + fleet/config)."""
    _check(body.user_uuid, instance_id)
    lay = ensure_layout(body.user_uuid, instance_id)
    cfg_path = os.path.join(instance_dir(body.user_uuid, instance_id), "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"slots": body.slots, "defaults": body.defaults}, f)
    return {"success": True, **lay}


@router.post("/{instance_id}/fleet")
def write_fleet(instance_id: str, body: FleetBody):
    """Sync the tenant's linked account emails (called on link/unlink)."""
    _check(body.user_uuid, instance_id)
    ensure_layout(body.user_uuid, instance_id)
    fp = os.path.join(instance_dir(body.user_uuid, instance_id), "fleet.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump({"emails": body.emails}, f)
    return {"success": True, "emails": body.emails}


@router.post("/{instance_id}/config")
def write_config(instance_id: str, body: ConfigBody):
    """Patch the tenant's local config.json with live website settings."""
    _check(body.user_uuid, instance_id)
    ensure_layout(body.user_uuid, instance_id)
    fp = os.path.join(instance_dir(body.user_uuid, instance_id), "config.json")
    cur: Dict[str, Any] = {}
    try:
        with open(fp, encoding="utf-8") as f:
            cur = json.load(f)
    except Exception:
        cur = {}
    cur["live_settings"] = body.settings
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(cur, f)
    return {"success": True}


@router.get("/{instance_id}/status")
def worker_status(instance_id: str, user_uuid: str):
    """PID/liveness of this tenant instance (never touches other tenants)."""
    _check(user_uuid, instance_id)
    from app.workers.tenant_worker_manager import status as wstatus
    return wstatus(user_uuid, instance_id)
