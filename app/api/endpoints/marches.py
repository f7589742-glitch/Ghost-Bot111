import logging
import uuid
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.models import CharacterDAO, AccountDAO, TaskLogDAO
from app.services.socket_worker import GameSocketWorker
from app.services.march_service import recall_character_marches

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/characters", tags=["Marches"])

class BulkRecallRequest(BaseModel):
    role_ids: List[str]

def _resolve_char(role_or_id: str, user_id: str = "") -> Optional[Dict[str, Any]]:
    char = CharacterDAO.get_by_role_id(str(role_or_id))
    if not char and str(role_or_id).isdigit():
        char = CharacterDAO.get_by_id(int(role_or_id))
    return char

@router.post("/{role_id}/recall-marches")
async def recall_character_marches_endpoint(
    role_id: str,
    bg_tasks: BackgroundTasks,
    user_id: str = Query("")
):
    """
    Manually recalls all field marches for a specific character.
    Triggered ONLY via explicit API request (frontend single character button).
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
        task_type="recall",
        status="RUNNING",
        details={},
        character_id=char["id"]
    )
    
    bg_tasks.add_task(
        GameSocketWorker.run_character_task,
        task_id=task_id,
        role_id=actual_role_id,
        task_type="recall",
        params={"bot_id": bot_id},
        user_id=user_id
    )
    
    return {
        "success": True,
        "task_id": task_id,
        "role_id": actual_role_id,
        "character_name": char.get("name"),
        "status": "RUNNING",
        "message": f"Recall dispatched for {char.get('name')}",
    }

@router.post("/bulk-recall-marches")
async def bulk_recall_marches_endpoint(
    req: BulkRecallRequest,
    bg_tasks: BackgroundTasks,
    user_id: str = Query("")
):
    """
    Top bar bulk button with list of role_ids.
    Sequentially logs into each character, recalls field marches, and closes session.
    """
    from app.api.routes import _run_sequential_recall
    
    targets = []
    skipped = []
    for r_id in req.role_ids:
        char = _resolve_char(str(r_id), user_id)
        if not char:
            skipped.append({"role_id": r_id, "reason": "not_found"})
            continue
        targets.append(char)

    if not targets:
        raise HTTPException(status_code=400, detail="No valid characters found in list")

    batch_task_id = f"batch_recall_{uuid.uuid4().hex[:10]}"
    task_entries = []
    for char in targets:
        t_id = f"task_{uuid.uuid4().hex[:12]}"
        TaskLogDAO.create(
            task_id=t_id,
            role_id=str(char["role_id"]),
            task_type="recall",
            status="QUEUED",
            details={"batch": batch_task_id},
            character_id=char["id"]
        )
        task_entries.append({"role_id": str(char["role_id"]), "name": char.get("name"), "task_id": t_id})

    bg_tasks.add_task(
        _run_sequential_recall,
        targets=targets,
        task_entries=task_entries,
        user_id=user_id
    )

    return {
        "success": True,
        "batch_task_id": batch_task_id,
        "queued": len(targets),
        "skipped": len(skipped),
        "details": task_entries,
        "message": f"Queued sequential march recall for {len(targets)} character(s)",
    }
