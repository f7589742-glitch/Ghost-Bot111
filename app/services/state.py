"""
state.py - Global Fleet State & Target Registry for Rise of Kingdoms Headless Bot.
Provides persistent in-memory and database-backed entity locking across accounts,
tasks, and workers to prevent barbarian target collisions.
"""

import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("state_registry")

class SharedFleetRegistry:
    """
    Fleet-wide target reservation registry.
    Ensures that an entity (e.g. barbarian) locked by Account A is never targeted
    by Account B or by subsequent marches from the same account.
    """
    _locks: Dict[int, Dict[str, Any]] = {}

    @classmethod
    def lock_barbarian(
        cls,
        entity_id: int,
        role_id: str = "",
        kingdom_id: int = 0,
        character_name: str = "",
        barb_level: int = 0,
        pos_x: float = 0.0,
        pos_y: float = 0.0,
        ttl_seconds: int = 180
    ) -> bool:
        """
        Attempts to lock an entity for ttl_seconds.
        Returns True if successfully locked, False if already claimed by someone else.
        """
        now = time.time()
        cls.cleanup_expired()

        eid = int(entity_id)
        existing = cls._locks.get(eid)
        if existing and existing.get("expires_at", 0) > now:
            return False

        cls._locks[eid] = {
            "entity_id": eid,
            "role_id": str(role_id),
            "kingdom_id": int(kingdom_id),
            "character_name": str(character_name),
            "barb_level": int(barb_level),
            "pos_x": float(pos_x),
            "pos_y": float(pos_y),
            "claimed_at": now,
            "expires_at": now + max(30, ttl_seconds),
        }

        try:
            from app.models import BarbarianReservationDAO
            BarbarianReservationDAO.claim_barbarian(
                entity_id=eid,
                role_id=str(role_id),
                kingdom_id=int(kingdom_id),
                character_name=str(character_name),
                barb_level=int(barb_level),
                pos_x=float(pos_x),
                pos_y=float(pos_y),
                ttl_seconds=ttl_seconds
            )
        except Exception:
            pass

        return True

    @classmethod
    def is_locked(cls, entity_id: int, kingdom_id: int = 0, role_id: Optional[str] = None) -> bool:
        now = time.time()
        cls.cleanup_expired()
        eid = int(entity_id)

        existing = cls._locks.get(eid)
        if existing and existing.get("expires_at", 0) > now:
            if role_id and str(existing.get("role_id")) == str(role_id):
                return False
            return True

        try:
            from app.models import BarbarianReservationDAO
            db_claimed = BarbarianReservationDAO.get_claimed_barbarians(int(kingdom_id))
            if eid in db_claimed:
                claimed_role = str(db_claimed[eid].get("role_id", ""))
                if role_id and claimed_role == str(role_id):
                    return False
                return True
        except Exception:
            pass

        return False

    @classmethod
    def get_claimed_barbarians(cls, kingdom_id: int = 0) -> Dict[int, Dict[str, Any]]:
        now = time.time()
        cls.cleanup_expired()
        result: Dict[int, Dict[str, Any]] = {}

        try:
            from app.models import BarbarianReservationDAO
            result.update(BarbarianReservationDAO.get_claimed_barbarians(int(kingdom_id)))
        except Exception:
            pass

        for eid, info in cls._locks.items():
            if info.get("expires_at", 0) > now:
                if kingdom_id == 0 or info.get("kingdom_id", 0) == int(kingdom_id):
                    result[eid] = info

        return result

    @classmethod
    def release_barbarian(cls, entity_id: int, kingdom_id: int = 0, role_id: Optional[str] = None) -> None:
        eid = int(entity_id)
        if eid in cls._locks:
            if role_id is None or str(cls._locks[eid].get("role_id", "")) == str(role_id):
                cls._locks.pop(eid, None)

        try:
            from app.models import BarbarianReservationDAO
            BarbarianReservationDAO.release_barbarian(eid, int(kingdom_id), role_id)
        except Exception:
            pass

    @classmethod
    def cleanup_expired(cls) -> None:
        now = time.time()
        expired = [eid for eid, info in cls._locks.items() if info.get("expires_at", 0) <= now]
        for eid in expired:
            cls._locks.pop(eid, None)
