import asyncio
import datetime
import logging
import random
import uuid
from typing import Optional

from app.models import AccountDAO, CharacterDAO, BotSettingsDAO, TaskLogDAO
from app.services.activity_stream import activity_stream
from app.services.socket_worker import GameSocketWorker
from app.tenant_ctx import current_user_id

logger = logging.getLogger("AutonomousScheduler")

class AutonomousScheduler:
    """
    Autonomous loop scheduler:
    Cycles sequentially through active accounts (is_active == 1)
    and enabled characters (enabled == 1).
    Honors dynamic web Config for gathering/training per governor.
    """
    def __init__(self, user_id: str = ""):
        self._user_id = user_id
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def is_running(self) -> bool:
        return self._running

    def start(self):
        if self._running:
            return
        self._running = True
        BotSettingsDAO.set("bot_running", "true", user_id=self._user_id or None)
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"AutonomousScheduler started for tenant {self._user_id}.")
        asyncio.create_task(activity_stream.broadcast(
            "Autonomous Scheduler started.", user_id=self._user_id))

    def stop(self):
        if not self._running:
            return
        self._running = False
        BotSettingsDAO.set("bot_running", "false", user_id=self._user_id or None)
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info(f"AutonomousScheduler stopped for tenant {self._user_id}.")
        asyncio.create_task(activity_stream.broadcast(
            "Autonomous Scheduler stopped.", user_id=self._user_id))

    def _parse_interval_hours(self) -> float:
        freq_str = BotSettingsDAO.get("run_frequency", "Every 2 hours", user_id=self._user_id or None)
        parts = freq_str.split()
        for p in parts:
            if p.isdigit():
                return float(p)
        return 2.0

    def _calculate_next_run(self, interval_hours: float) -> str:
        jitter_minutes = random.uniform(15, 30)
        if random.choice([True, False]):
            jitter_minutes = -jitter_minutes
        base_seconds = interval_hours * 3600
        jitter_seconds = jitter_minutes * 60
        total_seconds = max(1800, base_seconds + jitter_seconds)
        next_time = datetime.datetime.now() + datetime.timedelta(seconds=total_seconds)
        return next_time.strftime("%Y-%m-%d %H:%M:%S")

    async def _run_character_cycle(self, account: dict, char: dict):
        role_id = str(char["role_id"])
        kd = str(char["kingdom_id"])
        name = char.get("name") or role_id
        uid = self._user_id
        token = current_user_id.set(uid)
        await activity_stream.broadcast(f"Starting visit for {kd} KD ({name})...", kingdom_id=kd, user_id=uid)

        # Check if governor is enabled on web (per-character toggle)
        if not char.get("enabled", 1):
            await activity_stream.broadcast(f"Skipping {name} — disabled on web Config", kingdom_id=kd, user_id=uid)
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            interval_hours = self._parse_interval_hours()
            next_run_str = self._calculate_next_run(interval_hours)
            CharacterDAO.update_run_times(role_id, last_run=now_str, next_run=next_run_str)
            AccountDAO.update_last_run(account["id"], last_run=now_str)
            await activity_stream.broadcast(f"Visit completed for {name}. Next scheduled run: {next_run_str}.", kingdom_id=kd, user_id=uid)
            current_user_id.reset(token)
            return

        # Load dynamic settings from CharacterSettingsDAO (web Config tab)
        try:
            from app.models import CharacterSettingsDAO
            settings = CharacterSettingsDAO.get_by_character_id(char["id"])
        except Exception:
            settings = {}

        # 1. Dynamic Training Check
        try:
            # Training config can be in settings["training"] or inferred from tiers/train_pct
            training_cfg = settings.get("training") if isinstance(settings.get("training"), dict) else None
            training_enabled = True
            if training_cfg is not None:
                training_enabled = training_cfg.get("enabled", True)
            else:
                # Check BotSettings global toggle
                try:
                    from app.models import BotSettingsDAO
                    bot_train = BotSettingsDAO.get("training_enabled", "true", user_id=uid)
                    if str(bot_train).lower() in ("false", "0", "off", "disabled"):
                        training_enabled = False
                except:
                    pass
                # If gather_json has explicit training disabled flag
                gather_json = settings.get("gather") or {}
                if isinstance(gather_json, dict) and gather_json.get("training_enabled") is False:
                    training_enabled = False
            # Also check if any tier is configured; if all tiers are Off/skipped, consider disabled
            tiers = settings.get("tiers") or {}
            if training_enabled and tiers:
                # If all tiers are explicitly "Off" or empty, disable training
                if all(str(v).lower() in ("off", "skip", "0", "") for v in tiers.values()):
                    training_enabled = False

            if training_enabled:
                await activity_stream.broadcast(f"Initiating dynamic troop training for {name}...", kingdom_id=kd, user_id=uid)
                tid_train = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_train, role_id=role_id, task_type="train", status="RUNNING", details={}, character_id=char["id"])
                train_result = await GameSocketWorker.run_character_task(tid_train, role_id, "train", user_id=uid)
                if train_result and train_result.get("wire_logs"):
                    for wlog in train_result["wire_logs"]:
                        wmsg = wlog.get("message", "")
                        if any(kw in wmsg for kw in ["Trained", "TRAIN", "Barracks", "SUCCESS", "FAIL", "Trained 900x", "Swordsman"]):
                            await activity_stream.broadcast(wmsg[:300], kingdom_id=kd, user_id=uid)
                if train_result and not train_result.get("success", True):
                    await activity_stream.broadcast(f"Train FAILED: {train_result.get('error', 'unknown')}", kingdom_id=kd, user_id=uid)
        except Exception as e_train:
            logger.warning(f"Training failed for {role_id}: {e_train}")

        # 2. Dynamic Gathering Check
        gather_cfg = settings.get("gather") or {}
        gather_enabled = True
        if isinstance(gather_cfg, dict) and gather_cfg.get("enabled") is False:
            gather_enabled = False

        if not gather_enabled:
            await activity_stream.broadcast(f"Gathering disabled for {name} on web Config — skipping", kingdom_id=kd, user_id=uid)
        else:
            await activity_stream.broadcast(f"Dispatching gathering marches...", kingdom_id=kd, user_id=uid)
            try:
                tid = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid, role_id=role_id, task_type="gather", status="RUNNING", details={}, character_id=char["id"])
                gather_result = await GameSocketWorker.run_character_task(tid, role_id, "gather", user_id=uid)
                if gather_result and gather_result.get("wire_logs"):
                    for wlog in gather_result["wire_logs"]:
                        wmsg = wlog.get("message", "")
                        if any(kw in wmsg for kw in ["COORDS", "PACKET", "SUMMARY", "CONFIRMED", "SUCCESS", "FAIL", "ERROR", "FATAL", "[GATHER]", "INVENTORY", "DISPATCH", "SEARCH", "Sent gatherer"]):
                            await activity_stream.broadcast(wmsg[:300], kingdom_id=kd, user_id=uid)
                if gather_result and not gather_result.get("success", True):
                    await activity_stream.broadcast(f"Gather FAILED: {gather_result.get('error', 'unknown error')}", kingdom_id=kd, user_id=uid)
            except Exception as e:
                logger.warning(f"Gather failed for {role_id}: {e}")

        # Update Last Run and calculate Next Run with jitter
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        interval_hours = self._parse_interval_hours()
        next_run_str = self._calculate_next_run(interval_hours)
        CharacterDAO.update_run_times(role_id, last_run=now_str, next_run=next_run_str)
        AccountDAO.update_last_run(account["id"], last_run=now_str)
        await activity_stream.broadcast(f"Visit completed for {name}. Next scheduled run: {next_run_str}.", kingdom_id=kd, user_id=uid)
        current_user_id.reset(token)

    async def _run_loop(self):
        logger.info(f"AutonomousScheduler loop entered for tenant {self._user_id}.")
        while self._running:
            try:
                accounts = AccountDAO.get_all(self._user_id)
                active_accounts = [a for a in accounts if a.get("is_active", 1) == 1]
                all_pending: list = []
                for acc in active_accounts:
                    chars = CharacterDAO.get_by_account_id(acc["id"])
                    for c in chars:
                        if c.get("enabled", 1) == 1:
                            all_pending.append((acc, c))
                if not all_pending:
                    logger.info("Sweep: no enabled characters, skipping to sleep.")
                else:
                    logger.info(f"Sweep wave: {len(all_pending)} enabled character(s) across {len(active_accounts)} account(s) — strict sequential 1-by-1 execution.")
                    for acc, ch in all_pending:
                        if not self._running:
                            break
                        try:
                            await self._run_character_cycle(acc, ch)
                        except asyncio.CancelledError:
                            raise
                        except Exception as cycle_err:
                            logger.error(f"Error cycling character visit: {cycle_err}")
                        if self._running:
                            await asyncio.sleep(3.0)

                interval_hours = self._parse_interval_hours()
                sleep_seconds = max(300, int(interval_hours * 3600))
                logger.info(f"Sweep complete. Sleeping for {sleep_seconds}s before next round.")
                elapsed = 0
                while self._running and elapsed < sleep_seconds:
                    await asyncio.sleep(10.0)
                    elapsed += 10
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in AutonomousScheduler loop: {e}", exc_info=True)
                await asyncio.sleep(30.0)

scheduler = AutonomousScheduler()
_tenants: dict = {}

def get_scheduler(user_id: str) -> AutonomousScheduler:
    if not user_id:
        raise ValueError("user_id is required for tenant scheduler")
    sched = _tenants.get(user_id)
    if sched is None:
        sched = AutonomousScheduler(user_id=user_id)
        _tenants[user_id] = sched
    return sched

def stop_all_schedulers() -> None:
    for sched in list(_tenants.values()):
        try:
            sched.stop()
        except Exception:
            pass
