import time
import asyncio
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel

from app.database import get_db_connection
from app.models import CharacterDAO, InventoryDAO
from app.services.rss_transfer_service import RSSTransferEngine, TransferJobRunner, TRADING_POST_DATA
from app.services.session_manager import toggle_gather_scheduler
from app.services.activity_stream import activity_stream

logger = logging.getLogger("RSSTransferAPI")

router = APIRouter(tags=["RSS Transfer"])

# In-memory registry for real-time transfer jobs telemetry
_ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}


def _init_transfer_db():
    """Ensures local SQLite recipient table exists as persistent backing store."""
    con = get_db_connection()
    with con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS rss_transfer_recipients (
                role_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
        """)


try:
    _init_transfer_db()
except Exception as e:
    logger.warning(f"Could not initialize rss_transfer_recipients table: {e}")


class TransferOrderSchema(BaseModel):
    target_role_id: str
    target_name: Optional[str] = "Target"
    x: int
    y: int
    requested_rss: Dict[str, int]
    selected_farm_roles: List[str]
    user_id: Optional[str] = ""
    transfer_mode: Optional[str] = "total_net"
    custom_tp_level: Optional[int] = None


def _firebase_save_recipient(role_id: str, name: str, x: int, y: int):
    """Safely saves recipient into Firebase Realtime Database if configured."""
    try:
        import firebase_admin
        from firebase_admin import db
        if firebase_admin._apps:
            ref = db.reference(f"rss_transfer_recipients/{role_id}")
            ref.set({
                "role_id": role_id,
                "name": name,
                "x": x,
                "y": y,
                "updated_at": int(time.time())
            })
    except Exception as e:
        logger.debug(f"Firebase recipient save skipped: {e}")


def _firebase_fetch_recipients() -> List[Dict[str, Any]]:
    """Safely fetches recipients from Firebase if available."""
    try:
        import firebase_admin
        from firebase_admin import db
        if firebase_admin._apps:
            ref = db.reference("rss_transfer_recipients")
            data = ref.get()
            if isinstance(data, dict):
                return list(data.values())
    except Exception as e:
        logger.debug(f"Firebase fetch skipped: {e}")
    return []


def _firebase_log(job_id: str, msg: str):
    """Safely appends telemetry log line into Firebase if available."""
    try:
        import firebase_admin
        from firebase_admin import db
        if firebase_admin._apps:
            ref = db.reference(f"transfer_logs/{job_id}")
            ref.push({"timestamp": int(time.time()), "message": msg})
    except Exception:
        pass


@router.get("/saved-recipients")
@router.get("/v1/saved-recipients")
async def list_saved_recipients():
    """Fetches previously saved buyer/recipient records from Firebase or SQLite."""
    fb_recipients = _firebase_fetch_recipients()
    if fb_recipients:
        return {"recipients": fb_recipients}

    con = get_db_connection()
    try:
        rows = con.execute("SELECT role_id, name, x, y, updated_at FROM rss_transfer_recipients ORDER BY updated_at DESC").fetchall()
        return {"recipients": [dict(r) for r in rows]}
    except Exception as e:
        logger.error(f"Error fetching recipients: {e}")
        return {"recipients": []}


@router.get("/trading-post-rates")
@router.get("/v1/trading-post-rates")
async def get_trading_post_rates():
    """Returns official Trading Post capacity and tax rates for all levels 1-25."""
    return {"progression": TRADING_POST_DATA}


@router.get("/characters/summary")
@router.get("/v1/characters/summary")
async def get_characters_summary(user_id: Optional[str] = Query(None), bot_id: Optional[str] = Query(None)):
    """Summary of all available farms with current resources, email, and city level."""
    con = get_db_connection()
    try:
        from app.api.routes import _normalize_bot_id
    except Exception:
        def _normalize_bot_id(b): return b or ""

    query = """
        SELECT c.role_id, c.name, c.alliance_tag, c.food, c.wood, c.stone, c.gold, c.city_level, c.power, a.email
        FROM characters c
        JOIN accounts a ON c.account_id = a.id
        WHERE c.enabled = 1
    """
    params = []
    if user_id:
        query += " AND a.user_id = ?"
        params.append(user_id)
    if bot_id:
        nbid = _normalize_bot_id(bot_id)
        if nbid:
            query += " AND (a.bot_id = ? OR a.bot_id = ?)"
            params.extend([nbid, nbid.replace("bot-", "")])
    query += " ORDER BY c.power DESC"

    rows = con.execute(query, params).fetchall()
    chars = []
    for r in rows:
        city_lvl = int(r["city_level"] or 17)
        tp_data = TRADING_POST_DATA.get(city_lvl, TRADING_POST_DATA[17])
        chars.append({
            "role_id": str(r["role_id"]),
            "name": r["name"] or f"Gov_{r['role_id']}",
            "email": r["email"] or "",
            "alliance_tag": r["alliance_tag"] or "",
            "resources": {
                "food": int(r["food"] or 0),
                "wood": int(r["wood"] or 0),
                "stone": int(r["stone"] or 0),
                "gold": int(r["gold"] or 0),
            },
            "power": int(r["power"] or 0),
            "city_hall": city_lvl,
            "city_level": city_lvl,
            "tax_rate": int(tp_data["tax"] * 100)
        })
    return {"characters": chars}


@router.post("/start-transfer")
@router.post("/v1/start-transfer")
async def trigger_rss_transfer(order: TransferOrderSchema, bg_tasks: BackgroundTasks):
    """
    Saves recipient to Firebase/SQLite, pauses gather loops, and dispatches parallel transfers.
    """
    target_id_str = str(order.target_role_id or "").strip()
    order.selected_farm_roles = [
        str(f).strip() for f in (order.selected_farm_roles or [])
        if f and str(f).strip().isdigit() and str(f).strip() != target_id_str
    ]
    if not order.selected_farm_roles:
        raise HTTPException(status_code=400, detail="يرجى تحديد مزرعة صالحة واحدة على الأقل لإرسال الموارد منها.")

    if not order.target_role_id or not str(order.target_role_id).isdigit():
        raise HTTPException(status_code=400, detail="معرف الحساب المستلم (Role ID) غير صالح.")

    job_id = f"tx_{int(time.time())}"

    # 1. Upsert Recipient into SQLite
    try:
        con = get_db_connection()
        with con:
            con.execute("""
                INSERT INTO rss_transfer_recipients (role_id, name, x, y, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(role_id) DO UPDATE SET
                    name = excluded.name,
                    x = excluded.x,
                    y = excluded.y,
                    updated_at = excluded.updated_at
            """, (order.target_role_id, order.target_name or "Target", order.x, order.y, int(time.time())))
    except Exception as e:
        logger.warning(f"Failed to upsert recipient into SQLite: {e}")

    # 2. Upsert into Firebase
    _firebase_save_recipient(order.target_role_id, order.target_name or "Target", order.x, order.y)

    # 3. Register initial job structure in memory
    con = get_db_connection()
    initial_workers = []
    account_set = set()

    for r_id in order.selected_farm_roles:
        row = con.execute("""
            SELECT c.role_id, c.name, c.city_level, a.email
            FROM characters c
            LEFT JOIN accounts a ON c.account_id = a.id
            WHERE c.role_id = ?
        """, (str(r_id),)).fetchone()

        farm_name = row["name"] if (row and row["name"]) else f"Farm_{r_id}"
        email = row["email"] if (row and row["email"]) else f"account_{r_id}@rok.bot"
        city_lvl = int(row["city_level"]) if (row and row["city_level"]) else 17
        tp_data = TRADING_POST_DATA.get(city_lvl, TRADING_POST_DATA[17])
        tax_pct = int(tp_data["tax"] * 100)

        account_set.add(email)
        initial_workers.append({
            "role_id": str(r_id),
            "name": farm_name,
            "email": email,
            "stage_msg": "Recalling army marches (Opcode 1014)...",
            "market_lvl": city_lvl,
            "tax_rate": tax_pct,
            "sent_amount": 0,
            "sent_rss": {"food": 0, "wood": 0, "stone": 0, "gold": 0},
            "status": "WAITING"
        })

    initial_accounts = [{"email": email, "status": "RUNNING"} for email in sorted(list(account_set))]

    _ACTIVE_JOBS[job_id] = {
        "job_id": job_id,
        "target_role_id": order.target_role_id,
        "target_name": order.target_name or f"Target_{order.target_role_id}",
        "x": order.x,
        "y": order.y,
        "coords": (order.x, order.y),
        "requested": order.requested_rss,
        "requested_rss": order.requested_rss,
        "farms": order.selected_farm_roles,
        "status": "RUNNING",
        "progress": 0,
        "logs": [],
        "delivered": {"food": 0, "wood": 0, "stone": 0, "gold": 0},
        "accounts": initial_accounts,
        "workers": initial_workers,
        "created_at": int(time.time()),
        "cancelled": False
    }

    # 4. Launch background transfer pipeline
    bg_tasks.add_task(run_parallel_transfer_job, job_id, order)

    return {
        "success": True,
        "job_id": job_id,
        "message": f"تم إطلاق خطة النقل المتزامن لجميع المزارع ({len(order.selected_farm_roles)} مزارع) إلى {order.target_name} (#{order.target_role_id})."
    }


@router.get("/status/{job_id}")
@router.get("/v1/status/{job_id}")
async def get_transfer_status(job_id: str):
    """Retrieves live progress and structured telemetry for an ongoing or completed transfer job."""
    job = _ACTIVE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="رقم مهمة النقل غير موجود.")
    return {
        "job_id": job["job_id"],
        "status": job.get("status", "RUNNING"),
        "progress": job.get("progress", 0),
        "target_role_id": job.get("target_role_id", ""),
        "x": job.get("x", 0),
        "y": job.get("y", 0),
        "requested": job.get("requested", job.get("requested_rss", {})),
        "delivered": job.get("delivered", {}),
        "accounts": job.get("accounts", []),
        "workers": job.get("workers", []),
        "logs": job.get("logs", [])[-60:],
        "completed": job.get("status") in ("COMPLETED", "FAILED", "CANCELLED", "PARTIAL")
    }


@router.post("/stop/{job_id}")
@router.post("/v1/stop/{job_id}")
@router.post("/transfer/{job_id}/cancel")
@router.post("/v1/transfer/{job_id}/cancel")
async def stop_transfer_job(job_id: str):
    """Stops an active RSS transfer pipeline."""
    job = _ACTIVE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="المهمة غير موجودة.")
    job["cancelled"] = True
    job["status"] = "CANCELLED"
    TransferJobRunner.update_telemetry(job_id, {"status": "CANCELLED"})
    toggle_gather_scheduler(paused=False)
    return {"success": True, "message": "تم إيقاف مهمة النقل واستئناف الجدولة."}


async def run_parallel_transfer_job(job_id: str, order: TransferOrderSchema):
    """
    Concurrent pipeline: pauses gathering, distributes payload, and dispatches parallel transfers.
    Publishes real-time telemetry into Firebase Realtime Database and _ACTIVE_JOBS.
    """
    job = _ACTIVE_JOBS[job_id]

    def log(msg: str):
        logger.info(f"[{job_id}] {msg}")
        job["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        _firebase_log(job_id, msg)
        asyncio.create_task(activity_stream.broadcast(f"[RSS_TRANSFER] {msg}", user_id=order.user_id or ""))

    num_farms = len(order.selected_farm_roles)
    mode_name = "إجمالي طلب الزبون" if order.transfer_mode == "total_net" else ("تفريغ كامل المتاح" if order.transfer_mode == "max_drain" else "حصة فردية لكل مزرعة")
    log(f"⚡ بدء مهمة النقل المتزامن #{job_id} إلى {order.target_name} ({order.x}, {order.y}) عبر {num_farms} مزارع [الوضع: {mode_name}]...")

    try:
        telemetry = await TransferJobRunner.run_pipeline(job_id, order.dict(), log_cb=log)
        
        total_delivered = telemetry.get("delivered", {})
        job["delivered"] = total_delivered
        job["status"] = telemetry.get("status", "COMPLETED")
        job["accounts"] = telemetry.get("accounts", job.get("accounts", []))
        job["workers"] = telemetry.get("workers", job.get("workers", []))
        job["progress"] = 100

        delivered_readable = ", ".join(f"{k}: {v:,}" for k, v in total_delivered.items() if v > 0) or "لا توجد شحنات"
        log(f"🎉 اكتملت عملية النقل بالكامل! إجمالي الموارد المسلمة: {delivered_readable}")

        deficits = []
        for res_name, req_amt in order.requested_rss.items():
            if req_amt > 0:
                deliv = total_delivered.get(res_name, 0)
                if deliv < req_amt:
                    diff = req_amt - deliv
                    deficits.append(f"{res_name}: متبقي {diff:,} صافي لم يُنقل (تم تسليم {deliv:,} من أصل {req_amt:,})")

        if deficits:
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            log("⚠️ [تقرير العجز المتبقي - نفاد رصيد المزارع المحددة]:")
            for d in deficits:
                log(f"  ❌ {d}")
            log("💡 انتهت الموارد المتاحة في المزارع المحددة. يمكنك تزويد المزارع أو اختيار مزارع إضافية لاحقاً.")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    except Exception as e:
        job["status"] = "FAILED"
        log(f"💥 فشلت مهمة النقل: {e}")
    finally:
        toggle_gather_scheduler(paused=False)
        log("🔄 تم استئناف جدولة جمع الموارد لجميع المزارع بنجاح.")
