import random
import logging
from datetime import datetime, timedelta
from typing import Optional, Union, Dict, Any

logger = logging.getLogger("BotScheduler")

BASE_CYCLE_MINUTES = 180  # 3 Hours


class BotScheduler:
    BASE_CYCLE_MINUTES = BASE_CYCLE_MINUTES  # 3 Hours

    @classmethod
    def calculate_next_run(
        cls,
        account_id: Union[str, int] = "",
        is_bot_running: Union[bool, str] = True,
        base_minutes: Optional[int] = None,
        status: str = "COMPLETED"
    ) -> Optional[datetime]:
        """
        Always schedule accounts for ~3 hours, regardless of whether they completed,
        skipped, or hit a connection drop, avoiding premature 15-minute re-runs.
        Random jitter: 175 to 185 minutes (approx 3 hours).
        """
        if isinstance(is_bot_running, str):
            status = is_bot_running
            running = True
        else:
            running = bool(is_bot_running)

        if not running:
            return None  # Reset or clear time if bot is stopped

        base = int(base_minutes) if (base_minutes and base_minutes > 0) else cls.BASE_CYCLE_MINUTES
        # Random jitter: (-5 to +5 minutes) -> 175 to 185 minutes
        jitter_offset = random.randint(-5, 5)
        total_minutes = max(5, base + jitter_offset)

        return datetime.now() + timedelta(minutes=total_minutes)

    @classmethod
    def calculate_global_next_run(cls, is_bot_running: bool = True, base_minutes: Optional[int] = None) -> Optional[datetime]:
        """
        Calculates the authoritative global cycle reference timestamp (without individual jitter)
        so the top-level timer is synchronized with the background scheduler cycle.
        """
        if not is_bot_running:
            return None
        base = int(base_minutes) if (base_minutes and base_minutes > 0) else cls.BASE_CYCLE_MINUTES
        return datetime.now() + timedelta(minutes=base)

    @classmethod
    def reset_bot_schedule(cls, bot_id: str, user_id: Optional[str] = None):
        """
        Ensures stopped bots have their timers wiped from database records,
        clearing next_run in accounts and characters, and resetting BotSettingsDAO.
        """
        try:
            from app.models import BotSettingsDAO
            if user_id:
                BotSettingsDAO.set(f"next_run_timestamp_{bot_id}", "", user_id=user_id)
                BotSettingsDAO.set("next_run_timestamp", "", user_id=user_id)
            if bot_id:
                BotSettingsDAO.set(f"next_run_timestamp_{bot_id}", "")
                BotSettingsDAO.set("next_run_timestamp", "", user_id=bot_id)

            from app.database import get_db_connection
            with get_db_connection() as con:
                if bot_id:
                    con.execute("UPDATE accounts SET next_run = NULL WHERE bot_id = ?", (str(bot_id),))
                    con.execute("UPDATE characters SET next_run = NULL WHERE account_id IN (SELECT id FROM accounts WHERE bot_id = ?)", (str(bot_id),))
                elif user_id:
                    con.execute("UPDATE accounts SET next_run = NULL WHERE user_id = ?", (str(user_id),))
                    con.execute("UPDATE characters SET next_run = NULL WHERE account_id IN (SELECT id FROM accounts WHERE user_id = ?)", (str(user_id),))
            logger.info(f"🔄 [SCHEDULER RESET] Successfully wiped next_run timestamps for bot_id={bot_id} user_id={user_id}")
        except Exception as e:
            logger.warning(f"⚠️ [SCHEDULER RESET] Error resetting schedule for {bot_id}: {e}")

    @classmethod
    def sync_account_states(cls, db_session=None, bot_status_map: Optional[Dict[str, bool]] = None):
        """
        Ensures stopped bots have their timers wiped, and active ones have synchronized intervals.
        """
        if not bot_status_map:
            return
        for bot_id, is_running in bot_status_map.items():
            if not is_running:
                cls.reset_bot_schedule(bot_id)

    @classmethod
    def reset_stale_timers(cls, min_minutes_threshold: int = 120, target_minutes: int = 180) -> int:
        """
        Reset Existing Stale Timers in Database:
        Pushes any account or character currently showing < 120m (or None/expired)
        back to the proper ~3 hours window (180m ± 5m).
        """
        count = 0
        try:
            from app.database import get_db_connection
            con = get_db_connection()
            now = datetime.now()
            threshold_time = (now + timedelta(minutes=min_minutes_threshold)).strftime("%Y-%m-%d %H:%M:%S")

            with con:
                # Find all enabled accounts
                acc_rows = con.execute("SELECT id, next_run FROM accounts WHERE is_active = 1").fetchall()
                for r in acc_rows:
                    aid, next_run = r[0], r[1]
                    if not next_run or str(next_run) < threshold_time:
                        jitter = random.randint(-5, 5)
                        new_next = (now + timedelta(minutes=target_minutes + jitter)).strftime("%Y-%m-%d %H:%M:%S")
                        con.execute("UPDATE accounts SET next_run = ? WHERE id = ?", (new_next, aid))
                        count += 1

                # Find all enabled characters
                char_rows = con.execute("SELECT id, role_id, next_run FROM characters WHERE enabled = 1").fetchall()
                for r in char_rows:
                    cid, role_id, next_run = r[0], r[1], r[2]
                    if not next_run or str(next_run) < threshold_time:
                        jitter = random.randint(-5, 5)
                        new_next = (now + timedelta(minutes=target_minutes + jitter)).strftime("%Y-%m-%d %H:%M:%S")
                        con.execute("UPDATE characters SET next_run = ? WHERE id = ?", (new_next, cid))
                        count += 1

            logger.info(f"🔄 [STALE TIMER RESET] Pushed {count} accounts/characters showing < {min_minutes_threshold}m back to ~{target_minutes}m.")
        except Exception as e:
            logger.warning(f"⚠️ [STALE TIMER RESET] Error resetting stale timers: {e}")
        return count


def calculate_next_run(account_id: str = "", status: str = "COMPLETED") -> datetime:
    """
    Always schedule accounts for ~3 hours, regardless of whether they completed,
    skipped, or hit a connection drop, avoiding premature 15-minute re-runs.
    """
    res = BotScheduler.calculate_next_run(account_id=account_id, is_bot_running=True, status=status)
    return res or (datetime.now() + timedelta(minutes=BASE_CYCLE_MINUTES))
