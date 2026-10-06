"""
Clean activity telemetry — the single source of truth for the customer-facing
dashboard feed.

`CleanActivityStream` and `TenantActivityStream` keep a per-bot bounded history
of clean activity lines partitioned strictly by bot_id.
"""
import time
from collections import deque
from typing import Deque, List, Optional


def _fmt_troop_tier(meta: Optional[dict], default: str = "troops") -> str:
    """Dominant troop tier string, e.g. 'T1 Siege'. Falls back to 'troops'."""
    if not meta:
        return default
    tier = meta.get("unit_tier") or meta.get("tier")
    unit = meta.get("unit_name") or meta.get("unit")
    if tier and unit:
        t = str(tier).strip()
        tier_prefix = t.upper() if t.upper().startswith("T") else f"T{t}"
        unit_clean = str(unit).strip()
        if unit_clean.lower() in t.lower():
            return t if t.upper().startswith("T") else f"T{t}"
        return f"{tier_prefix} {unit_clean}"
    if tier:
        t = str(tier).strip()
        return t if t.upper().startswith("T") else f"T{t}"
    return default


def _fmt_int(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value or 0)


class TenantActivityStream:
    """Strict SaaS Multi-Tenant log buffer partitioned strictly by bot_id."""
    _tenant_buffers: dict = {}  # {bot_id: deque(maxlen=100)}

    @classmethod
    def _normalize(cls, bot_id: Optional[str]) -> str:
        if not bot_id:
            return ""
        bid = str(bot_id).strip()
        if bid.endswith("2404"):
            return "bot-2404"
        if bid.endswith("2911"):
            return "bot-2911"
        return bid

    @classmethod
    def emit(cls, bot_id: str, char_name: Optional[str], message: str) -> None:
        if not bot_id:
            return
        bid = str(bot_id).strip()
        norm = cls._normalize(bid)
        timestamp = time.strftime("%I:%M:%S %p")
        if char_name:
            log_line = f"{timestamp} [{char_name}] {message}"
        else:
            log_line = f"{timestamp} {message}"

        if norm not in cls._tenant_buffers:
            cls._tenant_buffers[norm] = deque(maxlen=100)
        cls._tenant_buffers[norm].append(log_line)

        # Also store under raw key if different
        if bid != norm:
            if bid not in cls._tenant_buffers:
                cls._tenant_buffers[bid] = deque(maxlen=100)
            cls._tenant_buffers[bid].append(log_line)

    @classmethod
    def get_buffer(cls, bot_id: str) -> List[str]:
        if not bot_id:
            return []
        bid = str(bot_id).strip()
        norm = cls._normalize(bid)

        if bid in cls._tenant_buffers and cls._tenant_buffers[bid]:
            return list(cls._tenant_buffers[bid])
        if norm in cls._tenant_buffers and cls._tenant_buffers[norm]:
            return list(cls._tenant_buffers[norm])

        # Check aliases
        if norm == "bot-2404":
            for alias in ("bot-1789264332404", "bot-2404", "2404"):
                if alias in cls._tenant_buffers and cls._tenant_buffers[alias]:
                    return list(cls._tenant_buffers[alias])
        elif norm == "bot-2911":
            for alias in ("bot-1789264332911", "bot-2911", "2911"):
                if alias in cls._tenant_buffers and cls._tenant_buffers[alias]:
                    return list(cls._tenant_buffers[alias])
        return []

    @classmethod
    def clear(cls, bot_id: str) -> None:
        bid = str(bot_id).strip()
        norm = cls._normalize(bid)
        keys = (bid, norm, "bot-2404", "bot-1789264332404", "2404") if norm == "bot-2404" else (bid, norm, "bot-2911", "bot-1789264332911", "2911")
        for k in keys:
            if k in cls._tenant_buffers:
                cls._tenant_buffers[k].clear()


class CleanActivityStream:
    """Per-bot bounded deque of clean activity lines ({text,id} dicts)."""

    # { bot_id: deque(maxlen=200) }
    _streams: dict = {}
    _maxlen = 200

    @classmethod
    def _bucket(cls, bot_id: str) -> Deque:
        dq = cls._streams.get(bot_id)
        if dq is None:
            dq = deque(maxlen=cls._maxlen)
            cls._streams[bot_id] = dq
        return dq

    @classmethod
    def emit(cls, bot_id: str, char_name: Optional[str], message: str, meta: Optional[dict] = None) -> None:
        """Append a clean line."""
        if not bot_id:
            return
        message = (message or "").strip()
        if not message:
            return

        # ----- Rich template overrides (metadata-driven rendering) -----
        if meta is not None:
            m = meta
            tier_str = _fmt_troop_tier(m, "troops")
            commander = m.get("commander")
            if message.startswith("gather:") and char_name:
                msg = (
                    f"⛏️ [{char_name}] Sent gatherer [{commander or 'Auto'}] to {m.get('resource', 'Resource')} level {m.get('level', '?')} "
                    f"({_fmt_int(m.get('troops', 0))} {tier_str}, cargo {_fmt_int(m.get('cargo', 0))}, node reserves {_fmt_int(m.get('node_reserve', 0))})"
                )
                char_name = None  # already embedded
            elif message.startswith("barb_dispatch:") and char_name:
                msg = (
                    f"🏹 [{char_name}] Hunting Barbarians: Queue {m.get('queue_index', '?')}/{m.get('total_queues', '?')} -> "
                    f"Dispatched to Barbarian Lvl {m.get('level', '?')} ([{commander or 'Auto'}], {_fmt_int(m.get('troops', 0))} {tier_str})"
                )
                char_name = None
            elif message.startswith("barb_done:") and char_name:
                msg = f"⚔️ [{char_name}] Barbarian combat finished. All marches returned safely."
                char_name = None
            elif message.startswith("train:") and char_name:
                building = m.get("building")
                level = m.get("level")
                if building:
                    lv = f" (Lv.{level})" if level not in (None, "", 0) else ""
                    msg = f"⚔️ [{char_name}] Trained {_fmt_int(m.get('count', 0))} {tier_str} in {building}{lv}"
                else:
                    msg = f"⚔️ [{char_name}] Trained {_fmt_int(m.get('count', 0))} {tier_str}"
                char_name = None
            elif message.startswith("heal:") and char_name:
                msg = f"🏥 [{char_name}] Healed {_fmt_int(m.get('count', 0))} wounded troops ({tier_str})"
                char_name = None
            elif message.startswith("donate:") and char_name:
                msg = f"🔬 [{char_name}] Donated {m.get('stars', 1)} stars to alliance tech"
                char_name = None
            elif message.startswith("help:") and char_name:
                msg = f"🤝 [{char_name}] Helped {m.get('help_count', 'all')} alliance members"
                char_name = None
            elif message.startswith("pit:") and char_name:
                msg = f"🏛️ [{char_name}] Checking alliance resource pit"
                char_name = None
            elif message.startswith("harvest:") and char_name:
                msg = f"🌾 [{char_name}] Collected {_fmt_int(m.get('food', 0))} Food, {_fmt_int(m.get('wood', 0))} Wood from city buildings"
                char_name = None
            elif message.startswith("vip:") and char_name:
                msg = f"👑 [{char_name}] Claimed VIP daily chest & points"
                char_name = None
            elif message.startswith("mail:") and char_name:
                msg = f"📜 [{char_name}] Claimed quest rewards & mail chests"
                char_name = None
            elif message.startswith("switch:") and char_name:
                msg = f"🔄 Switching to {char_name}"
                char_name = None
            elif message.startswith("visit_start:") and char_name:
                msg = f"🏰 [{char_name}] Starting visit for {char_name}"
                char_name = None
            elif message.startswith("visit_done:") and char_name:
                msg = f"✅ [{char_name}] Finished visit for {char_name}"
                char_name = None
            else:
                msg = message
        else:
            msg = message

        timestamp = time.strftime("%I:%M:%S %p")
        if char_name and not msg.startswith("🔄"):
            line = f"{timestamp} [{char_name}] {msg}"
        else:
            line = f"{timestamp} {msg}"
        cls._bucket(str(bot_id)).append({"id": f"{time.time()}", "text": line})
        # Mirror to TenantActivityStream
        TenantActivityStream.emit(bot_id, char_name, msg)

    @classmethod
    def recent(cls, bot_id: str, limit: Optional[int] = None) -> List[dict]:
        dq = cls._streams.get(str(bot_id))
        if dq is None:
            return []
        items = list(dq)
        return items[-limit:] if limit else items

    @classmethod
    def recent_text(cls, bot_id: str, limit: Optional[int] = None) -> List[str]:
        return [item["text"] for item in cls.recent(bot_id, limit)]

    @classmethod
    def clear(cls, bot_id: str) -> None:
        cls._streams.pop(str(bot_id), None)
        TenantActivityStream.clear(bot_id)


def unit_str(meta: dict) -> str:
    return meta.get("unit_name") or meta.get("unit") or "units"


# Singletons
clean_activity = CleanActivityStream()
tenant_activity = TenantActivityStream
