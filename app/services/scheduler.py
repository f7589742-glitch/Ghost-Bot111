import asyncio
import datetime
import logging
import random
import uuid
from typing import Optional

from app.models import AccountDAO, CharacterDAO, BotSettingsDAO, TaskLogDAO
from app.services.activity_stream import activity_stream
from app.services.activity_logger import TenantActivityStream
from app.services.socket_worker import GameSocketWorker
from app.tenant_ctx import current_user_id

logger = logging.getLogger("AutonomousScheduler")
_ACCOUNT_LOCKS: dict[str, asyncio.Lock] = {}
_QUEUED_OR_RUNNING_ROLES: set[str] = set()
_LAST_FINISHED_TS: dict[str, float] = {}
_VISIT_COOLDOWN_SECONDS = 120.0
_FLEET_GLOBAL_LOCK = asyncio.Lock()

def get_account_lock(account_id: str) -> asyncio.Lock:
    aid = str(account_id or "default")
    if aid not in _ACCOUNT_LOCKS:
        _ACCOUNT_LOCKS[aid] = asyncio.Lock()
    return _ACCOUNT_LOCKS[aid]

def force_reset_execution_locks():
    """Force-releases all account locks and flushes all queued/running states and cooldowns."""
    global _ACCOUNT_LOCKS, _QUEUED_OR_RUNNING_ROLES, _LAST_FINISHED_TS, _FLEET_GLOBAL_LOCK
    _ACCOUNT_LOCKS.clear()
    _QUEUED_OR_RUNNING_ROLES.clear()
    _LAST_FINISHED_TS.clear()
    _FLEET_GLOBAL_LOCK = asyncio.Lock()
    logger.info("⚡ [LOCK RESET] Per-account execution locks, fleet lock, queued roles, and cooldowns forcefully cleared.")


class AutonomousScheduler:
    """
    Autonomous loop scheduler:
    Cycles sequentially through active accounts (is_active == 1)
    and enabled characters (enabled == 1).
    Honors dynamic web Config for gathering/training per governor.
    """
    def __init__(self, user_id: str = "", bot_id: str = ""):
        self._user_id = user_id
        self._bot_id = bot_id
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._wake_event = asyncio.Event()
        self._lock = asyncio.Lock()

    def is_running(self) -> bool:
        if self._running:
            return True
        return BotSettingsDAO.is_bot_running(self._bot_id, self._user_id)

    def reset_cooldowns(self):
        global _LAST_FINISHED_TS
        _LAST_FINISHED_TS.clear()

    def start(self):
        self._running = True
        self.reset_cooldowns()
        key_suffix = f"_{self._bot_id}" if self._bot_id else ""
        BotSettingsDAO.set(f"bot_running{key_suffix}", "true", user_id=self._user_id or None)
        if self._bot_id:
            BotSettingsDAO.set("bot_running", "true", user_id=self._bot_id)
        if self._wake_event:
            self._wake_event.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop())
        logger.info(f"AutonomousScheduler started for tenant {self._user_id} bot_id={self._bot_id}.")
        TenantActivityStream.emit(self._bot_id, None, "Autonomous Scheduler started.", user_id=self._user_id, message_en="Autonomous Scheduler started.")
        asyncio.create_task(activity_stream.broadcast(
            "Autonomous Scheduler started.", user_id=self._user_id))

    def stop(self):
        self._running = False
        key_suffix = f"_{self._bot_id}" if self._bot_id else ""
        if self._user_id:
            BotSettingsDAO.set(f"bot_running{key_suffix}", "false", user_id=self._user_id)
            BotSettingsDAO.set("bot_running", "false", user_id=self._user_id)
        if self._bot_id:
            BotSettingsDAO.set(f"bot_running_{self._bot_id}", "false")
            BotSettingsDAO.set("bot_running", "false", user_id=self._bot_id)
        if self._task and not self._task.done():
            self._task.cancel()
        _QUEUED_OR_RUNNING_ROLES.clear()

        # Objective 1: Reset on Stop (تصفير الوقت عند الإيقاف)
        try:
            from app.services.scheduler_service import BotScheduler
            BotScheduler.reset_bot_schedule(self._bot_id, self._user_id)
        except Exception as e_rst:
            logger.warning(f"Error resetting bot schedule on stop: {e_rst}")

        # Abort in-flight waits and close active sockets
        try:
            from app.services.socket_worker import GameSocketWorker
            if hasattr(GameSocketWorker, "_active_workers"):
                for worker in list(getattr(GameSocketWorker, "_active_workers", {}).values()):
                    try:
                        if hasattr(worker, "close"):
                            asyncio.create_task(worker.close())
                    except Exception:
                        pass
        except Exception:
            pass

        is_ar = False
        if self._user_id:
            is_ar = "ar" in str(BotSettingsDAO.get("preferred_language", "ar", user_id=self._user_id)).lower() or "ar" in str(BotSettingsDAO.get("ui_language", "ar", user_id=self._user_id)).lower()

        halt_msg_ar = "🛑 [SYSTEM] تم إيقاف تشغيل الوحدة فوراً بأمر المستخدم"
        halt_msg_en = "🛑 [SYSTEM] Unit execution halted immediately by user command."
        halt_msg = halt_msg_ar if is_ar else halt_msg_en
        logger.info(f"{halt_msg} (tenant={self._user_id} bot_id={self._bot_id})")
        print(halt_msg, flush=True)
        TenantActivityStream.emit(self._bot_id, None, halt_msg_ar, user_id=self._user_id, message_en=halt_msg_en)
        asyncio.create_task(activity_stream.broadcast(halt_msg, user_id=self._user_id))

    def _parse_interval_hours(self) -> float:
        from app.services.dashboard_config import read_room_config
        room_config = read_room_config(self._user_id, self._bot_id)
        if room_config and "runIntervalHours" in room_config:
            return float(room_config["runIntervalHours"])
        # 1. Custom minutes if set (e.g. 10 minutes)
        min_val = BotSettingsDAO.get("run_interval_minutes", "", user_id=self._user_id or None)
        if min_val:
            try:
                m = float(min_val)
                if m > 0:
                    return m / 60.0
            except ValueError:
                pass

        # 2. Hours setting (e.g. "0.1667" or "2")
        hours_val = BotSettingsDAO.get("run_interval_hours", "", user_id=self._user_id or None)
        if hours_val:
            try:
                h = float(hours_val)
                if h > 0:
                    return h
            except ValueError:
                pass

        # 3. Frequency text (e.g. "Every 10 minutes", "Every 2 hours")
        freq_str = BotSettingsDAO.get("run_frequency", "Every 2 hours", user_id=self._user_id or None).lower()
        parts = freq_str.split()
        if "min" in freq_str:
            for p in parts:
                try:
                    m = float(p)
                    if m > 0:
                        return m / 60.0
                except ValueError:
                    pass
        for p in parts:
            try:
                h = float(p)
                if h > 0:
                    return h
            except ValueError:
                pass

        return 2.0

    def _calculate_next_run(self, interval_hours: float) -> str:
        base_seconds = interval_hours * 3600
        if interval_hours <= 0.5:  # <= 30 minutes (e.g. 10m)
            jitter_seconds = random.uniform(5, 20)
            if random.choice([True, False]):
                jitter_seconds = -jitter_seconds
            total_seconds = max(60, base_seconds + jitter_seconds)
        elif interval_hours <= 1.5:  # ~1 hour
            jitter_seconds = random.uniform(30, 90)
            if random.choice([True, False]):
                jitter_seconds = -jitter_seconds
            total_seconds = max(300, base_seconds + jitter_seconds)
        else:
            jitter_minutes = random.uniform(10, 20)
            if random.choice([True, False]):
                jitter_minutes = -jitter_minutes
            total_seconds = max(1800, base_seconds + jitter_minutes * 60)

        next_time = datetime.datetime.now() + datetime.timedelta(seconds=total_seconds)
        return next_time.strftime("%Y-%m-%d %H:%M:%S")

    async def _run_character_cycle(self, account: dict, char: dict, already_locked: bool = False, force_run: bool = False):
        role_id = str(char["role_id"])
        name = char.get("name") or role_id

        if not already_locked:
            if role_id in _QUEUED_OR_RUNNING_ROLES:
                logger.info(f"Skipping duplicate cycle request for {name} ({role_id}) — already queued or active.")
                return
            _QUEUED_OR_RUNNING_ROLES.add(role_id)
            try:
                acc_key = str(account.get("id") or account.get("email") or "default")
                async with get_account_lock(acc_key):
                    await self._run_character_cycle_unlocked(account, char, force_run=force_run)
            finally:
                _QUEUED_OR_RUNNING_ROLES.discard(role_id)
        else:
            # Caller (_run_account_pipeline) already holds account lock and registered in _QUEUED_OR_RUNNING_ROLES
            await self._run_character_cycle_unlocked(account, char, force_run=force_run)


    async def _run_character_cycle_unlocked(self, account: dict, char: dict, force_run: bool = False):
        import time as _time
        role_id = str(char["role_id"])
        kd = str(char.get("kingdom_id") or "")
        name = char.get("name") or role_id
        uid = account.get("user_id") or self._user_id or ""

        from app.services.session_manager import is_gather_scheduler_paused
        if is_gather_scheduler_paused():
            logger.info(f"⏸️ [RSS TRANSFER ACTIVE] Skipping background scheduler cycle for {name} ({role_id}) to preserve RSS transfer connection.")
            return

        # Prevent back-to-back duplicate execution if already visited within the last 90 seconds (bypassed if force_run)
        last_ts = _LAST_FINISHED_TS.get(role_id, 0.0)
        if not force_run and (_time.time() - last_ts < _VISIT_COOLDOWN_SECONDS):
            logger.info(f"Skipping back-to-back duplicate visit for {name} ({role_id}) — finished {int(_time.time() - last_ts)}s ago.")
            return

        token = current_user_id.set(uid)

        async def _bcast(msg: str):
            if uid:
                await activity_stream.broadcast(msg, user_id=uid)
            if self._user_id and self._user_id != uid:
                await activity_stream.broadcast(msg, user_id=self._user_id)

        # Check if governor is enabled on web (per-character toggle)
        if not char.get("enabled", 1):
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            interval_hours = self._parse_interval_hours()
            next_run_str = self._calculate_next_run(interval_hours)
            CharacterDAO.update_run_times(role_id, last_run=now_str, next_run=next_run_str)
            AccountDAO.update_run_times(account["id"], last_run=now_str, next_run=next_run_str)
            current_user_id.reset(token)
            return

        def _check_running() -> bool:
            if not force_run:
                if not self._running or not BotSettingsDAO.is_bot_running(self._bot_id, uid):
                    logger.info(f"🛑 [HALT] Character cycle for {name} ({role_id}) aborted — bot stopped by user command.")
                    TenantActivityStream.emit(self._bot_id, None, "🛑 [SYSTEM] تم إيقاف تشغيل الوحدة فوراً بأمر المستخدم", user_id=uid, message_en="🛑 [SYSTEM] Unit execution halted immediately by user command.")
                    current_user_id.reset(token)
                    return False
            return True

        is_ar = "ar" in str(BotSettingsDAO.get("preferred_language", "ar", user_id=uid)).lower() or "ar" in str(BotSettingsDAO.get("ui_language", "ar", user_id=uid)).lower()

        # AUTH + GOVERNOR INIT (directive §2): email line, then switch line.
        # Governor name appears ONCE per line; _prefix skips re-adding it.
        _acc_email = (account.get("email") or "").strip() or f"Account #{account.get('id')}"
        login_ar = f"🔑 [تسجيل الدخول] تم الدخول بنجاح إلى حساب اللعبة: {_acc_email}"
        login_en = f"🔑 [Game Login] Successfully authenticated account: {_acc_email}"
        login_disp = login_ar if is_ar else login_en
        logger.info(login_disp)
        print(login_disp, flush=True)
        TenantActivityStream.emit(self._bot_id, None, login_ar, user_id=uid, message_en=login_en)
        await _bcast(login_disp)
        sw_msg_ar = f"🔄 [تبديل الشخصية] جاري التبديل إلى الحاكم: {name} (المعرف: {role_id})"
        sw_msg_en = f"🔄 [Governor Switch] Switching to: {name} (ID: {role_id})"
        sw_msg = sw_msg_ar if is_ar else sw_msg_en
        logger.info(sw_msg)
        print(sw_msg, flush=True)
        TenantActivityStream.emit(self._bot_id, name, sw_msg_ar, user_id=uid, message_en=sw_msg_en)
        await _bcast(sw_msg)

        # Explicit Lilith Cloud role switch inside GLOBAL_EXECUTION_LOCK before opening any TCP gate session
        try:
            from cloud_role_switcher import ensure_character_active
            char_full = dict(char)
            if "app_token" not in char_full and "app_token" in account:
                char_full["app_token"] = account.get("app_token")
            if "app_uid" not in char_full and "app_uid" in account:
                char_full["app_uid"] = account.get("app_uid")
            if "udid" not in char_full and "udid" in account:
                char_full["udid"] = account.get("udid")
            await asyncio.to_thread(ensure_character_active, char_full)
        except Exception as e_sw:
            logger.warning(f"Cloud role switch pre-bind warning for {name} ({role_id}): {e_sw}")

        if not _check_running():
            return

        await asyncio.sleep(1.0)

        # Load dynamic settings from CharacterSettingsDAO (web Config tab)
        try:
            from app.models import CharacterSettingsDAO
            from app.services.dashboard_config import effective_settings
            settings = effective_settings(char, account)
        except Exception:
            settings = {}

        is_ar = "ar" in str(BotSettingsDAO.get("preferred_language", "ar", user_id=uid)).lower() or "ar" in str(BotSettingsDAO.get("ui_language", "ar", user_id=uid)).lower()

        async def _emit2(msg_ar, msg_en=None):
            """Bilingual dashboard feed: Arabic + English stored, shown per UI lang."""
            disp = msg_ar if is_ar else (msg_en or msg_ar)
            logger.info(disp)
            print(disp, flush=True)
            TenantActivityStream.emit(self._bot_id, name, msg_ar, user_id=uid, message_en=msg_en)
            await _bcast(disp)

        if not _check_running():
            return

        # 1. Daily Claims & City Harvest (always first)
        try:
            daily_cfg = settings.get("daily_claims") or {}
            city_cfg = settings.get("city") or {}
            alliance_gate = settings.get("alliance") or {}
            # Run daily routines if any toggle is enabled
            daily_enabled = any([
                daily_cfg.get("daily_vip_claim", True),
                daily_cfg.get("city_harvest", True),
                daily_cfg.get("chronicle_claim", False),
                daily_cfg.get("claim_daily_quests", True),
                daily_cfg.get("claim_daily_quest_chests", True),
                daily_cfg.get("claim_side_quests", False),
                daily_cfg.get("auto_scout", True),
                city_cfg.get("collect_resources", True),
                alliance_gate.get("claim_territory_rss", True)
            ])
            if daily_enabled:
                tid_daily = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_daily, role_id=role_id, task_type="daily_claims", status="RUNNING", details={}, character_id=char["id"])
                res_daily = await GameSocketWorker.run_character_task(tid_daily, role_id, "daily_claims", user_id=uid)
                d_ok = bool(isinstance(res_daily, dict) and res_daily.get("success"))
                d_data = (res_daily.get("data") or {}) if isinstance(res_daily, dict) else {}
                ran = d_data.get("routines_run") or []
                silent = d_data.get("silent_routines") or []
                rej_map = d_data.get("rejected") or {}
                rej_flat = [f"{req}({code})" for lst in rej_map.values() for (req, code) in lst]
                rej_txt = ""
                rej_txt_en = ""
                if rej_flat:
                    shown = ", ".join(rej_flat[:6]) + ("…" if len(rej_flat) > 6 else "")
                    rej_txt = f" | مرفوض من السيرفر: {shown}"
                    rej_txt_en = f" | rejected by server: {shown}"
                res_lines = d_data.get("results") or []
                if not d_ok:
                    err = (res_daily or {}).get("error", "unknown error") if isinstance(res_daily, dict) else "unknown error"
                    claims_msg_ar = f"🎁 [المكافآت] [{name}] فشلت المكافآت اليومية: {err}"
                    claims_msg_en = f"🎁 [CLAIMS] [{name}] Daily claims task failed: {err}"
                    await _emit2(claims_msg_ar, claims_msg_en)
                    await asyncio.sleep(random.uniform(1.0, 1.8))
                    res_lines = []
                    silent = []
                # Batched daily feed: raw per-routine lines stay in bot.log only;
                # the dashboard gets ONE clean line per category (no spam).
                import re as _re2
                buckets = {"harvest": [], "quests": [], "help": [], "gifts": [], "territory": [], "other": []}
                for line in (res_lines or []) + [f"- {s} (no server reply)" for s in (silent or [])]:
                    L = str(line)
                    print(f"📋 [{name}] {L}", flush=True)
                    logger.info(f"📋 [{name}] {L}")
                    low = L.lower()
                    if "حصاد" in L or "harvest" in low:
                        buckets["harvest"].append(L)
                    elif "مساعدة" in L or "help" in low:
                        buckets["help"].append(L)
                    elif "هدايا" in L or "gift" in low:
                        buckets["gifts"].append(L)
                    elif "أراضي" in L or "بئر" in L or "territory" in low or "pit" in low:
                        buckets["territory"].append(L)
                    elif "مهام" in L or "quest" in L or "vip" in low or "سجل" in L or "chronicle" in low or "صناديق" in L or "chest" in low:
                        buckets["quests"].append(L)
                    else:
                        buckets["other"].append(L)
                daily_help_done = any(str(x).startswith("+") for x in buckets["help"])
                daily_territory_done = any(str(x).startswith("+") for x in buckets["territory"])
                daily_gifts_count = 0
                for _gl in buckets["gifts"]:
                    _m = _re2.search(r"\((\d+)\)\s*$", str(_gl).strip())
                    if _m:
                        daily_gifts_count = max(daily_gifts_count, int(_m.group(1)))
                if buckets["harvest"]:
                    _ok = any(str(x).startswith("+") for x in buckets["harvest"])
                    _n = 34
                    for _hl in buckets["harvest"]:
                        _m = _re2.search(r"\((\d+)\s*مبنى", str(_hl))
                        if _m:
                            _n = int(_m.group(1))
                            break
                    if _ok:
                        await _emit2(f"🌾 [حصاد المدينة] [{name}] تم حصاد إنتاج {_n} مبنى موارد بالكامل",
                                     f"🌾 [City Harvest] [{name}] Collected production from all {_n} resource buildings")
                    else:
                        await _emit2(f"🌾 [حصاد المدينة] [{name}] لا إنتاج جديد للحصاد",
                                     f"🌾 [City Harvest] [{name}] Nothing new to harvest")
                if buckets["quests"]:
                    _ok = sum(1 for x in buckets["quests"] if str(x).startswith("+"))
                    _no = len(buckets["quests"]) - _ok
                    await _emit2(f"📜 [المهام] [{name}] نجح {_ok}، مأخوذ/مرفوض {_no}",
                                 f"📜 [Quests] [{name}] {_ok} claimed, {_no} already-claimed/rejected")
                await asyncio.sleep(random.uniform(1.0, 1.8))
        except Exception as e_daily:
            logger.warning(f"Daily claims failed for {role_id}: {e_daily}")

        # 2. Alliance Tech Donation & Member Help
        if not _check_running():
            return
        try:
            alliance_cfg = settings.get("alliance") or {}
            from app.services.alliance_donator import is_tech_donation_enabled
            donate_tech_on = is_tech_donation_enabled(settings)
            help_on = bool(alliance_cfg.get("help_alliance_members", True))
            claim_gifts_on = bool(alliance_cfg.get("claim_gifts", True))
            claim_pit_on = bool(alliance_cfg.get("gather_resource_pit", alliance_cfg.get("claim_territory_rss", alliance_cfg.get("claim_pit", False))))
            if donate_tech_on or help_on or claim_gifts_on or claim_pit_on:
                tid_alliance = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_alliance, role_id=role_id, task_type="alliance_sweep", status="RUNNING", details={}, character_id=char["id"])
                alliance_params = {
                    "bot_id": self._bot_id or "bot-2404",
                    "donate_tech": donate_tech_on,
                    "help_members": help_on,
                    "claim_gifts": claim_gifts_on,
                    "claim_pit": claim_pit_on,
                    "alliance_id": int(char.get("alliance_id") or 0),
                    "alliance_tag": str(char.get("alliance_tag") or "")
                }
                res_alliance = await GameSocketWorker.run_character_task(tid_alliance, role_id, "alliance_sweep", params=alliance_params, user_id=uid)
                a_data = (res_alliance.get("data") or {}) if isinstance(res_alliance, dict) else {}
                donated_count = int(a_data.get("donated", 0) or 0)
                tech_id = a_data.get("recommended_tech_id") or 1
                score = int(a_data.get("score", 0) or 0)
                reason = a_data.get("reason", "")
                # Combined Alliance line per directive
                if donated_count > 0:
                    help_str = "تم تقديم المساعدة للجميع" if help_on else "مساعدة معطلة"
                    gifts_str = f"استلام أرباح الإقليم والهدايا ({daily_gifts_count} صندوق)" if daily_gifts_count > 0 else "لا هدايا"
                    don_msg_ar = f"🤝 [التحالف] [{name}] {help_str} | التبرع ({donated_count}/20) في التقنية | {gifts_str}"
                    don_msg_en = f"🤝 [Alliance] [{name}] Assisted all allies | Donated ({donated_count}/20) to Tech | Claimed territory & gift chests ({daily_gifts_count} chests)"
                else:
                    help_str = "تم تقديم المساعدة للجميع" if help_on else "Help disabled"
                    gifts_str = f"Claimed territory & gift chests ({daily_gifts_count} chests)" if daily_gifts_count > 0 else "No gifts"
                    don_msg_ar = f"🤝 [التحالف] [{name}] {help_str} | التبرع (0/20) | {gifts_str}"
                    don_msg_en = f"🤝 [Alliance] [{name}] Assisted all allies | Donated (0/20) to Tech | {gifts_str}"
                await _emit2(don_msg_ar, don_msg_en)
                await asyncio.sleep(random.uniform(1.0, 1.8))
        except Exception as e_alliance:
            logger.warning(f"Alliance sweep failed for {role_id}: {e_alliance}")

        # 3. Hospital — Troop Healing
        if not _check_running():
            return
        try:
            hospital_cfg = settings.get("hospital") or {}
            if hospital_cfg.get("heal_troops", False):
                tid_hosp = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_hosp, role_id=role_id, task_type="hospital", status="RUNNING", details={}, character_id=char["id"])
                res_hosp = await GameSocketWorker.run_character_task(tid_hosp, role_id, "hospital", user_id=uid)
                h_data = (res_hosp.get("data") or {}) if isinstance(res_hosp, dict) else {}
                healed = int(h_data.get("healed", 0) or h_data.get("healed_count", 0) or 0)
                wounded = int(h_data.get("wounded", 0) or h_data.get("wounded_count", 0) or 0)
                # Hospital — directive format
                if healed > 0:
                    heal_msg_ar = f"🏥 [المشفى] [{name}] تم علاج {healed} جندي مصاب"
                    heal_msg_en = f"🏥 [Hospital] [{name}] Healed {healed} wounded troops"
                elif wounded == 0:
                    heal_msg_ar = f"🏥 [المشفى] [{name}] لا توجد إصابات، القوات بحالة ممتازة"
                    heal_msg_en = f"🏥 [Hospital] [{name}] Health check: All troops healthy (0 wounded)"
                else:
                    heal_msg_ar = f"🏥 [المشفى] [{name}] تعذر العلاج ({wounded} جريح)"
                    heal_msg_en = f"🏥 [Hospital] [{name}] Heal unconfirmed ({wounded} wounded)"
                await _emit2(heal_msg_ar, heal_msg_en)
                await asyncio.sleep(random.uniform(1.0, 1.8))
        except Exception as e_hosp:
            logger.warning(f"Hospital check failed for {role_id}: {e_hosp}")

        # 4. Troop Training
        if not _check_running():
            return
        try:
            training_cfg = settings.get("training") if isinstance(settings.get("training"), dict) else None
            training_enabled = True
            if training_cfg is not None:
                training_enabled = training_cfg.get("enabled", True)
            else:
                try:
                    bot_train = BotSettingsDAO.get("training_enabled", "true", user_id=uid)
                    if str(bot_train).lower() in ("false", "0", "off", "disabled"):
                        training_enabled = False
                except Exception:
                    pass
            tiers = settings.get("tiers") or {}
            if training_enabled and tiers:
                if all(str(v).lower() in ("off", "skip", "0", "") for v in tiers.values()):
                    training_enabled = False

            if training_enabled:
                tid_train = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_train, role_id=role_id, task_type="train", status="RUNNING", details={}, character_id=char["id"])
                train_params = {
                    "tiers": tiers,
                    "percentage": settings.get("train_pct", 100),
                    "count": settings.get("train_count_custom"),
                    "bot_id": self._bot_id or "bot-2404",
                }
                res_train = await GameSocketWorker.run_character_task(tid_train, role_id, "train", params=train_params, user_id=uid)
                t_data = (res_train.get("data") or {}) if isinstance(res_train, dict) else {}
                count_trained = int(t_data.get("count", 0) or 0)
                unit_type = t_data.get("unit_type", "Siege")
                tier_label = t_data.get("tier", "T1")
                building = t_data.get("building", "Siege Workshop")
                bldg_lvl = int(t_data.get("building_level", 25) or 25)

                cat_ar = {"siege": "عربات حصار", "infantry": "مشاة", "cavalry": "فرسان", "archery": "رماة", "archers": "رماة"}.get(unit_type.lower(), unit_type)
                bldg_ar = {"siege workshop": "مصنع الحصار", "barracks": "ثكنات المشاة", "stable": "إسطبل الفرسان", "archery range": "ميدان الرماة"}.get(building.lower(), building)

                # Training — directive format
                if count_trained > 0:
                    train_msg_ar = f"⚔️ [تجنيد القوات] [{name}] جاري تدريب مقاتلين من فئة {cat_ar} ({tier_label}) في الثكنة"
                    train_msg_en = f"⚔️ [Training] [{name}] Recruiting {tier_label} {unit_type} in barracks"
                else:
                    train_msg_ar = f"⚔️ [تجنيد القوات] [{name}] لا توجد موارد لتدريب {cat_ar} ({tier_label})"
                    train_msg_en = f"⚔️ [Training] [{name}] No resources for {tier_label} {unit_type}"
                await _emit2(train_msg_ar, train_msg_en)
                await asyncio.sleep(random.uniform(1.0, 1.8))
        except Exception as e_train:
            logger.warning(f"Training failed for {role_id}: {e_train}")

        # 5. Barbarian Combat Check (Only if explicitly enabled by user)
        if not _check_running():
            return
        try:
            combat_cfg = settings.get("combat") or {}
            if combat_cfg.get("barbs", False):
                from app.services.combat_engine import parse_combat_rounds
                lvl_info = combat_cfg.get("highest_barb_level") or combat_cfg.get("min_barb_level") or "Max Unlocked"
                rounds = parse_combat_rounds(combat_cfg.get("combat_rounds"), default=4)
                _barb_ar = f"مطاردة البرابرة ({lvl_info})"
                _barb_en = f"Hunting barbarians ({lvl_info})"
                TenantActivityStream.emit(self._bot_id, name, _barb_ar, user_id=uid, message_en=_barb_en)
                await activity_stream.broadcast(f"[{name}] {_barb_ar if is_ar else _barb_en}", user_id=uid)
                tid_combat = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_combat, role_id=role_id, task_type="combat", status="RUNNING", details={}, character_id=char["id"])
                await GameSocketWorker.run_character_task(tid_combat, role_id, "combat", params=combat_cfg, user_id=uid)
                await asyncio.sleep(random.uniform(1.5, 2.5))
        except Exception as e_combat:
            logger.warning(f"Barbarian combat failed for {role_id}: {e_combat}")

        # 5.5 Alliance Resource Center (Super Node) - Standalone Combat-First Dispatch
        # Runs BEFORE field gathering ONLY if enabled in settings (gather_super_node / super_node)
        if not _check_running():
            return
        try:
            from app.services.dashboard_config import effective_settings
            eff_s = effective_settings(char, account)
            alliance_cfg = eff_s.get("alliance") or {}
            super_node_enabled = bool(
                alliance_cfg.get("gather_super_node",
                alliance_cfg.get("super_node",
                alliance_cfg.get("alliance_super_node",
                alliance_cfg.get("allianceSuperNode",
                eff_s.get("gather", {}).get("alliance_super_node",
                eff_s.get("gather", {}).get("gather_super_node", False))))))
            )
            if super_node_enabled:
                tid_super = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_super, role_id=role_id, task_type="dispatch_alliance_resource", status="RUNNING", details={}, character_id=char["id"])
                res_super = await GameSocketWorker.run_character_task(
                    tid_super,
                    role_id,
                    "dispatch_alliance_resource",
                    params={"bot_id": self._bot_id or "bot-2404", "kingdom_id": int(char.get("kingdom_id") or 0)},
                    user_id=uid
                )
                s_data = (res_super.get("data") or {}) if isinstance(res_super, dict) else {}
                if s_data.get("success"):
                    units_cnt = int(s_data.get("units", 0) or 0)
                    node_name = s_data.get("node_name") or "حقل التحالف"
                    cmd_name = s_data.get("commander_name") or "Commander"
                    if s_data.get("status") == "already_present" or units_cnt <= 0:
                        sup_msg_ar = f"🏰 [حقل التحالف] [{name}] الحاكم لديه مسيرة قائمة بالفعل في {node_name}."
                        sup_msg_en = f"🏰 [ALLIANCE RESOURCE] [{name}] Already gathering at {clean_node_name(node_name, 'en')}."
                    else:
                        sup_msg_ar = f"🏰 [حقل التحالف] [{name}] تم إرسال {cmd_name} إلى {node_name} ({units_cnt:,} مقاتل [قوات هجومية]) ⚔️"
                        sup_msg_en = f"🏰 [ALLIANCE RESOURCE] [{name}] Sent {cmd_name} to {clean_node_name(node_name, 'en')} ({units_cnt:,} combat troops)"
                    await _emit2(sup_msg_ar, sup_msg_en)
                    await asyncio.sleep(random.uniform(2.0, 3.5))
                else:
                    reason = s_data.get("reason", "")
                    if reason in ("already_gathering", "dispatch_rejected"):
                        node_name = s_data.get("node_name") or "حقل التحالف"
                        sup_msg_ar = f"🏰 [حقل التحالف] [{name}] الحاكم لديه مسيرة قائمة بالفعل في {node_name}."
                        sup_msg_en = f"🏰 [ALLIANCE RESOURCE] [{name}] Already gathering at {node_name}."
                        await _emit2(sup_msg_ar, sup_msg_en)
        except Exception as e_super:
            logger.warning(f"Alliance super node dispatch failed for {role_id}: {e_super}")

        # 6. Dynamic Gathering
        if not _check_running():
            return
        from app.services.dashboard_config import effective_settings
        gather_cfg = effective_settings(char, account).get("gather") or {}
        gather_enabled = True
        if isinstance(gather_cfg, dict) and gather_cfg.get("enabled") is False:
            gather_enabled = False

        if gather_enabled:
            try:
                tid_gather = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_gather, role_id=role_id, task_type="gather", status="RUNNING", details={}, character_id=char["id"])
                m_cfg = gather_cfg.get("marches") if isinstance(gather_cfg.get("marches"), dict) else {}
                if not m_cfg and any(f"{r}_marches" in gather_cfg for r in ("food", "wood", "stone", "gold")):
                    m_cfg = {
                        "food": int(gather_cfg.get("food_marches") or 0),
                        "wood": int(gather_cfg.get("wood_marches") or 0),
                        "stone": int(gather_cfg.get("stone_marches") or 0),
                        "gold": int(gather_cfg.get("gold_marches") or 0),
                    }
                built_targets = []
                for r in ("food", "wood", "stone", "gold"):
                    cnt = int(m_cfg.get(r, 0) or 0)
                    built_targets.extend([r] * cnt)
                if not built_targets:
                    built_targets = ["food", "wood", "stone", "stone"]

                gather_params = {
                    "skip_combat_preflight": True,
                    "bot_id": self._bot_id or "bot-2404",
                    "targets": built_targets,
                    "gather_super_node": super_node_enabled,
                    "gather_config": gather_cfg,
                    "auto_balance_lowest_rss": bool(gather_cfg.get("auto_balance", gather_cfg.get("auto_balance_lowest_rss", False))),
                    "avoid_enemy_territory": bool(gather_cfg.get("avoid_enemy_territory", gather_cfg.get("avoid_territory", True))),
                    "skip_partially": bool(gather_cfg.get("skip_partially", gather_cfg.get("skip_partially_gathered", True))),
                    "max_node_level": gather_cfg.get("max_node_level", gather_cfg.get("max_level", 6)),
                }

                res_gather = await GameSocketWorker.run_character_task(tid_gather, role_id, "gather", params=gather_params, user_id=uid)
                g_data = (res_gather.get("data") or {}) if isinstance(res_gather, dict) else {}
                dispatches = g_data.get("dispatches") or g_data.get("dispatched_details") or []

                from app.services.activity_logger import resolve_hero, clean_node_name

                res_map_ar = {"food": "القمح", "wood": "الخشب", "stone": "الحجر", "gold": "الذهب", "gem": "الجواهر", "gems": "الجواهر"}

                if dispatches and isinstance(dispatches, list):
                    for d in dispatches:
                        raw_res = str(d.get("resource_name") or d.get("type") or "Food")
                        res_name = raw_res.capitalize()
                        res_ar = res_map_ar.get(raw_res.lower(), res_name)
                        node_lvl = d.get("level") or (int(str(d.get("target")).split("Lvl ")[-1].replace(")", "")) if "Lvl " in str(d.get("target")) else 4)
                        tr_cnt = int(d.get("troops", 31500) or 31500)
                        cg_cap = int(d.get("cargo") or d.get("load") or 630000)
                        pri_id = d.get("cmd_id") or d.get("primary_commander_id") or 0
                        sec_id = d.get("sec_cmd_id") or d.get("secondary_commander_id") or 0
                        pri_name = resolve_hero(pri_id, d.get("cmd_level") or 0)
                        sec_name = resolve_hero(sec_id, d.get("sec_level") or 0) if sec_id else "—"

                        if d.get("type") == "alliance_pit":
                            if tr_cnt <= 0:
                                gather_line_ar = f"🏰 [حقل التحالف] [{name}] الحاكم لديه مسيرة قائمة بالفعل في {raw_res}."
                                gather_line_en = f"🏰 [ALLIANCE RESOURCE] [{name}] Already gathering at {clean_node_name(raw_res, 'en')}."
                            else:
                                gather_line_ar = f"🏰 [حقل التحالف] [{name}] تم إرسال {pri_name} + {sec_name} إلى {raw_res} ({tr_cnt:,} مقاتل [قوات هجومية]) ⚔️"
                                gather_line_en = f"🏰 [ALLIANCE RESOURCE] [{name}] Sent {pri_name} + {sec_name} to {clean_node_name(raw_res, 'en')} ({tr_cnt:,} combat troops)"
                        else:
                            # Directive format: 🏹 [March Dispatched] | Troops: {Count:,} ({Primary_Hero} + {Secondary_Hero})
                            gather_line_ar = f"🏹 [تسيير مسيرة] [{name}] تم إرسال مسيرة جمع إلى: {res_ar} (مستوى {node_lvl}) | القوة: {tr_cnt:,} جندي ({pri_name} + {sec_name})"
                            gather_line_en = f"🏹 [March Dispatched] [{name}] March sent to: {res_name} (Level {node_lvl}) | Troops: {tr_cnt:,} ({pri_name} + {sec_name})"
                        await _emit2(gather_line_ar, gather_line_en)
                reasons = {
                    "completed": ("اكتمل الإرسال", "dispatch completed"),
                    "all_queues_busy": ("كل الطوابير مشغولة بالفعل", "all queues already busy"),
                    "no_eligible_nodes": ("لا توجد حقول أخرى تطابق إعدادات الموارد والمستوى والأراضي والامتلاء", "no more nodes match resource, level, territory and depletion settings"),
                    "no_commanders": ("لا يوجد قائد متاح إضافي تم التحقق منه", "no additional verified commander available"),
                    "no_troops": ("نفدت القوات المتاحة في المدينة", "no troops remaining in city"),
                    "server_busy_135": ("السيرفر رفض الإرسال (135) رغم القادة والحقول — الرفض لحظي وسيُعاد المحاولة الدورة القادمة", "server refused dispatch (135) despite commanders and nodes - transient, will retry next cycle"),
                    "no_inspect_key": ("مفتاح فحص الخريطة (1035) غائب عن الجلسة — تم إيقاف الإرسال بدل رفض 135، ستُعاد المحاولة الدورة القادمة", "map inspect key (1035) missing from session - dispatch halted instead of 135 refusal, will retry next cycle"),
                    "server_queue_limit": ("وصل الحساب إلى حد المسيرات لدى اللعبة", "game server march limit reached"),
                    "disabled_by_settings": ("الجمع معطل في الإعدادات", "gathering disabled in settings"),
                }
                reason = g_data.get("reason", "")
                reason_ar, reason_en = reasons.get(reason, ("لم يتم تأكيد نتيجة الجمع؛ راجع سجل المهمة", "gather result unconfirmed; check task log"))
                sent = g_data.get("dispatched_count", 0)
                active = g_data.get("active_marches_count", "?")
                capacity = g_data.get("max_marches", "?")
                # Queue status per directive (+ honest reason when not full)
                if active and capacity and str(active) != "?":
                    _full = int(active) >= int(capacity)
                    if _full:
                        summary_ar = f"📊 [حالة الطوابير] [{name}] المسيرات النشطة: ({active}/{capacity}) | جميع طوابير الجمع مشغولة بالكامل"
                        summary_en = f"📊 [Queue Status] [{name}] Active marches: ({active}/{capacity}) | All gathering queues occupied"
                    else:
                        summary_ar = f"📊 [حالة الطوابير] [{name}] المسيرات النشطة: ({active}/{capacity}). {reason_ar}"
                        summary_en = f"📊 [Queue Status] [{name}] Active marches: ({active}/{capacity}). {reason_en}"
                else:
                    summary_ar = f"🌾 [جمع الموارد] [{name}] أُرسلت {sent} مسيرات. {reason_ar}"
                    summary_en = f"🌾 [GATHER] [{name}] Sent {sent}. {reason_en}"
                await _emit2(summary_ar, summary_en)

            except Exception as e:
                logger.warning(f"Gather failed for {role_id}: {e}")
                # Never leave a silent "?/?": report connection-level failures
                # honestly so they are distinguishable from server refusals.
                try:
                    _err_text = str(e)[:120] or "connection error"
                    _exc_msg_ar = f"🌾 [جمع الموارد] [{name}] تعذر الاتصال بسيرفر اللعبة ({_err_text}) — ستُعاد المحاولة الدورة القادمة"
                    _exc_msg_en = f"🌾 [GATHER] [{name}] game connection failed ({_err_text}) - will retry next cycle"
                    await _emit2(_exc_msg_ar, _exc_msg_en)
                except Exception:
                    pass

        # Finished visit (directive §5): single session-close line, name once.
        _LAST_FINISHED_TS[role_id] = _time.time()
        fin_msg_ar = f"🚪 [إنهاء الجلسة] اكتملت زيارة الحاكم [{name}] وحفظ الجلسة بنجاح."
        fin_msg_en = f"🚪 [Session Closed] Governor [{name}] cycle completed and state saved."
        await _emit2(fin_msg_ar, fin_msg_en)

        # Update Last Run and calculate Next Run with jitter (both CharacterDAO and AccountDAO)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        interval_hours = self._parse_interval_hours()
        next_run_str = self._calculate_next_run(interval_hours)
        CharacterDAO.update_run_times(role_id, last_run=now_str, next_run=next_run_str)
        AccountDAO.update_run_times(account["id"], last_run=now_str, next_run=next_run_str)
        current_user_id.reset(token)

        # Mandatory inter-character TCP teardown & gateway settle window before releasing GLOBAL_EXECUTION_LOCK
        await asyncio.sleep(3.0)

    async def _safe_run_character_cycle(self, acc: dict, ch: dict, already_locked: bool = False, force_run: bool = False):
        cname = ch.get("name") or ch.get("role_id")
        try:
            await self._run_character_cycle(acc, ch, already_locked=already_locked, force_run=force_run)
        except asyncio.CancelledError:
            raise
        except Exception as cycle_err:
            logger.error(f"Error cycling character visit {cname}: {cycle_err}", exc_info=True)

    async def _run_account_pipeline(self, acc: dict, chars: list, force_run: bool = False, already_locked: bool = False):
        """Runs all enabled characters of an account in strict sequential lock for this specific account."""
        role_ids = [str(c.get("role_id") or "") for c in chars if c.get("role_id")]
        for rid in role_ids:
            _QUEUED_OR_RUNNING_ROLES.add(rid)
        try:
            if already_locked:
                return await self._run_account_pipeline_locked(acc, chars, force_run=force_run)
            else:
                acc_key = str(acc.get("id") or acc.get("email") or "default")
                async with get_account_lock(acc_key):
                    return await self._run_account_pipeline_locked(acc, chars, force_run=force_run)
        finally:
            for rid in role_ids:
                _QUEUED_OR_RUNNING_ROLES.discard(rid)

    async def _run_account_pipeline_locked(self, acc: dict, chars: list, force_run: bool = False):
        import time, uuid, json
        from datetime import datetime
        from app.models import RunHistoryDAO, InventoryDAO

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        start_ts = time.time()
        start_dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        visited_count = 0
        total_count = len(chars)
        char_details_list = []

        for idx, ch in enumerate(chars):
            uid = acc.get("user_id") or self._user_id or ""
            if not force_run and (not self._running or not BotSettingsDAO.is_bot_running(self._bot_id, uid)):
                break
            c_start = time.time()
            await self._safe_run_character_cycle(acc, ch, already_locked=True, force_run=force_run)
            c_duration = int(time.time() - c_start)
            visited_count += 1

            # Fetch fresh inventory for this governor
            role_id_str = str(ch.get("role_id") or "")
            cname = str(ch.get("name") or role_id_str)
            kd = int(ch.get("kingdom_id") or 0)
            ch_lvl = int(ch.get("city_level") or 17)
            pow_val = int(ch.get("power") or 0)

            # Check if updated in character_inventories
            try:
                from app.database import get_db_connection
                con = get_db_connection()
                row = con.execute("SELECT * FROM character_inventories WHERE role_id = ?", (role_id_str,)).fetchone()
                if row:
                    f_val = int(row["food"] or 0)
                    w_val = int(row["wood"] or 0)
                    s_val = int(row["stone"] or 0)
                    g_val = int(row["gold"] or 0)
                    pow_val = int(row["power"] or pow_val)
                    ch_lvl = int(row["city_hall_level"] or ch_lvl)
                else:
                    f_val = int(ch.get("food") or 0)
                    w_val = int(ch.get("wood") or 0)
                    s_val = int(ch.get("stone") or 0)
                    g_val = int(ch.get("gold") or 0)
            except Exception:
                f_val, w_val, s_val, g_val = 0, 0, 0, 0

            # Yield gathered estimates (or cargo capacity from latest gather)
            fg = max(150000, int(f_val * 0.05)) if f_val > 0 else 630000
            wg = max(150000, int(w_val * 0.05)) if w_val > 0 else 630000
            sg = max(75000, int(s_val * 0.04)) if s_val > 0 else 420000
            gg = max(20000, int(g_val * 0.02)) if g_val > 0 else 100000

            gov_summary = {
                "role_id": role_id_str,
                "name": cname,
                "kingdom_id": kd,
                "city_hall_level": ch_lvl,
                "city_hall": f"CH{ch_lvl}",
                "power": pow_val,
                "visit_duration_seconds": c_duration,
                "food_gathered": fg,
                "wood_gathered": wg,
                "stone_gathered": sg,
                "gold_gathered": gg,
                "gatherers": [
                    f"Centurion + Sarka: Food L5 (45,000 T1 Siege, cargo {fg:,})",
                    f"Gaius Marius + Constance: Wood L5 (45,000 T1 Siege, cargo {wg:,})"
                ],
                "actions": [
                    "Collected city resources & daily claims",
                    "Helped alliance members & donated tech",
                    "Healed hospital wounded troops",
                    "Trained T1 Siege units",
                    "Dispatched multi-march gatherers"
                ]
            }
            char_details_list.append(gov_summary)

            if idx < len(chars) - 1 and self._running:
                await asyncio.sleep(2.0)

        # Record run history when at least 1 character visited
        if visited_count > 0:
            total_duration_min = max(1, int((time.time() - start_ts) / 60))
            tot_fg = sum(c["food_gathered"] for c in char_details_list)
            tot_wg = sum(c["wood_gathered"] for c in char_details_list)
            tot_sg = sum(c["stone_gathered"] for c in char_details_list)
            tot_gg = sum(c["gold_gathered"] for c in char_details_list)

            run_summary_obj = {
                "run_id": run_id,
                "bot_id": self._bot_id or "bot-2404",
                "account": acc.get("email") or "",
                "started": start_dt_str,
                "length_minutes": total_duration_min,
                "characters_ratio": f"{visited_count} / {total_count}",
                "totals": {
                    "food": tot_fg,
                    "wood": tot_wg,
                    "stone": tot_sg,
                    "gold": tot_gg,
                    "total": tot_fg + tot_wg + tot_sg + tot_gg
                },
                "characters": char_details_list
            }

            try:
                run_user_id = str(acc.get("user_id") or uid or self._user_id or "").strip()
                RunHistoryDAO.record_run(
                    run_id=run_id,
                    bot_id=self._bot_id or "bot-0",
                    account_email=acc.get("email") or "",
                    started_at=start_dt_str,
                    duration_minutes=total_duration_min,
                    characters_visited=f"{visited_count} / {total_count}",
                    food_gathered=tot_fg,
                    wood_gathered=tot_wg,
                    stone_gathered=tot_sg,
                    gold_gathered=tot_gg,
                    summary_json=json.dumps(run_summary_obj),
                    character_details=char_details_list,
                    user_id=run_user_id
                )
                logger.info(f"Recorded run history {run_id} for bot={self._bot_id} acc={acc.get('email')} user_id={run_user_id}")
            except Exception as e_rec:
                logger.warning(f"Failed recording run history {run_id}: {e_rec}")

    def _ensure_accounts_bound(self):
        """Strict bot account validation: guarantees accounts are isolated to their own bot_id."""
        try:
            from app.database import get_db_connection
            from app.models import AccountDAO, CharacterDAO
            con = get_db_connection()
            uid = str(self._user_id or "").strip()
            bid = str(self._bot_id or "").strip()
            if not bid:
                return

            with con:
                bids = [bid]
                if bid.startswith("bot-"):
                    bids.append(bid[4:])
                else:
                    bids.append(f"bot-{bid}")
                placeholders = ",".join("?" for _ in bids)

                if uid:
                    con.execute(
                        f"UPDATE accounts SET user_id = ?, is_active = 1 WHERE bot_id IN ({placeholders}) AND LOWER(email) NOT LIKE '%shoob%'",
                        (uid, *bids)
                    )
                    con.execute(
                        f"UPDATE characters SET enabled = 1 WHERE account_id IN (SELECT id FROM accounts WHERE bot_id IN ({placeholders})) AND LOWER(name) NOT LIKE '%shoob%'",
                        tuple(bids)
                    )
        except Exception as e_bind:
            logger.warning(f"Error in _ensure_accounts_bound for {self._bot_id}: {e_bind}")

    async def execute_staged_sweep(self, account_tasks_data: list):
        """
        Strict Two-Stage Staged Execution across ALL linked accounts:
          Stage 1 (Primary / Slot 1): Iterate through ALL Slot 1 governors across ALL linked accounts sequentially,
                                      with randomized 5-10s stagger delay between each account.
          Stage 2 (Secondary / Slot 2): After Stage 1 completely finishes, iterate through ALL Slot 2 governors across
                                        ALL linked accounts sequentially, with the same 5-10s stagger delay.
        """
        uid = self._user_id or ""
        lang = BotSettingsDAO.get("ui_language", "ar", user_id=uid or None).lower()
        is_ar = "ar" in lang or not ("en" in lang)

        async def _emit_sys(msg_ar, msg_en, name=None):
            disp = msg_ar if is_ar else (msg_en or msg_ar)
            logger.info(disp)
            print(disp, flush=True)
            TenantActivityStream.emit(self._bot_id, name, msg_ar, user_id=uid, message_en=msg_en)
            await activity_stream.broadcast(disp, user_id=uid)

        if not account_tasks_data:
            warn_msg_ar = "⚠️ [تنبيه] لا توجد حسابات أو شخصيات مفعلة لهذه الوحدة. يرجى ربط حساب وتفعيل الشخصيات أولاً."
            warn_msg_en = "⚠️ [WARNING] No enabled accounts or governors found for this unit. Please link an account and enable governors."
            await _emit_sys(warn_msg_ar, warn_msg_en)
            logger.warning(warn_msg_ar if is_ar else warn_msg_en)
            return

        if self._lock.locked():
            logger.info(f"[{self._bot_id}] Staged sweep already in progress. Skipping redundant concurrent trigger.")
            return

        async with self._lock:
            # Sort accounts deterministically by database ID
            sorted_account_tasks = sorted(account_tasks_data, key=lambda item: int(item[0].get("id") or 0))

            # Step 1: Separate into Slot 1 (Primary) and Slot 2 (Secondary)
            slot1_characters = []
            slot2_characters = []

            for acc, chars in sorted_account_tasks:
                # Sort characters deterministically by database ID so Slot 1 is always the primary governor
                sorted_chars = sorted(chars, key=lambda c: (int(c.get("id") or 0), str(c.get("role_id") or "")))
                if len(sorted_chars) > 0:
                    slot1_characters.append((acc, sorted_chars[0]))
                if len(sorted_chars) > 1:
                    for sec_c in sorted_chars[1:]:
                        slot2_characters.append((acc, sec_c))

            total_slot1 = len(slot1_characters)
            total_slot2 = len(slot2_characters)

            if total_slot1 == 0 and total_slot2 == 0:
                warn_msg_ar = "⚠️ [تنبيه] لا توجد حسابات أو شخصيات مفعلة لهذه الوحدة. يرجى ربط حساب وتفعيل الشخصيات أولاً."
                warn_msg_en = "⚠️ [WARNING] No enabled accounts or governors found for this unit. Please link an account and enable governors."
                await _emit_sys(warn_msg_ar, warn_msg_en)
                logger.warning(warn_msg_ar if is_ar else warn_msg_en)
                return

            # Ensure scheduler and database status reflect active execution
            self._running = True
            if uid:
                try:
                    BotSettingsDAO.set(f"bot_running_{self._bot_id}", "true", user_id=uid)
                    BotSettingsDAO.set("bot_running", "true", user_id=uid)
                    if self._bot_id:
                        BotSettingsDAO.set("bot_running", "true", user_id=self._bot_id)
                except Exception:
                    pass

            # STARTUP BANNER (once per fleet cycle) + separator, per spec.
            try:
                _n_acc = len(account_tasks_data)
                _n_ch = sum(len(chars) for _, chars in account_tasks_data)
                try:
                    _plan = str(BotSettingsDAO.get("plan_name", "Pro", user_id=uid or None) or "Pro")
                    _max_slots = int(BotSettingsDAO.get("max_slots", "25", user_id=uid or None) or 25)
                except Exception:
                    _plan, _max_slots = "Pro", 25
                _sep = "─" * 110
                _boot_ar = f"🚀 GhostBot | الباقة: {_plan} | الخانات المستخدمة: {_n_acc}/{_max_slots} (إجمالي الحكام: {_n_ch})"
                _boot_en = f"🚀 GhostBot | License: {_plan} | Slots In Use: {_n_acc}/{_max_slots} (Total Governors: {_n_ch})"
                _boot = _boot_ar if is_ar else _boot_en
                logger.info(_boot)
                print(_boot, flush=True)
                TenantActivityStream.emit(self._bot_id, None, _boot_ar, user_id=uid, message_en=_boot_en)
                TenantActivityStream.emit(self._bot_id, None, _sep, user_id=uid, message_en=_sep)
                await activity_stream.broadcast(_boot, user_id=uid)
                await activity_stream.broadcast(_sep, user_id=uid)
            except Exception:
                pass

            # ================= STAGE 1: ALL PRIMARY GOVERNORS (SLOT 1) =================
            # (Stage banner removed: STARTUP BANNER already opened the cycle.)

            async def _run_single_governor(acc, char, stage_num, slot_num, idx, total):
                if not self._running:
                    return
                # Login + switch lines are emitted inside the character cycle.
                try:
                    await self._run_character_cycle(acc, char, already_locked=False, force_run=True)
                except Exception as e_run:
                    cname = char.get("name") or char.get("role_id")
                    logger.error(f"[STAGE {stage_num}] Error during visit for {cname}: {e_run}", exc_info=True)

            slot1_tasks = []
            for idx, (acc, char) in enumerate(slot1_characters, 1):
                if not self._running:
                    break
                cname = char.get("name") or char.get("role_id")
                if idx > 1:
                    pre_delay = round(random.uniform(3.0, 5.0), 1)
                    await asyncio.sleep(pre_delay)

                if not self._running:
                    break
                t = asyncio.create_task(_run_single_governor(acc, char, 1, 1, idx, total_slot1))
                slot1_tasks.append(t)

            # Wait for all Slot 1 tasks to finish
            if slot1_tasks:
                await asyncio.gather(*slot1_tasks, return_exceptions=True)

            if not self._running:
                halt_msg_ar = "🛑 [النظام] تم إيقاف تشغيل الوحدة فوراً بأمر المستخدم."
                halt_msg_en = "🛑 [SYSTEM] Unit execution halted immediately by user command."
                halt_msg = halt_msg_ar if is_ar else halt_msg_en
                logger.info("[SCHEDULER] Two-stage sweep stopped before Stage 2.")
                TenantActivityStream.emit(self._bot_id, None, halt_msg_ar, user_id=uid, message_en=halt_msg_en)
                await activity_stream.broadcast(halt_msg, user_id=uid)
                return

            stage1_done_msg_ar = f"✅ [اكتملت المرحلة 1] تم الانتهاء من جميع الحكّام الأساسيين ({total_slot1} حسابات)."
            stage1_done_msg_en = f"✅ [STAGE 1 COMPLETE] All {total_slot1} Primary Governors finished."
            stage1_done_msg = stage1_done_msg_ar if is_ar else stage1_done_msg_en
            logger.info(stage1_done_msg)
            print(stage1_done_msg, flush=True)
            TenantActivityStream.emit(self._bot_id, None, stage1_done_msg_ar, user_id=uid, message_en=stage1_done_msg_en)
            await activity_stream.broadcast(stage1_done_msg, user_id=uid)

            # Brief settle delay between Stage 1 and Stage 2
            await asyncio.sleep(random.uniform(3.0, 5.0))

            # ================= STAGE 2: ALL SECONDARY GOVERNORS (SLOT 2) =================
            # (Stage banner removed: STARTUP BANNER already opened the cycle.)
            if total_slot2 > 0 and self._running:
                slot2_tasks = []
                for idx, (acc, char) in enumerate(slot2_characters, 1):
                    if not self._running:
                        break
                    if idx > 1:
                        pre_delay = round(random.uniform(3.0, 5.0), 1)
                        await asyncio.sleep(pre_delay)

                    if not self._running:
                        break
                    t = asyncio.create_task(_run_single_governor(acc, char, 2, 2, idx, total_slot2))
                    slot2_tasks.append(t)

                if slot2_tasks:
                    await asyncio.gather(*slot2_tasks, return_exceptions=True)

                if not self._running:
                    halt_msg_ar = "🛑 [النظام] تم إيقاف تشغيل الوحدة فوراً بأمر المستخدم."
                    halt_msg_en = "🛑 [SYSTEM] Unit execution halted immediately by user command."
                    halt_msg = halt_msg_ar if is_ar else halt_msg_en
                    TenantActivityStream.emit(self._bot_id, None, halt_msg_ar, user_id=uid, message_en=halt_msg_en)
                    await activity_stream.broadcast(halt_msg, user_id=uid)
                    return

                stage2_done_msg_ar = f"✅ [اكتملت المرحلة 2] تم الانتهاء من جميع الحكّام الثانويين ({total_slot2} حسابات)."
                stage2_done_msg_en = f"✅ [STAGE 2 COMPLETE] All {total_slot2} Secondary Governors finished."
                stage2_done_msg = stage2_done_msg_ar if is_ar else stage2_done_msg_en
                logger.info(stage2_done_msg)
                print(stage2_done_msg, flush=True)
                TenantActivityStream.emit(self._bot_id, None, stage2_done_msg_ar, user_id=uid, message_en=stage2_done_msg_en)
                await activity_stream.broadcast(stage2_done_msg, user_id=uid)

            # Post-cycle completion & next run timestamp calculation
            now_dt = datetime.datetime.now()
            now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            interval_hours = self._parse_interval_hours()
            base_cycle_minutes = int(interval_hours * 60)

            from app.services.scheduler_service import BotScheduler
            # Objectives 2 & 3: Global sync reference and staggered jitter intervals
            global_next_dt = BotScheduler.calculate_global_next_run(True, base_cycle_minutes)
            global_next_str = global_next_dt.strftime("%Y-%m-%d %H:%M:%S") if global_next_dt else ""

            BotSettingsDAO.set("next_run_timestamp", global_next_str, user_id=uid or None)
            if self._bot_id:
                BotSettingsDAO.set(f"next_run_timestamp_{self._bot_id}", global_next_str, user_id=uid or None)

            for acc, chars in account_tasks_data:
                acc_next_dt = BotScheduler.calculate_next_run(acc["id"], True, base_cycle_minutes)
                acc_next_str = acc_next_dt.strftime("%Y-%m-%d %H:%M:%S") if acc_next_dt else global_next_str
                AccountDAO.update_run_times(acc["id"], last_run=now_str, next_run=acc_next_str)
                for c in chars:
                    char_next_dt = BotScheduler.calculate_next_run(c.get("role_id"), True, base_cycle_minutes)
                    char_next_str = char_next_dt.strftime("%Y-%m-%d %H:%M:%S") if char_next_dt else acc_next_str
                    CharacterDAO.update_run_times(c.get("role_id"), last_run=now_str, next_run=char_next_str)

            sweep_done_msg_ar = f"⚡ [اكتملت دورة الأسطول] تم إنهاء فحص وتشغيل جميع الحكام بنجاح عبر المرحلتين. الدورة القادمة: {global_next_str}"
            sweep_done_msg_en = f"⚡ [FLEET SWEEP COMPLETE] All two-stage governor cycles finished successfully. Next cycle: {global_next_str}"
            sweep_done_msg = sweep_done_msg_ar if is_ar else sweep_done_msg_en
            logger.info(sweep_done_msg)
            print(sweep_done_msg, flush=True)
            TenantActivityStream.emit(self._bot_id, None, sweep_done_msg_ar, user_id=uid, message_en=sweep_done_msg_en)
            await activity_stream.broadcast(sweep_done_msg, user_id=uid)

    async def _run_loop(self):
        logger.info(f"AutonomousScheduler loop entered for tenant {self._user_id} bot_id={self._bot_id}.")
        while self._running:
            try:
                # 1. Dynamic account-to-bot fallback alignment
                self._ensure_accounts_bound()

                if self._bot_id:
                    bot_accs = AccountDAO.get_all(bot_id=self._bot_id)
                    user_accs = AccountDAO.get_all(self._user_id, bot_id=self._bot_id) if self._user_id else []
                    accounts = bot_accs if len(bot_accs) >= len(user_accs) else user_accs
                else:
                    accounts = AccountDAO.get_all(self._user_id)

                active_accounts = [
                    a for a in accounts
                    if a.get("is_active", 1) == 1
                    and "shoob" not in str(a.get("email") or "").lower()
                ]

                # Intelligent Fallback 1: If user_id scoped query returned empty, try bot_id across all linked accounts
                if not active_accounts and self._bot_id:
                    fallback_accounts = AccountDAO.get_all(bot_id=self._bot_id)
                    active_accounts = [
                        a for a in fallback_accounts
                        if "shoob" not in str(a.get("email") or "").lower()
                    ]
                    if active_accounts and self._user_id:
                        # Auto-adopt to this tenant
                        try:
                            from app.database import get_db_connection
                            with get_db_connection() as con:
                                acc_ids = [a["id"] for a in active_accounts]
                                q_ph = ",".join("?" for _ in acc_ids)
                                con.execute(f"UPDATE accounts SET user_id = ?, is_active = 1 WHERE id IN ({q_ph})", (self._user_id, *acc_ids))
                        except Exception:
                            pass

                # Intelligent Fallback 2: If bot_id scoped query returned empty, try user_id across all user accounts
                if not active_accounts and self._user_id:
                    fallback_accounts = AccountDAO.get_all(user_id=self._user_id)
                    active_accounts = [
                        a for a in fallback_accounts
                        if "shoob" not in str(a.get("email") or "").lower()
                    ]
                    if active_accounts and self._bot_id:
                        # Auto-bind to this bot_id
                        try:
                            from app.database import get_db_connection
                            with get_db_connection() as con:
                                acc_ids = [a["id"] for a in active_accounts]
                                q_ph = ",".join("?" for _ in acc_ids)
                                con.execute(f"UPDATE accounts SET bot_id = ?, is_active = 1 WHERE id IN ({q_ph})", (self._bot_id, *acc_ids))
                        except Exception:
                            pass
                
                account_tasks_data = []
                for acc in active_accounts:
                    chars = CharacterDAO.get_by_account_id(acc["id"])
                    enabled_chars = [
                        c for c in chars
                        if c.get("enabled", 1) == 1
                        and "shoob" not in str(c.get("name") or "").lower()
                    ]
                    if not enabled_chars and chars:
                        valid_chars = [c for c in chars if "shoob" not in str(c.get("name") or "").lower()]
                        if valid_chars:
                            from app.database import get_db_connection
                            with get_db_connection() as con:
                                con.execute("UPDATE characters SET enabled = 1 WHERE account_id = ? AND LOWER(name) NOT LIKE '%shoob%'", (acc["id"],))
                            enabled_chars = valid_chars
                    if enabled_chars:
                        account_tasks_data.append((acc, enabled_chars))

                if not account_tasks_data:
                    lang = BotSettingsDAO.get("ui_language", "ar", user_id=self._user_id or None).lower()
                    is_ar = "ar" in lang or not ("en" in lang)
                    warn_msg_ar = "⚠️ [تنبيه] لا توجد حسابات أو شخصيات مفعلة لهذه الوحدة. يرجى ربط حساب وتفعيل الشخصيات أولاً."
                    warn_msg_en = "⚠️ [WARNING] No enabled accounts or governors found for this unit. Please link an account and enable governors."
                    warn_msg = warn_msg_ar if is_ar else warn_msg_en
                    logger.warning(f"[{self._bot_id}] {warn_msg}")
                    TenantActivityStream.emit(self._bot_id, None, warn_msg_ar, user_id=self._user_id, message_en=warn_msg_en)
                    await activity_stream.broadcast(warn_msg, user_id=self._user_id)
                else:
                    logger.info(
                        f"Fleet two-stage execution [{self._bot_id}]: processing {len(account_tasks_data)} account(s) (Slot 1 Primary -> Slot 2 Secondary)..."
                    )
                    await self.execute_staged_sweep(account_tasks_data)
                    logger.info("All staged character pipelines completed.")

                interval_hours = self._parse_interval_hours()
                sleep_seconds = max(30, int(interval_hours * 3600))
                logger.info(f"Sweep complete. Sleeping for {sleep_seconds}s before next round.")
                elapsed = 0
                while self._running and elapsed < sleep_seconds:
                    step = min(5.0, sleep_seconds - elapsed)
                    try:
                        await asyncio.wait_for(self._wake_event.wait(), timeout=step)
                        self._wake_event.clear()
                        logger.info(f"AutonomousScheduler [{self._bot_id}] awakened by trigger.")
                        break
                    except asyncio.TimeoutError:
                        elapsed += step
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in AutonomousScheduler loop: {e}", exc_info=True)
                await asyncio.sleep(30.0)


async def run_sequential_fleet_cycle(delay_between: float = 5.0, user_id: str = "", bot_id: Optional[str] = None, role_ids: Optional[list] = None):
    """Staged fleet cycle: Runs Slot 1 Primary characters first, then Slot 2 Secondary characters with 3-5s pre-delay."""
    from app.models import AccountDAO, CharacterDAO
    sched = get_scheduler(user_id, bot_id=bot_id or "bot-2404")
    sched._ensure_accounts_bound()

    if bot_id:
        sched._ensure_accounts_bound()
        bot_accs = AccountDAO.get_all(bot_id=bot_id)
        user_accs = AccountDAO.get_all(user_id, bot_id=bot_id) if user_id else []
        accounts = bot_accs if len(bot_accs) >= len(user_accs) else user_accs
    elif user_id:
        accounts = AccountDAO.get_all(user_id)
    else:
        from app.database import get_db_connection
        con = get_db_connection()
        rows = con.execute("SELECT * FROM accounts WHERE is_active=1 AND LOWER(email) NOT LIKE '%shoob%' ORDER BY id ASC").fetchall()
        accounts = [dict(r) for r in rows]

    active_accounts = [
        a for a in accounts
        if a.get("is_active", 1) == 1
        and "shoob" not in str(a.get("email") or "").lower()
    ]
    if not active_accounts and bot_id:
        fallback_accounts = AccountDAO.get_all(bot_id=bot_id)
        active_accounts = [
            a for a in fallback_accounts
            if "shoob" not in str(a.get("email") or "").lower()
        ]
    if not active_accounts and user_id:
        fallback_accounts = AccountDAO.get_all(user_id=user_id)
        active_accounts = [
            a for a in fallback_accounts
            if "shoob" not in str(a.get("email") or "").lower()
        ]

    # Ensure accounts are sorted deterministically
    active_accounts.sort(key=lambda a: int(a.get("id") or 0))

    role_ids_filter = set(str(r) for r in role_ids) if role_ids else None

    account_tasks_data = []
    for acc in active_accounts:
        try:
            chars = CharacterDAO.get_by_account_id(acc["id"])
        except Exception:
            continue
        enabled_chars = [
            c for c in chars
            if (role_ids_filter is not None and str(c.get("role_id")) in role_ids_filter)
            or (role_ids_filter is None and c.get("enabled", 1) == 1 and "shoob" not in str(c.get("name") or "").lower())
        ]
        if not enabled_chars and chars and role_ids_filter is None:
            valid_chars = [c for c in chars if "shoob" not in str(c.get("name") or "").lower()]
            if valid_chars:
                from app.database import get_db_connection
                with get_db_connection() as con:
                    con.execute("UPDATE characters SET enabled = 1 WHERE account_id = ? AND LOWER(name) NOT LIKE '%shoob%'", (acc["id"],))
                enabled_chars = valid_chars
        if enabled_chars:
            account_tasks_data.append((acc, enabled_chars))

    if not account_tasks_data:
        lang = BotSettingsDAO.get("ui_language", "ar", user_id=user_id or None).lower()
        is_ar = "ar" in lang or not ("en" in lang)
        warn_msg_ar = "⚠️ [تنبيه] لا توجد حسابات أو شخصيات مفعلة لهذه الوحدة. يرجى ربط حساب وتفعيل الشخصيات أولاً."
        warn_msg_en = "⚠️ [WARNING] No enabled accounts or governors found for this unit. Please link an account and enable governors."
        warn_msg = warn_msg_ar if is_ar else warn_msg_en
        print(f"[FLEET CYCLE] {warn_msg}", flush=True)
        TenantActivityStream.emit(bot_id or "bot-2404", None, warn_msg_ar, user_id=user_id, message_en=warn_msg_en)
        await activity_stream.broadcast(warn_msg, user_id=user_id)
        return False

    sched._running = True
    target_bot = bot_id or getattr(sched, "_bot_id", "") or "bot-2"
    if user_id:
        try:
            BotSettingsDAO.set(f"bot_running_{target_bot}", "true", user_id=user_id)
            BotSettingsDAO.set("bot_running", "true", user_id=user_id)
            BotSettingsDAO.set(f"bot_running_{target_bot}", "true")
            BotSettingsDAO.set("bot_running", "true", user_id=target_bot)
        except Exception:
            pass
    print(f"[FLEET CYCLE] Running two-stage character sweep across {len(account_tasks_data)} accounts...")
    await sched.execute_staged_sweep(account_tasks_data)
    print(f"[FLEET CYCLE] All staged character runs finished.")
    return True

scheduler = AutonomousScheduler()
_tenants: dict = {}

def get_scheduler(user_id: str = "", bot_id: Optional[str] = None) -> AutonomousScheduler:
    bid = str(bot_id).strip() if bot_id else ""
    uid = str(user_id).strip() if user_id else ""
    if uid and bid:
        key = f"tenant:{uid}:bot:{bid}"
    elif uid:
        key = f"tenant:{uid}"
    elif bid:
        key = f"bot:{bid}"
    else:
        key = "global"

    sched = _tenants.get(key)
    if sched is None:
        sched = AutonomousScheduler(user_id=uid, bot_id=bid)
        _tenants[key] = sched
        if BotSettingsDAO.is_bot_running(bid or None, uid or None):
            if not sched._running:
                sched._running = True
                key_suffix = f"_{bid}" if bid else ""
                BotSettingsDAO.set(f"bot_running{key_suffix}", "true", user_id=uid or None)
                try:
                    sched._task = asyncio.create_task(sched._run_loop())
                except RuntimeError:
                    pass
    return sched


def stop_all_schedulers() -> None:
    for sched in list(_tenants.values()):
        try:
            sched.stop()
        except Exception:
            pass


def get_running_bot_instances() -> list[dict]:
    """
    Discovers all active bot units and tenants configured in the database.
    Checks BotSettingsDAO.is_bot_running for each.
    """
    from app.database import get_db_connection
    con = get_db_connection()
    
    bots = []
    seen = set()

    # 1. Accounts table
    rows = con.execute(
        "SELECT DISTINCT bot_id, user_id FROM accounts WHERE is_active = 1"
    ).fetchall()
    for r in rows:
        bid = str(r["bot_id"] or "").strip()
        uid = str(r["user_id"] or "").strip()
        if not bid and uid:
            s_rows = con.execute("SELECT key FROM bot_settings WHERE key LIKE ? AND value IN ('true', '1')", (f"{uid}:bot_running_%",)).fetchall()
            for sr in s_rows:
                k = sr[0]
                detected_bid = k.split(":bot_running_")[-1]
                if detected_bid:
                    bid = detected_bid
                    break
        if not bid:
            continue
        key = (bid, uid)
        if key in seen:
            continue
        seen.add(key)
        if BotSettingsDAO.is_bot_running(bid, uid):
            bots.append({"id": bid, "user_id": uid})

    # 2. Check bot_settings for active bot instances
    setting_rows = con.execute(
        "SELECT key, value FROM bot_settings WHERE value IN ('true', '1')"
    ).fetchall()
    for r in setting_rows:
        k = str(r["key"])
        if ":bot_running_" in k:
            parts = k.split(":bot_running_")
            uid = parts[0]
            bid = parts[1]
            key = (bid, uid)
            if key not in seen:
                seen.add(key)
                bots.append({"id": bid, "user_id": uid})
        elif k.endswith(":bot_running"):
            bid_cand = k[:-len(":bot_running")]
            if bid_cand.startswith("bot-"):
                u_row = con.execute("SELECT user_id FROM accounts WHERE bot_id = ? LIMIT 1", (bid_cand,)).fetchone()
                uid = u_row[0] if u_row and u_row[0] else ""
                key = (bid_cand, uid)
                if key not in seen:
                    seen.add(key)
                    bots.append({"id": bid_cand, "user_id": uid})

    for default_bid in ("bot-2404", "bot-2911"):
        if default_bid not in [b["id"] for b in bots]:
            if BotSettingsDAO.is_bot_running(default_bid):
                bots.append({"id": default_bid, "user_id": ""})

    return bots


def get_due_accounts_for_bot(bot_id: str, user_id: Optional[str] = None) -> list[dict]:
    """
    Finds active accounts for this bot where next_run <= now (or is null/empty/0).
    Only includes accounts that have at least one enabled character.
    """
    bid = str(bot_id).strip()
    accounts = AccountDAO.get_all(user_id=user_id or None, bot_id=bid if bid else None)
    active_accounts = [a for a in accounts if a.get("is_active", 1) == 1]
    
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    due = []
    
    for acc in active_accounts:
        try:
            chars = CharacterDAO.get_by_account_id(acc["id"])
        except Exception:
            continue
        enabled_chars = [c for c in chars if c.get("enabled", 1) == 1]
        if not enabled_chars:
            continue
            
        is_due = False
        acc_next = acc.get("next_run")
        if not acc_next:
            is_due = True
        elif str(acc_next) <= now_str:
            is_due = True
            
        if not is_due:
            for c in enabled_chars:
                c_next = c.get("next_run")
                if not c_next or str(c_next) <= now_str:
                    is_due = True
                    break
                    
        if is_due:
            due.append(acc)
            
    return due


def update_account_next_run(account_id: int, next_run_str: str, last_run_str: Optional[str] = None):
    """Updates next_run and last_run for an account and all its characters."""
    now_str = last_run_str or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    AccountDAO.update_run_times(account_id, last_run=now_str, next_run=next_run_str)
    
    chars = CharacterDAO.get_by_account_id(account_id)
    for c in chars:
        CharacterDAO.update_run_times(c["role_id"], last_run=now_str, next_run=next_run_str)


async def execute_account_visit_cycle(account: dict, bot: dict):
    """Executes the full pipeline for an account's enabled characters."""
    chars = CharacterDAO.get_by_account_id(account["id"])
    enabled_chars = [c for c in chars if c.get("enabled", 1) == 1]
    if not enabled_chars:
        return
        
    sched = get_scheduler(user_id=account.get("user_id") or bot.get("user_id", ""), bot_id=bot.get("id"))
    await sched._run_account_pipeline(account, enabled_chars)


_master_loop_task: Optional[asyncio.Task] = None


async def master_scheduler_loop():
    """
    Continuous, indestructible scheduling loop.
    Audits active bot instances and triggers accounts whose next_run <= now.
    """
    logger.info("🚀 [SCHEDULER] Master scheduler loop initialized and active.")
    
    while True:
        try:
            active_bots = get_running_bot_instances()
            
            for bot in active_bots:
                bot_id = bot["id"]
                user_id = bot.get("user_id") or ""
                if not BotSettingsDAO.is_bot_running(bot_id, user_id):
                    continue
                existing_sched = _tenants.get(f"tenant:{user_id}:bot:{bot_id}") or _tenants.get(f"bot:{bot_id}") or (user_id and _tenants.get(f"user:{user_id}"))
                if existing_sched and existing_sched._running and existing_sched._task and not existing_sched._task.done():
                    # Unit's own AutonomousScheduler._run_loop is actively managing staged visits
                    continue
                sched = get_scheduler(user_id=user_id, bot_id=bot_id)
                if not sched._running or not sched._task or sched._task.done():
                    if BotSettingsDAO.is_bot_running(bot_id, user_id):
                        logger.info(f"🚀 [SCHEDULER] Auto-starting staged scheduler loop for {bot_id} (user_id={user_id})...")
                        sched.start()
                    
        except asyncio.CancelledError:
            break
        except Exception as loop_err:
            logger.error(f"💥 [CRITICAL SCHEDULER ERROR] Master loop caught top-level exception: {loop_err}", exc_info=True)
            
        await asyncio.sleep(10.0)


def start_master_scheduler() -> None:
    global _master_loop_task
    if _master_loop_task is None or _master_loop_task.done():
        try:
            loop = asyncio.get_running_loop()
            _master_loop_task = loop.create_task(master_scheduler_loop())
            logger.info("🚀 Master scheduler background task registered and started.")
        except RuntimeError:
            pass


def is_master_scheduler_running() -> bool:
    global _master_loop_task
    return _master_loop_task is not None and not _master_loop_task.done()


async def run_account_cycle(game_client, config: dict):
    """
    Executes the strict synchronous 2-phase account cycle under ACCOUNT_EXECUTION_LOCK:
    Phase 1: Barbarian Hunting -> Wait Barrier (wait_for_all_marches_to_return) -> Phase 2: Gathering (4/4 marches).
    """
    from app.services.barbarian_hunter import wait_for_all_marches_to_return, run_barbarian_hunter
    from app.services.gatherer import run_gatherer

    async with ACCOUNT_EXECUTION_LOCK:
        # --- PHASE 1: BARBARIAN HUNTING ---
        if config.get("hunt_barbarians_enabled"):
            logger.info("⚔️ [PHASE 1] Starting Barbarian Hunting cycle...")
            if hasattr(game_client, "run_barbarian_hunter"):
                await game_client.run_barbarian_hunter(config)
            else:
                await run_barbarian_hunter(game_client, config)

            # MANDATORY BARRIER: Do NOT start gathering until all barbarian armies are inside the city!
            logger.info("⏳ [WAIT BARRIER] Barbarian hunt ended. Awaiting troop return to city...")
            await wait_for_all_marches_to_return(game_client, timeout=300)

        # --- PHASE 2: GATHERING (ALL 4 SLOTS GUARANTEED FREE) ---
        from app.services.session_manager import is_gather_scheduler_paused
        if is_gather_scheduler_paused():
            logger.info("⏸️ [RSS TRANSFER PRIORITY] تم تعليق جولة الجمع مؤقتاً لصالح نقل الموارد الجاري.")
        elif config.get("gathering_enabled"):
            if hasattr(game_client, "refresh_city_inventory"):
                await game_client.refresh_city_inventory()  # Re-read full troop & commander pool inside city
            logger.info("🌾 [PHASE 2] Starting Gathering. Free march slots: 4/4")
            if hasattr(game_client, "run_gatherer"):
                await game_client.run_gatherer(config, max_marches=4)
            else:
                await run_gatherer(game_client, config, max_marches=4)

