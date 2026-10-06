import asyncio
import logging
import random
import time
from typing import List, Dict, Any, Optional

from app.models import BotSettingsDAO, AccountDAO, CharacterDAO, TaskLogDAO
from app.services.activity_stream import activity_stream
from app.services.activity_logger import TenantActivityStream

logger = logging.getLogger("FleetDispatchEngine")


class FleetDispatchEngine:
    """
    Fleet Dispatch Engine:
    - Bounded Async Queue Worker Pool (asyncio.Semaphore(3))
    - Prevents socket auth throttling & Lilith gateway rejection
    - 1.5s staggered worker entry
    - Resilient connection & auth retry (3 attempts, backoff 2s -> 4s -> 8s)
    - Clean non-blocking worker release on persistent errors
    """
    MAX_CONCURRENT_WORKERS = 3
    MAX_RETRIES = 3
    BACKOFF_STEPS = [2.0, 4.0, 8.0]

    @classmethod
    async def run_room_fleet(cls, room_id: str, accounts: list, scheduler=None):
        """
        Runs fleet execution for a room with an Async Queue Worker Pool.
        Dispatches accounts through a managed semaphore queue (3 concurrent workers).
        """
        semaphore = asyncio.Semaphore(cls.MAX_CONCURRENT_WORKERS)

        async def worker_wrapper(account):
            async with semaphore:
                # Stagger account starts slightly to prevent burst auth conflicts
                await asyncio.sleep(1.5)
                return await cls.execute_account_lifecycle(account, scheduler=scheduler)

        tasks = [
            worker_wrapper(acc)
            for acc in accounts
            if acc.get("is_active", True) or acc.get("is_enabled", True)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    @classmethod
    async def run_governor_queue(
        cls,
        governor_items: list,
        scheduler,
        stage_num: int = 1,
        stage_name: str = ""
    ) -> list:
        """
        Managed task queue for governor execution in a specific stage (e.g. Slot 1 Primary or Slot 2 Secondary).
        Controls execution through asyncio.Semaphore(MAX_CONCURRENT_WORKERS = 3).
        Staggers entry by 1.5s inside the semaphore to prevent Lilith gateway socket flood.
        Wraps each lifecycle in exponential retry backoff.
        """
        semaphore = asyncio.Semaphore(cls.MAX_CONCURRENT_WORKERS)
        total_items = len(governor_items)

        async def worker_wrapper(idx: int, acc: dict, char: dict):
            if scheduler and not scheduler.is_running():
                return None
            async with semaphore:
                if scheduler and not scheduler.is_running():
                    return None
                # Stagger worker starts slightly (1.5s) to avoid burst auth / socket congestion
                await asyncio.sleep(1.5)
                return await cls.execute_governor_with_retry(
                    acc=acc,
                    char=char,
                    scheduler=scheduler,
                    stage_num=stage_num,
                    idx=idx,
                    total=total_items
                )

        tasks = [
            asyncio.create_task(worker_wrapper(idx, acc, char))
            for idx, (acc, char) in enumerate(governor_items, 1)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    @classmethod
    async def execute_governor_with_retry(
        cls,
        acc: dict,
        char: dict,
        scheduler,
        stage_num: int = 1,
        idx: int = 1,
        total: int = 1
    ) -> bool:
        """
        Executes a governor lifecycle with resilient retry:
        - Max retries: 3 attempts.
        - Exponential backoff: 2s -> 4s -> 8s.
        - Catches socket rejections / handshake timeouts without hanging the worker pool.
        - Immediately releases worker slot upon completion or after 3 failed attempts so remaining accounts proceed.
        """
        role_id = str(char.get("role_id") or "")
        name = char.get("name") or role_id
        max_retries = cls.MAX_RETRIES
        backoffs = cls.BACKOFF_STEPS

        uid = ""
        bid = ""
        if scheduler:
            uid = getattr(scheduler, "_user_id", "") or acc.get("user_id", "") or ""
            bid = getattr(scheduler, "_bot_id", "") or acc.get("bot_id", "") or ""
        else:
            uid = acc.get("user_id", "") or ""
            bid = acc.get("bot_id", "") or ""

        is_ar = False
        try:
            is_ar = "ar" in str(BotSettingsDAO.get("preferred_language", "ar", user_id=uid or None)).lower() or "ar" in str(BotSettingsDAO.get("ui_language", "ar", user_id=uid or None)).lower()
        except Exception:
            is_ar = True

        for attempt in range(1, max_retries + 1):
            if scheduler and not scheduler.is_running():
                logger.info(f"🛑 [HALT] Lifecycle for {name} ({role_id}) aborted — bot stopped by user.")
                return False

            try:
                if scheduler:
                    await scheduler._run_character_cycle(acc, char, already_locked=False, force_run=True)
                else:
                    from app.services.scheduler import get_scheduler
                    s = get_scheduler(user_id=uid, bot_id=bid)
                    await s._run_character_cycle(acc, char, already_locked=False, force_run=True)
                return True

            except asyncio.CancelledError:
                raise
            except Exception as e_err:
                err_str = str(e_err)[:120] or "connection/handshake error"
                if attempt < max_retries:
                    backoff = backoffs[min(attempt - 1, len(backoffs) - 1)]
                    retry_msg_ar = f"⚠️ [إعادة المحاولة] الحاكم [{name}] واجه خطأ اتصال ({err_str}). إعادة المحاولة ({attempt}/{max_retries}) بعد {backoff} ثوانٍ..."
                    retry_msg_en = f"⚠️ [RETRY] Governor [{name}] connection failed ({err_str}). Retrying ({attempt}/{max_retries}) in {backoff}s..."
                    disp = retry_msg_ar if is_ar else retry_msg_en
                    logger.warning(disp)
                    print(disp, flush=True)
                    TenantActivityStream.emit(bid, name, retry_msg_ar, user_id=uid, message_en=retry_msg_en)
                    asyncio.create_task(activity_stream.broadcast(disp, user_id=uid))
                    await asyncio.sleep(backoff)
                else:
                    # Final attempt failed — clean non-blocking notification, release worker immediately
                    skip_msg_ar = f"⚠️ [تخطي مؤقت] الحاكم [{name}] تعذر الاتصال به بعد {max_retries} محاولات ({err_str}). تم تحرير مسار العمل للمسيرات التالية وسيُعاد المحاولة الدورة القادمة."
                    skip_msg_en = f"⚠️ [TEMPORARY SKIP] Governor [{name}] failed after {max_retries} attempts ({err_str}). Worker slot released for next accounts; will retry next cycle."
                    disp = skip_msg_ar if is_ar else skip_msg_en
                    logger.error(disp)
                    print(disp, flush=True)
                    TenantActivityStream.emit(bid, name, skip_msg_ar, user_id=uid, message_en=skip_msg_en)
                    asyncio.create_task(activity_stream.broadcast(disp, user_id=uid))
                    return False

        return False

    @classmethod
    async def execute_account_lifecycle(cls, account: dict, scheduler=None) -> bool:
        """
        Executes lifecycle for all enabled characters of a single account.
        """
        from app.models import CharacterDAO
        chars = CharacterDAO.get_by_account_id(account["id"])
        enabled_chars = [
            c for c in chars
            if c.get("enabled", 1) == 1
            and "shoob" not in str(c.get("name") or "").lower()
        ]
        if not enabled_chars:
            return True

        overall_ok = True
        for char in enabled_chars:
            res = await cls.execute_governor_with_retry(acc=account, char=char, scheduler=scheduler)
            if not res:
                overall_ok = False
        return overall_ok
