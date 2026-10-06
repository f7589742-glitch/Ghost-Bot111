#!/usr/bin/env python3
"""Supabase MCP-style tool module for the Aegis Fleet backend.

Scoped helpers for AI/automation use. Every call is filtered by user_id
(RLS also enforces this in the database). Reads SUPABASE_URL and
SUPABASE_SERVICE_KEY from the environment — never commit keys.

Tools:
  get_user_fleet_status(user_id)            -> instances + accounts overview
  update_farm_settings(account_id, user_id, new_config) -> patch settings jsonb
  trigger_instance_action(instance_id, user_id, action)  -> start|stop via AWS backend

Usage as stdio JSON-RPC (one request per line):
  {"tool": "get_user_fleet_status", "args": {"user_id": "..."}}
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://16.171.9.216").rstrip("/")
BOT_SECRET = os.environ.get("BACKEND_STEALTH_SECRET", "")
API_KEY = os.environ.get("BACKEND_API_KEY", "")


def _sb(method: str, path: str, body: dict | None = None) -> object:
    if not SUPABASE_URL or not SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        data=data,
        method=method,
        headers={
            "apikey": SERVICE_KEY,
            "Authorization": f"Bearer {SERVICE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        text = res.read().decode()
        return json.loads(text) if text else []


def get_user_fleet_status(user_id: str) -> dict:
    instances = _sb("GET", f"bot_instances?user_id=eq.{user_id}&select=*")
    accounts = _sb("GET", f"game_accounts?user_id=eq.{user_id}&select=*")
    return {"instances": instances, "accounts": accounts}


def update_farm_settings(account_id: int, user_id: str, new_config: dict) -> dict:
    rows = _sb("GET", f"game_accounts?id=eq.{account_id}&user_id=eq.{user_id}&select=settings")
    if not rows:
        return {"success": False, "error": "account not found for this user"}
    merged = {**(rows[0].get("settings") or {}), **new_config}
    out = _sb("PATCH", f"game_accounts?id=eq.{account_id}&user_id=eq.{user_id}", {"settings": merged})
    return {"success": True, "account": out}


def trigger_instance_action(instance_id: str, user_id: str, action: str) -> dict:
    if action not in ("start", "stop"):
        return {"success": False, "error": "action must be start|stop"}
    rows = _sb("GET", f"bot_instances?id=eq.{instance_id}&user_id=eq.{user_id}&select=id")
    if not rows:
        return {"success": False, "error": "instance not found for this user"}
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/bot/{action}",
        data=b"{}",
        method="POST",
        headers={"X-Bot-Secret": BOT_SECRET, "X-API-Key": API_KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return {"success": True, "backend": json.loads(res.read().decode() or "{}")}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}


TOOLS = {
    "get_user_fleet_status": get_user_fleet_status,
    "update_farm_settings": update_farm_settings,
    "trigger_instance_action": trigger_instance_action,
}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            fn = TOOLS[msg["tool"]]
            print(json.dumps({"ok": True, "result": fn(**msg.get("args", {}))}), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(e)}), flush=True)


if __name__ == "__main__":
    main()
