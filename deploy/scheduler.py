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
GLOBAL_EXECUTION_LOCK = asyncio.Lock()
_QUEUED_OR_RUNNING_ROLES: set[str] = set()
_LAST_FINISHED_TS: dict[str, float] = {}
_VISIT_COOLDOWN_SECONDS = 90.0

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
        TenantActivityStream.emit(self._bot_id, None, "Autonomous Scheduler started.", user_id=self._user_id)
        asyncio.create_task(activity_stream.broadcast(
            "Autonomous Scheduler started.", user_id=self._user_id))

    def stop(self):
        self._running = False
        key_suffix = f"_{self._bot_id}" if self._bot_id else ""
        BotSettingsDAO.set(f"bot_running{key_suffix}", "false", user_id=self._user_id or None)
        if self._bot_id:
            BotSettingsDAO.set("bot_running", "false", user_id=self._bot_id)
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info(f"AutonomousScheduler stopped for tenant {self._user_id} bot_id={self._bot_id}.")
        TenantActivityStream.emit(self._bot_id, None, "Autonomous Scheduler stopped.", user_id=self._user_id)
        asyncio.create_task(activity_stream.broadcast(
            "Autonomous Scheduler stopped.", user_id=self._user_id))

    def _parse_interval_hours(self) -> float:
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

    async def _run_character_cycle(self, account: dict, char: dict, already_locked: bool = False):
        role_id = str(char["role_id"])
        name = char.get("name") or role_id
        if not already_locked:
            if role_id in _QUEUED_OR_RUNNING_ROLES:
                logger.info(f"Skipping duplicate cycle request for {name} ({role_id}) — already queued or active.")
                return
            _QUEUED_OR_RUNNING_ROLES.add(role_id)
            try:
                async with GLOBAL_EXECUTION_LOCK:
                    await self._run_character_cycle_unlocked(account, char)
            finally:
                _QUEUED_OR_RUNNING_ROLES.discard(role_id)
        else:
            _QUEUED_OR_RUNNING_ROLES.add(role_id)
            try:
                await self._run_character_cycle_unlocked(account, char)
            finally:
                _QUEUED_OR_RUNNING_ROLES.discard(role_id)

    async def _run_character_cycle_unlocked(self, account: dict, char: dict):
        import time as _time
        role_id = str(char["role_id"])
        kd = str(char.get("kingdom_id") or "")
        name = char.get("name") or role_id
        uid = account.get("user_id") or self._user_id or ""

        # Prevent back-to-back duplicate execution if already visited within the last 90 seconds
        last_ts = _LAST_FINISHED_TS.get(role_id, 0.0)
        if _time.time() - last_ts < _VISIT_COOLDOWN_SECONDS:
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

        # Clean sequence matching official dashboard format
        TenantActivityStream.emit(self._bot_id, name, f"Switching to {name}")
        await _bcast(f"Switching to {name}")

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

        await asyncio.sleep(1.0)
        TenantActivityStream.emit(self._bot_id, name, f"Starting visit for {name}")
        await _bcast(f"[{name}] Starting visit for {name}")

        # Load dynamic settings from CharacterSettingsDAO (web Config tab)
        try:
            from app.models import CharacterSettingsDAO
            settings = CharacterSettingsDAO.get_by_character_id(char["id"])
        except Exception:
            settings = {}

        # 1. Daily Claims & City Harvest Check
        try:
            daily_cfg = settings.get("daily_claims") or {}
            city_cfg = settings.get("city") or {}
            daily_enabled = any([
                daily_cfg.get("vip_chest", True),
                daily_cfg.get("daily_quest_chests", True),
                daily_cfg.get("chronicle", True),
                city_cfg.get("collect_resources", True),
            ])
            if daily_enabled:
                TenantActivityStream.emit(self._bot_id, name, "Collecting city resources & daily claims")
                await _bcast(f"[{name}] Collecting city resources & daily claims")
                tid_daily = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_daily, role_id=role_id, task_type="daily_claims", status="RUNNING", details={}, character_id=char["id"])
                await GameSocketWorker.run_character_task(tid_daily, role_id, "daily_claims", user_id=uid)
                await asyncio.sleep(random.uniform(1.2, 2.0))
        except Exception as e_daily:
            logger.warning(f"Daily claims failed for {role_id}: {e_daily}")

        # 2. Dynamic Alliance Sweep Check (Help all, resource pit, tech donation, gift boxes)
        try:
            alliance_cfg = settings.get("alliance") or {}
            from app.services.alliance_donator import is_tech_donation_enabled
            donate_tech_on = is_tech_donation_enabled(settings)
            alliance_enabled = any([
                alliance_cfg.get("help_alliance_members", True),
                alliance_cfg.get("gather_resource_pit", True),
                donate_tech_on,
                alliance_cfg.get("claim_gifts", True),
            ])
            if alliance_enabled:
                TenantActivityStream.emit(self._bot_id, name, "Executing alliance actions (help, pit, donation, gifts)")
                await _bcast(f"[{name}] Executing alliance actions (help, pit, donation, gifts)")
                tid_alliance = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_alliance, role_id=role_id, task_type="alliance_sweep", status="RUNNING", details={}, character_id=char["id"])
                await GameSocketWorker.run_character_task(tid_alliance, role_id, "alliance_sweep", user_id=uid)
                await asyncio.sleep(random.uniform(1.2, 2.0))
        except Exception as e_alliance:
            logger.warning(f"Alliance sweep failed for {role_id}: {e_alliance}")

        # 3. Hospital Check & Troop Healing
        try:
            hospital_cfg = settings.get("hospital") or {}
            if hospital_cfg.get("heal_troops", False):
                TenantActivityStream.emit(self._bot_id, name, "Checking hospital & healing wounded troops")
                await _bcast(f"[{name}] Checking hospital & healing wounded troops")
                tid_hosp = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_hosp, role_id=role_id, task_type="hospital", status="RUNNING", details={}, character_id=char["id"])
                await GameSocketWorker.run_character_task(tid_hosp, role_id, "hospital", user_id=uid)
                await asyncio.sleep(random.uniform(1.2, 2.0))
        except Exception as e_hosp:
            logger.warning(f"Hospital check failed for {role_id}: {e_hosp}")

        # 4. Dynamic Training Check
        try:
            training_cfg = settings.get("training") if isinstance(settings.get("training"), dict) else None
            training_enabled = True
            if training_cfg is not None:
                training_enabled = training_cfg.get("enabled", True)
            else:
                try:
                    from app.models import BotSettingsDAO
                    bot_train = BotSettingsDAO.get("training_enabled", "true", user_id=uid)
                    if str(bot_train).lower() in ("false", "0", "off", "disabled"):
                        training_enabled = False
                except Exception:
                    pass
                gather_json = settings.get("gather") or {}
                if isinstance(gather_json, dict) and gather_json.get("training_enabled") is False:
                    training_enabled = False
            tiers = settings.get("tiers") or {}
            if training_enabled and tiers:
                if all(str(v).lower() in ("off", "skip", "0", "") for v in tiers.values()):
                    training_enabled = False

            if training_enabled:
                TenantActivityStream.emit(self._bot_id, name, "Training troops")
                await _bcast(f"[{name}] Training troops")
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
                trained_cnt = t_data.get("trained_count", 0)
                busy_cnt = t_data.get("busy_count", 0)
                total_tgts = t_data.get("total_targets", 4)

                if trained_cnt > 0:
                    train_msg = f"Finished training troops ({trained_cnt}/{total_tgts} barracks started recruiting)"
                    TenantActivityStream.emit(self._bot_id, name, train_msg)
                    await _bcast(f"[{name}] {train_msg}")
                elif busy_cnt > 0:
                    train_msg = f"All {busy_cnt} military barracks are currently busy training"
                    TenantActivityStream.emit(self._bot_id, name, train_msg)
                    await _bcast(f"[{name}] {train_msg}")
                else:
                    train_msg = "Troop training check complete (barracks idle / waiting for resources)"
                    TenantActivityStream.emit(self._bot_id, name, train_msg)
                    await _bcast(f"[{name}] {train_msg}")
                await asyncio.sleep(random.uniform(1.2, 2.0))
        except Exception as e_train:
            logger.warning(f"Training failed for {role_id}: {e_train}")

        # 5. Barbarian Combat Check (Always strictly before gathering to clear all barbarians first)
        try:
            combat_cfg = settings.get("combat") or {}
            if combat_cfg.get("barbs", False):
                from app.services.combat_engine import parse_combat_rounds
                lvl_info = combat_cfg.get("highest_barb_level") or combat_cfg.get("min_barb_level") or "Max Unlocked"
                rounds = parse_combat_rounds(combat_cfg.get("combat_rounds"), default=4)
                TenantActivityStream.emit(self._bot_id, name, f"Hunting barbarians ({lvl_info} - {rounds} round{'s' if rounds > 1 else ''}) [BEFORE GATHER]")
                await activity_stream.broadcast(f"[{name}] Hunting barbarians ({lvl_info} - {rounds} round{'s' if rounds > 1 else ''}) [BEFORE GATHER]", user_id=uid)
                tid_combat = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_combat, role_id=role_id, task_type="combat", status="RUNNING", details={}, character_id=char["id"])
                res_c = await GameSocketWorker.run_character_task(tid_combat, role_id, "combat", params=combat_cfg, user_id=uid)
                c_data = (res_c.get("data") or {}) if isinstance(res_c, dict) else {}
                tot_m = c_data.get("total_marches", 0)
                if tot_m > 0:
                    TenantActivityStream.emit(self._bot_id, name, f"Barbarian combat finished ({tot_m} march{'es' if tot_m > 1 else ''}). Marches returned to city. Queues now empty for gathering.")
                    await activity_stream.broadcast(f"[{name}] Barbarian combat finished ({tot_m} march{'es' if tot_m > 1 else ''}). Marches returned to city. Queues now empty for gathering.", user_id=uid)
                else:
                    if not res_c.get("success"):
                        err_msg = res_c.get("error") or "execution error"
                        TenantActivityStream.emit(self._bot_id, name, f"Barbarian combat aborted ({err_msg}). Proceeding to gather...")
                        await activity_stream.broadcast(f"[{name}] Barbarian combat aborted ({err_msg}). Proceeding to gather...", user_id=uid)
                    else:
                        skip_reason = c_data.get("reason") or "insufficient AP or no targets in range"
                        TenantActivityStream.emit(self._bot_id, name, f"Barbarian combat skipped ({skip_reason}). Proceeding to gather...")
                        await activity_stream.broadcast(f"[{name}] Barbarian combat skipped ({skip_reason}). Proceeding to gather...", user_id=uid)
                await asyncio.sleep(random.uniform(2.0, 3.0))
        except Exception as e_combat:
            logger.warning(f"Barbarian combat failed for {role_id}: {e_combat}")

        # 6. Dynamic Gathering Check (Runs strictly after barbarian combat when all queues are free)
        gather_cfg = settings.get("gather") or {}
        gather_enabled = True
        if isinstance(gather_cfg, dict) and gather_cfg.get("enabled") is False:
            gather_enabled = False

        if gather_enabled:
            TenantActivityStream.emit(self._bot_id, name, "Sending out gatherers")
            await _bcast(f"[{name}] Sending out gatherers")
            try:
                tid_gather = f"task_{uuid.uuid4().hex[:12]}"
                TaskLogDAO.create(task_id=tid_gather, role_id=role_id, task_type="gather", status="RUNNING", details={}, character_id=char["id"])
                gather_params = {
                    "skip_combat_preflight": True,
                    "bot_id": self._bot_id or "bot-2404"
                }
                res_gather = await GameSocketWorker.run_character_task(tid_gather, role_id, "gather", params=gather_params, user_id=uid)
                g_data = (res_gather.get("data") or {}) if isinstance(res_gather, dict) else {}
                dispatched_cnt = g_data.get("dispatched_count", 0)
                active_cnt = g_data.get("active_marches_count", 0)

                if dispatched_cnt > 0:
                    gather_done_msg = f"Dispatched {dispatched_cnt} new gathering march{'es' if dispatched_cnt > 1 else ''} ({active_cnt} total active on map)"
                    TenantActivityStream.emit(self._bot_id, name, gather_done_msg)
                    await _bcast(f"[{name}] {gather_done_msg}")
                elif active_cnt > 0:
                    gather_done_msg = f"All {active_cnt} gathering queues are already active on resource tiles"
                    TenantActivityStream.emit(self._bot_id, name, gather_done_msg)
                    await _bcast(f"[{name}] {gather_done_msg}")
                else:
                    gather_done_msg = "Gathering check complete (0 marches dispatched)"
                    TenantActivityStream.emit(self._bot_id, name, gather_done_msg)
                    await _bcast(f"[{name}] {gather_done_msg}")
            except Exception as e:
                logger.warning(f"Gather failed for {role_id}: {e}")

        # Finished visit
        _LAST_FINISHED_TS[role_id] = _time.time()
        TenantActivityStream.emit(self._bot_id, name, f"Finished visit for {name}")
        await activity_stream.broadcast(f"[{name}] Finished visit for {name}", user_id=uid)

        # Update Last Run and calculate Next Run with jitter (both CharacterDAO and AccountDAO)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        interval_hours = self._parse_interval_hours()
        next_run_str = self._calculate_next_run(interval_hours)
        CharacterDAO.update_run_times(role_id, last_run=now_str, next_run=next_run_str)
        AccountDAO.update_run_times(account["id"], last_run=now_str, next_run=next_run_str)
        current_user_id.reset(token)

        # Mandatory inter-character TCP teardown & gateway settle window before releasing GLOBAL_EXECUTION_LOCK
        await asyncio.sleep(3.0)

    async def _safe_run_character_cycle(self, acc: dict, ch: dict, already_locked: bool = False):
        cname = ch.get("name") or ch.get("role_id")
        try:
            await self._run_character_cycle(acc, ch, already_locked=already_locked)
        except asyncio.CancelledError:
            raise
        except Exception as cycle_err:
            logger.error(f"Error cycling character visit {cname}: {cycle_err}", exc_info=True)

    async def _run_account_pipeline(self, acc: dict, chars: list):
        """Runs all enabled characters of an account in strict sequential lock."""
        role_ids = [str(c.get("role_id") or "") for c in chars if c.get("role_id")]
        for rid in role_ids:
            _QUEUED_OR_RUNNING_ROLES.add(rid)
        try:
            async with GLOBAL_EXECUTION_LOCK:
                return await self._run_account_pipeline_locked(acc, chars)
        finally:
            for rid in role_ids:
                _QUEUED_OR_RUNNING_ROLES.discard(rid)

    async def _run_account_pipeline_locked(self, acc: dict, chars: list):
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
            if not self._running:
                break
            c_start = time.time()
            await self._safe_run_character_cycle(acc, ch, already_locked=True)
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
                RunHistoryDAO.record_run(
                    run_id=run_id,
                    bot_id=self._bot_id or "bot-2404",
                    account_email=acc.get("email") or "",
                    started_at=start_dt_str,
                    duration_minutes=total_duration_min,
                    characters_visited=f"{visited_count} / {total_count}",
                    food_gathered=tot_fg,
                    wood_gathered=tot_wg,
                    stone_gathered=tot_sg,
                    gold_gathered=tot_gg,
                    summary_json=json.dumps(run_summary_obj),
                    character_details=char_details_list
                )
                logger.info(f"Recorded run history {run_id} for bot={self._bot_id} acc={acc.get('email')}")
            except Exception as e_rec:
                logger.warning(f"Failed recording run history {run_id}: {e_rec}")

    async def execute_staged_sweep(self, account_tasks_data: list):
        # Step 1: Separate into Slot 1 (Primary) and Slot 2 (Secondary)
        slot1_characters = []
        slot2_characters = []

        for acc, chars in account_tasks_data:
            sorted_chars = sorted(chars, key=lambda c: (int(c.get("id") or 0), str(c.get("role_id") or "")))
            if len(sorted_chars) > 0:
                slot1_characters.append((acc, sorted_chars[0]))
            if len(sorted_chars) > 1:
                for sec_c in sorted_chars[1:]:
                    slot2_characters.append((acc, sec_c))

        # Step 2: Execute all Slot 1 characters sequentially
        stage1_msg = f"🚀 [STAGE 1] Running Primary Characters (Slot 1) across {len(slot1_characters)} accounts..."
        logger.info(stage1_msg)
        print(stage1_msg, flush=True)
        TenantActivityStream.emit(self._bot_id or "bot-2404", None, stage1_msg, user_id=self._user_id)
        try:
            await activity_stream.broadcast(stage1_msg, user_id=self._user_id or "")
        except Exception:
            pass

        for acc, char in slot1_characters:
            if not self._running:
                break
            cname = char.get("name") or char.get("role_id")
            logger.info(f"[STAGE 1 - Slot 1] Executing primary character {cname} on {acc.get('email')}...")
            print(f"[STAGE 1 - Slot 1] Executing primary character {cname} on {acc.get('email')}...", flush=True)
            TenantActivityStream.emit(self._bot_id or "bot-2404", cname, f"Starting Stage 1 cycle for {cname}", user_id=self._user_id)
            await self._run_account_pipeline(acc, [char])
            if not self._running:
                break
            delay = random.uniform(5.0, 10.0)
            logger.info(f"Stagger delay: sleeping for {delay:.2f}s before next character...")
            print(f"Stagger delay: sleeping for {delay:.2f}s before next character...", flush=True)
            await asyncio.sleep(delay)

        stage1_done_msg = f"✅ [STAGE 1 COMPLETE] All {len(slot1_characters)} Primary Characters finished."
        logger.info(stage1_done_msg)
        print(stage1_done_msg, flush=True)
        TenantActivityStream.emit(self._bot_id or "bot-2404", None, stage1_done_msg, user_id=self._user_id)
        try:
            await activity_stream.broadcast(stage1_done_msg, user_id=self._user_id or "")
        except Exception:
            pass

        # Step 3: Execute all Slot 2 characters sequentially
        stage2_msg = f"🚀 [STAGE 2] Running Secondary Characters (Slot 2) across {len(slot2_characters)} accounts..."
        logger.info(stage2_msg)
        print(stage2_msg, flush=True)
        TenantActivityStream.emit(self._bot_id or "bot-2404", None, stage2_msg, user_id=self._user_id)
        try:
            await activity_stream.broadcast(stage2_msg, user_id=self._user_id or "")
        except Exception:
            pass

        for acc, char in slot2_characters:
            if not self._running:
                break
            cname = char.get("name") or char.get("role_id")
            logger.info(f"[STAGE 2 - Slot 2] Executing secondary character {cname} on {acc.get('email')}...")
            print(f"[STAGE 2 - Slot 2] Executing secondary character {cname} on {acc.get('email')}...", flush=True)
            TenantActivityStream.emit(self._bot_id or "bot-2404", cname, f"Starting Stage 2 cycle for {cname}", user_id=self._user_id)
            await self._run_account_pipeline(acc, [char])
            if not self._running:
                break
            delay = random.uniform(5.0, 10.0)
            logger.info(f"Stagger delay: sleeping for {delay:.2f}s before next character...")
            print(f"Stagger delay: sleeping for {delay:.2f}s before next character...", flush=True)
            await asyncio.sleep(delay)

        stage2_done_msg = f"✅ [STAGE 2 COMPLETE] All {len(slot2_characters)} Secondary Characters finished."
        logger.info(stage2_done_msg)
        print(stage2_done_msg, flush=True)
        TenantActivityStream.emit(self._bot_id or "bot-2404", None, stage2_done_msg, user_id=self._user_id)
        try:
            await activity_stream.broadcast(stage2_done_msg, user_id=self._user_id or "")
        except Exception:
            pass

    async def _run_loop(self):
        logger.info(f"AutonomousScheduler loop entered for tenant {self._user_id} bot_id={self._bot_id}.")
        while self._running:
            try:
                if self._bot_id:
                    accounts = AccountDAO.get_all(self._user_id, bot_id=self._bot_id)
                else:
                    accounts = AccountDAO.get_all(self._user_id)
                active_accounts = [
                    a for a in accounts
                    if a.get("is_active", 1) == 1
                    and "shoob" not in str(a.get("email") or "").lower()
                ]
                
                account_tasks_data = []
                for acc in active_accounts:
                    chars = CharacterDAO.get_by_account_id(acc["id"])
                    enabled_chars = [
                        c for c in chars
                        if c.get("enabled", 1) == 1
                        and int(c.get("kingdom_id") or 0) not in (3150, 3173)
                        and "shoob" not in str(c.get("name") or "").lower()
                    ]
                    if enabled_chars:
                        account_tasks_data.append((acc, enabled_chars))

                if not account_tasks_data:
                    logger.info(f"Sweep [{self._bot_id}]: no enabled characters across active accounts, skipping to sleep.")
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


async def run_sequential_fleet_cycle(delay_between: float = 5.0, user_id: str = "", bot_id: Optional[str] = None):
    """Staged fleet cycle: Runs Slot 1 Primary characters first, then Slot 2 Secondary characters with 5-10s stagger."""
    from app.models import AccountDAO, CharacterDAO
    if bot_id:
        accounts = AccountDAO.get_all(user_id, bot_id=bot_id)
    elif user_id:
        accounts = AccountDAO.get_all(user_id)
    else:
        from app.database import get_db_connection
        con = get_db_connection()
        rows = con.execute("SELECT * FROM accounts WHERE is_active=1").fetchall()
        accounts = [dict(r) for r in rows]

    active_accounts = [
        a for a in accounts
        if a.get("is_active", 1) == 1
        and "shoob" not in str(a.get("email") or "").lower()
    ]
    account_tasks_data = []
    for acc in active_accounts:
        try:
            chars = CharacterDAO.get_by_account_id(acc["id"])
        except Exception:
            continue
        enabled_chars = [
            c for c in chars
            if c.get("enabled", 1) == 1
            and int(c.get("kingdom_id") or 0) not in (3150, 3173)
            and "shoob" not in str(c.get("name") or "").lower()
        ]
        if enabled_chars:
            account_tasks_data.append((acc, enabled_chars))

    if not account_tasks_data:
        print(f"[FLEET CYCLE] No enabled characters to run.")
        return True

    sched = get_scheduler(user_id, bot_id=bot_id or "bot-2404")
    sched._running = True
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
                existing_sched = _tenants.get(f"bot:{bot_id}") or (user_id and _tenants.get(f"user:{user_id}"))
                if existing_sched and existing_sched._running and existing_sched._task and not existing_sched._task.done():
                    # Unit's own AutonomousScheduler._run_loop is actively managing staged visits
                    continue
                sched = get_scheduler(user_id=user_id, bot_id=bot_id)
                if not sched._running or not sched._task or sched._task.done():
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
        if config.get("gathering_enabled"):
            if hasattr(game_client, "refresh_city_inventory"):
                await game_client.refresh_city_inventory()  # Re-read full troop & commander pool inside city
            logger.info("🌾 [PHASE 2] Starting Gathering. Free march slots: 4/4")
            if hasattr(game_client, "run_gatherer"):
                await game_client.run_gatherer(config, max_marches=4)
            else:
                await run_gatherer(game_client, config, max_marches=4)

