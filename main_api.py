"""
main_api.py - Unified FastAPI Service
REST API endpoints for hybrid account onboarding, emulator management,
and live character profile queries.
"""

import os
import sys
import uuid
import asyncio
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "python"))
sys.path.insert(0, ROOT_DIR)

from ldplayer_controller import LDPlayerController
from rok_engine import RokEngine

app = FastAPI(
    title="Rise of Kingdoms Hybrid Automation API",
    description="Unified Headless Protocol & LDPlayer-1 Fallback Automation Service",
    version="1.0.0"
)

# In-memory task tracking for immediate execution
TASKS_DB: Dict[str, Dict[str, Any]] = {}

controller = LDPlayerController(instance_index=1, serial="emulator-5556")
engine = RokEngine()


class AccountAddRequest(BaseModel):
    email: str
    password: str
    force_emulator_fallback: bool = False


class EmulatorControlRequest(BaseModel):
    action: str # "launch", "stop", "launch_game", "stop_game", "extract_tokens", "screenshot"
    instance_index: int = 1


class RunBotRequest(BaseModel):
    app_uid: str
    access_token: str
    role_id: str
    train_count: int = 200


async def process_account_onboarding(task_id: str, email: str, password: str, force_fallback: bool):
    TASKS_DB[task_id] = {
        "task_id": task_id,
        "status": "PROCESSING",
        "email": email,
        "step": "inspecting_session"
    }

    tokens = None
    if not force_fallback:
        tokens = controller.extract_tokens(target_email=email)

    if tokens:
        TASKS_DB[task_id]["step"] = "validating_headless_login"
        res = await engine.login_and_query_characters(
            app_uid=tokens["app_uid"],
            app_token=tokens["access_token"]
        )
        if res.get("login_ok"):
            TASKS_DB[task_id].update({
                "status": "SUCCESS",
                "method": "headless_direct",
                "step": "completed",
                "tokens": tokens,
                "data": res
            })
            return

    # Fallback to LDPlayer-1
    TASKS_DB[task_id]["step"] = "triggering_ldplayer_fallback"
    controller.automate_login(email, password)
    tokens = controller.extract_tokens(target_email=email)

    if not tokens:
        TASKS_DB[task_id].update({
            "status": "FAILED",
            "error": "Failed to extract session tokens from LDPlayer-1"
        })
        return

    TASKS_DB[task_id]["step"] = "headless_profile_query"
    res = await engine.login_and_query_characters(
        app_uid=tokens["app_uid"],
        app_token=tokens["access_token"]
    )

    TASKS_DB[task_id].update({
        "status": "SUCCESS",
        "method": "ldplayer_fallback",
        "step": "completed",
        "tokens": tokens,
        "data": res
    })


@app.get("/")
def root():
    return {
        "service": "RoK Hybrid Automation Engine",
        "status": "online",
        "active_emulator": "LDPlayer-1 (emulator-5556)",
        "protocol_gate": "43.159.113.101:3101"
    }


@app.post("/api/v1/accounts/add")
async def add_account(req: AccountAddRequest, bg: BackgroundTasks):
    """
    Accepts credentials and starts background onboarding:
    Headless login first -> LDPlayer-1 fallback if verification/token needed.
    """
    task_id = str(uuid.uuid4())
    bg.add_task(process_account_onboarding, task_id, req.email, req.password, req.force_emulator_fallback)
    return {
        "task_id": task_id,
        "message": "Account onboarding initiated in background.",
        "status_url": f"/api/v1/tasks/{task_id}"
    }


@app.post("/api/v1/emulator/control")
def control_emulator(req: EmulatorControlRequest):
    """
    Manually controls LDPlayer instances (Launch, Stop, Screenshot, Extract Tokens).
    """
    ctrl = LDPlayerController(instance_index=req.instance_index, serial=f"emulator-{5554 + req.instance_index*2}")
    
    if req.action == "launch":
        ok = ctrl.launch()
        return {"status": "ok" if ok else "failed", "action": "launch"}
    elif req.action == "stop":
        ok = ctrl.stop()
        return {"status": "ok" if ok else "failed", "action": "stop"}
    elif req.action == "launch_game":
        ctrl.launch_game()
        return {"status": "ok", "action": "launch_game"}
    elif req.action == "stop_game":
        ctrl.stop_game()
        return {"status": "ok", "action": "stop_game"}
    elif req.action == "extract_tokens":
        tokens = ctrl.extract_tokens()
        return {"status": "ok" if tokens else "failed", "tokens": tokens}
    elif req.action == "screenshot":
        img_path = os.path.join(ROOT_DIR, "emulator_capture.png")
        ok = ctrl.take_screenshot(img_path)
        return {"status": "ok" if ok else "failed", "file": img_path}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action {req.action}")


@app.get("/api/v1/tasks/{task_id}")
def get_task_status(task_id: str):
    """
    Returns live account discovery status and character profiles.
    """
    if task_id not in TASKS_DB:
        raise HTTPException(status_code=404, detail="Task not found")
    return TASKS_DB[task_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
