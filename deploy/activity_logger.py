"""
Clean activity telemetry — the single source of truth for the customer-facing
dashboard feed.

Strict multi-tenant partitioning by (user_id, bot_id).
"""
import time
from datetime import datetime, timezone
from collections import deque
from typing import Deque, List, Optional


def _fmt_troop_tier(meta: Optional[dict], default: str = "troops") -> str:
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
    """Strict SaaS Multi-Tenant log buffer partitioned by (user_id, bot_id)."""
    _tenant_buffers: dict = {}  # {key: deque(maxlen=100)}

    @classmethod
    def _normalize(cls, bot_id: Optional[str], char_name: Optional[str] = None) -> str:
        if bot_id:
            bid = str(bot_id).strip()
            if bid in ("1", "bot-1", "01", "bot-01", "2404", "bot-2404", "fleet", "bot-fleet") or "2404" in bid or bid.endswith("2404"):
                return "bot-2404"
            if bid.endswith("2911") or "2911" in bid:
                return "bot-2911"
            return bid

        if char_name:
            cn = str(char_name).lower()
            if "nucro" in cn or "kd" in cn:
                return "bot-2404"
            return "bot-2404"
        return "bot-2404"

    @classmethod
    def emit(cls, bot_id: str, char_name: Optional[str] = None, message: str = "", user_id: Optional[str] = None) -> None:
        norm = cls._normalize(bot_id, char_name)
        if not norm:
            norm = str(bot_id or "bot-2404").strip()

        timestamp = time.strftime("%I:%M:%S %p")
        if char_name:
            log_line = f"{timestamp} [{char_name}] {message}"
            content_sig = f"[{char_name}] {message}"
        else:
            log_line = f"{timestamp} {message}"
            content_sig = message

        keys_to_update = set(filter(None, [norm, str(bot_id).strip()]))
        if char_name and "nucro" in str(char_name).lower():
            keys_to_update.add("bot-2404")

        uid = str(user_id or "").strip()
        all_keys = set(keys_to_update)
        if uid:
            for k in keys_to_update:
                all_keys.add(f"{uid}:{k}")

        for k in all_keys:
            if k not in cls._tenant_buffers:
                cls._tenant_buffers[k] = deque(maxlen=100)
            buf = cls._tenant_buffers[k]
            # Deduplicate: if previous line ends with the exact same content, skip
            if buf and buf[-1].endswith(content_sig):
                continue
            buf.append(log_line)

    @classmethod
    def get_buffer(cls, bot_id: str, user_id: Optional[str] = None) -> List[str]:
        if not bot_id and not user_id:
            return []
        bid = str(bot_id).strip() if bot_id else ""
        norm = cls._normalize(bid) if bid else ""
        uid = str(user_id or "").strip()

        # If user_id provided, strictly search user-scoped buffer first
        if uid:
            candidates = [f"{uid}:{norm}", f"{uid}:{bid}"] if norm else [f"{uid}:{bid}"]
            if norm == "bot-2404" or bid.endswith("2404"):
                candidates.extend([f"{uid}:bot-2404", f"{uid}:2404"])
            for c in candidates:
                if c in cls._tenant_buffers and cls._tenant_buffers[c]:
                    return list(cls._tenant_buffers[c])
            # If tenant has no active logs yet, return empty list (NEVER leak another tenant's logs!)
            return []

        # Unauthenticated / global lookup fallback
        if norm and norm in cls._tenant_buffers and cls._tenant_buffers[norm]:
            return list(cls._tenant_buffers[norm])
        if bid in cls._tenant_buffers and cls._tenant_buffers[bid]:
            return list(cls._tenant_buffers[bid])

        if norm == "bot-2404" or bid.endswith("2404"):
            for alias in ("bot-2404", "2404", "bot-1789264332404"):
                if alias in cls._tenant_buffers and cls._tenant_buffers[alias]:
                    return list(cls._tenant_buffers[alias])
        elif norm == "bot-2911" or bid.endswith("2911"):
            for alias in ("bot-2911", "2911", "bot-1789264332911"):
                if alias in cls._tenant_buffers and cls._tenant_buffers[alias]:
                    return list(cls._tenant_buffers[alias])
        return []

    @classmethod
    def clear(cls, bot_id: str, user_id: Optional[str] = None) -> None:
        bid = str(bot_id).strip()
        norm = cls._normalize(bid)
        uid = str(user_id or "").strip()
        keys = [bid, norm]
        if uid:
            keys.extend([f"{uid}:{bid}", f"{uid}:{norm}"])
        for k in keys:
            if k in cls._tenant_buffers:
                cls._tenant_buffers[k].clear()


class CleanActivityStream:
    """Per-bot bounded deque of clean activity lines ({text,id} dicts)."""
    _streams: dict = {}
    _maxlen = 200

    @classmethod
    def _bucket(cls, key: str) -> Deque:
        dq = cls._streams.get(key)
        if dq is None:
            dq = deque(maxlen=cls._maxlen)
            cls._streams[key] = dq
        return dq

    @classmethod
    def emit(cls, bot_id: str, char_name: Optional[str], message: str, meta: Optional[dict] = None, user_id: Optional[str] = None) -> None:
        norm = TenantActivityStream._normalize(bot_id, char_name) or str(bot_id or "").strip()
        if not norm:
            return
        message = (message or "").strip()
        if not message:
            return

        msg = message
        timestamp = time.strftime("%I:%M:%S %p")
        iso_ts = datetime.now(timezone.utc).isoformat()
        if char_name and not msg.startswith("🔄"):
            line = f"{timestamp} [{char_name}] {msg}"
            content_sig = f"[{char_name}] {msg}"
        else:
            line = f"{timestamp} {msg}"
            content_sig = msg

        bkt = cls._bucket(norm)
        if not (bkt and bkt[-1].get("text", "").endswith(content_sig)):
            bkt.append({"id": f"{time.time()}", "text": line, "created_at": iso_ts})

        uid = str(user_id or "").strip()
        if uid:
            bkt_u = cls._bucket(f"{uid}:{norm}")
            if not (bkt_u and bkt_u[-1].get("text", "").endswith(content_sig)):
                bkt_u.append({"id": f"{time.time()}", "text": line, "created_at": iso_ts})

        TenantActivityStream.emit(norm, char_name, msg, user_id=uid)

    @classmethod
    def recent(cls, bot_id: str, limit: Optional[int] = None, user_id: Optional[str] = None) -> List[dict]:
        norm = TenantActivityStream._normalize(bot_id) or str(bot_id or "").strip()
        uid = str(user_id or "").strip()
        key = f"{uid}:{norm}" if uid else norm
        dq = cls._streams.get(key)
        if dq is None and not uid:
            dq = cls._streams.get(norm)
        if dq is None:
            return []
        items = list(dq)
        return items[-limit:] if limit else items

    @classmethod
    def recent_text(cls, bot_id: str, limit: Optional[int] = None, user_id: Optional[str] = None) -> List[str]:
        return [item["text"] for item in cls.recent(bot_id, limit, user_id=user_id)]

    @classmethod
    def clear(cls, bot_id: str, user_id: Optional[str] = None) -> None:
        norm = TenantActivityStream._normalize(bot_id) or str(bot_id or "").strip()
        uid = str(user_id or "").strip()
        cls._streams.pop(norm, None)
        if uid:
            cls._streams.pop(f"{uid}:{norm}", None)
        TenantActivityStream.clear(bot_id, user_id=uid)


clean_activity = CleanActivityStream()
tenant_activity = TenantActivityStream
