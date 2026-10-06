# app/api/endpoints/alliance.py
import logging
import uuid
from typing import Dict, Any, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.models import CharacterDAO, AccountDAO, TaskLogDAO
from app.services.socket_worker import GameSocketWorker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/characters", tags=["Alliance"])


def _resolve_char(role_or_id: str, user_id: str = "") -> Optional[Dict[str, Any]]:
    char = CharacterDAO.get_by_role_id(str(role_or_id))
    if not char and str(role_or_id).isdigit():
        char = CharacterDAO.get_by_id(int(role_or_id))
    return char


@router.post("/{role_id}/dispatch-alliance-resource")
async def dispatch_alliance_resource_endpoint(
    role_id: str,
    bg_tasks: BackgroundTasks,
    user_id: str = Query("")
):
    """
    Directly dispatches a combat-first march to the Alliance Resource Center (Super Node).
    Zero-scan direct targeting from live alliance territory state.
    """
    char = _resolve_char(role_id, user_id)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")

    actual_role_id = str(char["role_id"])
    acc = AccountDAO.get_by_id(char["account_id"]) if char.get("account_id") else None
    bot_id = str(acc.get("bot_id") or "bot-0") if acc else "bot-0"
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    TaskLogDAO.create(
        task_id=task_id,
        role_id=actual_role_id,
        task_type="dispatch_alliance_resource",
        status="RUNNING",
        details={"mode": "combat_first_zero_scan"},
        character_id=char["id"]
    )

    bg_tasks.add_task(
        GameSocketWorker.run_character_task,
        task_id=task_id,
        role_id=actual_role_id,
        task_type="dispatch_alliance_resource",
        params={"bot_id": bot_id},
        user_id=user_id
    )

    return {
        "success": True,
        "task_id": task_id,
        "role_id": actual_role_id,
        "character_name": char.get("name"),
        "status": "RUNNING",
        "message": f"Direct dispatch to Alliance Resource Center initiated for {char.get('name')}",
    }
