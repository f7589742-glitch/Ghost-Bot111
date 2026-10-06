import random
import logging
from datetime import datetime, timedelta
from typing import Optional, Union, Dict, Any

logger = logging.getLogger("BotScheduler")

class BotScheduler:
    BASE_CYCLE_MINUTES = 180  # Default 3 Hours

    @classmethod
    def calculate_next_run(cls, account_id: Union[str, int], is_bot_running: bool, base_minutes: Optional[int] = None) -> Optional[datetime]:
        """
        Calculates the next run datetime with staggered jitter (-5m to +5m).
        If the bot is stopped (is_bot_running is False), returns None immediately to clear/reset the timer.
        """
        if not is_bot_running:
            return None  # Reset or clear time if bot is stopped

        base = int(base_minutes) if (base_minutes and base_minutes > 0) else cls.BASE_CYCLE_MINUTES
        # Add a staggered jitter offset (-5 to +5 minutes) to prevent identical execution times
        jitter_offset_minutes = random.randint(-5, 5)
        total_interval = max(5, base + jitter_offset_minutes)
        
        next_run_time = datetime.now() + timedelta(minutes=total_interval)
        return next_run_time

    @classmethod
    def calculate_global_next_run(cls, is_bot_running: bool, base_minutes: Optional[int] = None) -> Optional[datetime]:
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
