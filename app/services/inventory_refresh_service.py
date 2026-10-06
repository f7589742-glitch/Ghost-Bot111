"""Bulk inventory refresh: log in → read live resources → upsert → log out.

Read-only pass over a room's characters. Sequential per account while briefly
holding the account lock so the gather scheduler never races the same gateway
session (no kicks either way). Balances come from live Opcode 121 / 1002 wire
data; InventoryDAO.upsert only overwrites with positive values, so a partial
parse can never zero an account.
"""
import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

_REFRESH_JOBS: Dict[str, Dict[str, Any]] = {}


def _job_log(job: Dict[str, Any], msg: str) -> None:
    try:
        job.setdefault("logs", []).append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        job["logs"] = job["logs"][-60:]
    except Exception:
        pass


async def run_refresh_job(job_id: str, roles: List[str], user_id: str = "", bot_id: str = "") -> Dict[str, Any]:
    from app.models import CharacterDAO, AccountDAO, InventoryDAO
    from app.services.session_manager import get_active_client
    try:
        from app.services.scheduler import get_account_lock
    except Exception:
        get_account_lock = None  # type: ignore

    job = _REFRESH_JOBS.get(job_id) or {}
    job.update({"status": "RUNNING", "total": len(roles), "done": 0})
    _REFRESH_JOBS[job_id] = job

    for i, role_id in enumerate(roles):
        if job.get("cancelled"):
            break
        role_id = str(role_id)
        entry = {"role_id": role_id, "name": role_id, "status": "RUNNING", "detail": ""}
        job.setdefault("results", []).append(entry)
        try:
            char = CharacterDAO.get_by_role_id(role_id, user_id) if user_id else None
            if not char:
                char = CharacterDAO.get_by_role_id(role_id)
            if not char:
                entry.update({"status": "FAILED", "detail": "not found"})
                continue
            entry["name"] = char.get("name") or role_id
            acc = None
            try:
                acc = AccountDAO.get_by_id(char.get("account_id"), user_id) if user_id else None
            except Exception:
                acc = None
            if not acc:
                try:
                    acc = AccountDAO.get_by_id(char.get("account_id"))
                except Exception:
                    acc = None
            lock = None
            if get_account_lock:
                try:
                    lock = get_account_lock(str(char.get("account_id") or role_id))
                except Exception:
                    lock = None
            if lock is not None and lock.locked():
                entry.update({"status": "SKIPPED", "detail": "account busy in scheduler cycle"})
                _job_log(job, f"[{entry['name']}] ⏭️ الحساب مشغول بدورة مجدول — تم التخطي.")
                continue

            quiet = lambda m: _job_log(job, str(m)[:160])
            if lock is not None:
                async with lock:
                    client = await get_active_client(role_id, user_id=user_id or "", log_cb=quiet)
                    await _sync_client_state(job, entry, job_id, role_id, acc, bot_id, client)
            else:
                client = await get_active_client(role_id, user_id=user_id or "", log_cb=quiet)
                await _sync_client_state(job, entry, job_id, role_id, acc, bot_id, client)
        except Exception as e:
            entry.update({"status": "FAILED", "detail": str(e)[:120]})
        finally:
            job["done"] = int(job.get("done", 0)) + 1
        if i < len(roles) - 1:
            await asyncio.sleep(3.0)

    job["status"] = "CANCELLED" if job.get("cancelled") else "COMPLETED"
    _REFRESH_JOBS[job_id] = job
    return job


async def _sync_client_state(job, entry, job_id, role_id, acc, bot_id, client) -> None:
    from app.models import InventoryDAO
    if not client:
        entry.update({"status": "FAILED", "detail": "gateway login failed"})
        return
    try:
        state = getattr(client, "state", {}) or {}
        rss = state.get("resources", {}) or {}
        food = int(rss.get("food", 0) or 0)
        wood = int(rss.get("wood", 0) or 0)
        stone = int(rss.get("stone", 0) or 0)
        gold = int(rss.get("gold", 0) or 0)
        gems = int(rss.get("gems", 0) or 0)
        bid = (acc.get("bot_id") if acc else None) or bot_id or "bot-0"
        InventoryDAO.upsert(
            bot_id=str(bid),
            role_id=str(role_id),
            name=entry.get("name") or "",
            food=food, wood=wood, stone=stone, gold=gold, gems=gems,
        )
        entry.update({"status": "COMPLETED",
                      "detail": f"{food:,}/{wood:,}/{stone:,}/{gold:,}"})
        _job_log(job, f"[{entry['name']}] 💾 المخزون: {food:,}/{wood:,}/{stone:,}/{gold:,}")
    except Exception as e:
        entry.update({"status": "FAILED", "detail": str(e)[:120]})
    finally:
        try:
            await client.close()
        except Exception:
            pass


def new_refresh_job(roles: List[str]) -> str:
    job_id = f"rx_{uuid.uuid4().hex[:10]}"
    _REFRESH_JOBS[job_id] = {
        "job_id": job_id, "status": "QUEUED", "total": len(roles),
        "done": 0, "results": [], "logs": [], "cancelled": False,
        "created_at": int(time.time()),
    }
    return job_id
