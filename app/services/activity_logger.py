"""
Clean bilingual activity telemetry — the single source of truth for the
customer-facing dashboard feed.

Strict multi-tenant partitioning by (user_id, bot_id).
Entries are stored as (timestamp, arabic, english-or-None) tuples and rendered
in the requested language at read time, so the website language toggle
instantly switches the whole visible stream. Raw engine logs (bot.err)
always keep full untranslated detail for debugging.
"""
import datetime
import re
import time
from datetime import datetime, timezone
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple


def clean_line(text: str) -> str:
    """Make one activity line human-clean without losing meaning."""
    if not text:
        return ""
    out = str(text)
    # 1. Drop 2nd+ identical [Name] tags in the same line.
    seen_tags = set()

    def _dedup_tag(m):
        tag = m.group(1)
        if tag in seen_tags:
            return ""
        seen_tags.add(tag)
        return m.group(0)

    out = re.sub(r"\[([^\]\[]+)\]", _dedup_tag, out)
    # 2. Reject clusters CODE(SUB) -> CODE  (8602(322) -> 8602).
    out = re.sub(r"(\d{2,})\(\d{2,}\)", r"\1", out)
    # 3. Bare 3+ digit server codes in parens -> drop ((5502), (3536)).
    #    1-2 digit counts ((2), (1)) and worded groups are preserved.
    out = re.sub(r"\(\d{3,}\)", "", out)
    # 4. Collapse whitespace left behind.
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return out


#: Wire-ID -> readable commander name. PROVEN entries (troops-panel names
#: matched 1:1 with official 1012 packets + detail+367 triangulation on two
#: accounts): 15, 102, 134, 24, 32, 572, 38, 34, 61. LEGACY entries below
#: are long-standing labels, unverified individually - kept so logs stay
#: readable; anything else falls back to "Commander {id}", never a guess.
HERO_NAMES = {
    15: "Joan of Arc",
    102: "Seondeok",
    134: "Queen Tamar of Georgia",
    24: "Centurion",
    32: "Ishida Mitsunari",
    572: "Matilda of Flanders",
    38: "Sarka",
    34: "Gaius Marius",
    33: "Constance",
    61: "Belisarius",
    7: "Eulji Mundeok",
    3: "Sun Tzu",
    36: "Lancelot",
    13: "Kusunoki Masashige",
    35: "Tomoe Gozen",
    23: "Markswoman",
    12: "Osman I",
    9: "Hermann",
    11: "Baibars",
    5: "Pelagius",
    6: "Lohar",
    2: "Cao Cao",
    1: "City Keeper",
}


def resolve_hero(hero_id, level: int = 0) -> str:
    """Readable commander name for a wire hero ID (honest fallback).

    Unknown IDs are never guessed - they render as ``Commander {id}``
    with live level when known (``Commander 25 (L11)``) so the owner can
    match them in-game.
    """
    try:
        hid = int(hero_id)
    except (TypeError, ValueError):
        return f"Commander {hero_id}"
    name = HERO_NAMES.get(hid)
    if name:
        return name
    try:
        lvl = int(level or 0)
    except (TypeError, ValueError):
        lvl = 0
    return f"Commander {hid} (L{lvl})" if lvl > 0 else f"Commander {hid}"


def clean_node_name(name: str, lang: str = "ar") -> str:
    """Feed-safe resource node name.

    Pit/node names arrive raw from the game server in the account's game
    language (often Arabic). Arabic UI keeps the real server name; English
    UI gets a generic label instead of a mixed-language fragment.
    """
    name = str(name or "").strip() or "alliance resource field"
    if lang == "en":
        if re.search(r"[\u0600-\u06FF]", name):
            return "alliance resource field"
        if name.lower() in ("alliance_pit", "alliance pit", "pit", "super_node"):
            return "alliance resource field"
    return name


class TelemetryLogger:
    """Structured bilingual event templates (STARTUP/LOGIN/SWITCH/MARCH...)."""

    @staticmethod
    def format_event(event_type: str, data: Dict[str, Any], lang: str = "ar") -> Dict[str, Any]:
        now = datetime.datetime.now().strftime("%I:%M:%S %p")
        category = str(data.get("category", "SYSTEM")).upper()
        msg = ""
        if lang == "en":
            if event_type == "STARTUP_HEADER":
                msg = (f"🚀 GhostBot | License: {data.get('plan', 'Pro')} "
                       f"| Slots In Use: {data.get('used_slots', 0)}/{data.get('max_slots', 25)} "
                       f"(Total Governors: {data.get('total_chars', 0)})")
            elif event_type == "EMAIL_LOGIN":
                msg = f"🔑 [Game Login] Successfully authenticated account: {data.get('email')}"
            elif event_type == "SWITCH_CHARACTER":
                msg = f"🔄 [Governor Switch] Switching to: {data.get('role_name')} (ID: {data.get('role_id')})"
            elif event_type == "CITY_HARVEST":
                msg = f"🌾 [City Harvest] Collected production from all {data.get('buildings_count', 34)} resource buildings"
            elif event_type == "CHRONICLE_CLAIM":
                msg = "[Chronicle] Checked and claimed available Kingdom Chronicle milestone rewards"
            elif event_type == "ALLIANCE_HELP":
                msg = "[Alliance Help] Assisted all alliance members with active research/construction"
            elif event_type == "ALLIANCE_GIFTS":
                msg = f"[Alliance Gifts] Claimed all alliance chests and bundle gifts ({data.get('count', 0)} claimed)"
            elif event_type == "ALLIANCE_DONATE":
                msg = f"[Alliance Tech] Donated {data.get('times', 1)} times to alliance technology (+{data.get('points', 0)} points)"
            elif event_type == "HOSPITAL_CHECK":
                msg = "🏥 [Hospital] Health check: All troops healthy (0 wounded)"
            elif event_type == "TRAIN_TROOPS":
                msg = f"⚔️ [Training] Recruiting {data.get('tier', 'T1')} {data.get('troop_type', 'Siege')} in barracks"
            elif event_type == "MARCH_DISPATCHED":
                msg = (f"🏹 [March Dispatched] [{data.get('role_name')}] March sent to: {data.get('res_name')} (Level {data.get('tile_level')}) "
                       f"| Troops: {data.get('troops_count', 0):,} ({data.get('primary')} + {data.get('secondary')})")
            elif event_type == "MARCH_STATUS":
                msg = f"📊 [Queue Status] [{data.get('role_name')}] Active marches: ({data.get('active', 0)}/{data.get('max', 5)}) | All gathering queues occupied"
            elif event_type == "SESSION_END":
                msg = f"🚪 [Session Closed] Governor [{data.get('role_name')}] cycle completed and state saved."
            else:
                msg = str(data.get("text_en", data.get("text", "")))
        else:
            if event_type == "STARTUP_HEADER":
                msg = (f"🚀 GhostBot | الباقة: {data.get('plan_ar', 'باقة المحترفين')} "
                       f"| الخانات المستخدمة: {data.get('used_slots', 0)}/{data.get('max_slots', 25)} "
                       f"(إجمالي الحكام: {data.get('total_chars', 0)})")
            elif event_type == "EMAIL_LOGIN":
                msg = f"🔑 [تسجيل الدخول] تم الدخول بنجاح إلى حساب اللعبة: {data.get('email')}"
            elif event_type == "SWITCH_CHARACTER":
                msg = f"🔄 [تبديل الشخصية] جاري التبديل إلى الحاكم: {data.get('role_name')} (المعرف: {data.get('role_id')})"
            elif event_type == "CITY_HARVEST":
                msg = f"🌾 [حصاد المدينة] تم حصاد إنتاج {data.get('buildings_count', 34)} مبنى موارد بالكامل"
            elif event_type == "CHRONICLE_CLAIM":
                msg = "[سجل المملكة] تم فحص واستلام مكافآت الجريدة المتاحة"
            elif event_type == "ALLIANCE_HELP":
                msg = "[مساعدة التحالف] تم تقديم المساعدة لكافة أعضاء التحالف"
            elif event_type == "ALLIANCE_GIFTS":
                msg = f"[هدايا التحالف] تم استلام هدايا وصناديق التحالف المتاحة ({data.get('count', 0)} صندوق)"
            elif event_type == "ALLIANCE_DONATE":
                msg = f"[تقنية التحالف] تم التبرع {data.get('times', 1)} مرة في بحوث التحالف (نقاط +{data.get('points', 0)})"
            elif event_type == "HOSPITAL_CHECK":
                msg = "🏥 [المشفى] فحص المشفى: لا توجد إصابات، القوات بحالة ممتازة"
            elif event_type == "TRAIN_TROOPS":
                msg = f"⚔️ [تجنيد القوات] جاري تدريب مقاتلين من فئة {data.get('troop_type_ar', 'عربات حصار')} ({data.get('tier', 'T1')}) في الثكنة"
            elif event_type == "MARCH_DISPATCHED":
                msg = (f"🏹 [تسيير مسيرة] [{data.get('role_name')}] تم إرسال مسيرة جمع إلى: {data.get('res_name_ar')} (مستوى {data.get('tile_level')}) "
                       f"| القوة: {data.get('troops_count', 0):,} جندي ({data.get('primary_ar', data.get('primary'))} + {data.get('secondary_ar', data.get('secondary'))})")
            elif event_type == "MARCH_STATUS":
                msg = f"📊 [حالة الطوابير] [{data.get('role_name')}] المسيرات النشطة: ({data.get('active', 0)}/{data.get('max', 5)}) | جميع طوابير الجمع مشغولة بالكامل"
            elif event_type == "SESSION_END":
                msg = f"🚪 [إنهاء الجلسة] اكتملت زيارة الحاكم [{data.get('role_name')}] وحفظ الجلسة بنجاح."
            else:
                msg = str(data.get("text_ar", data.get("text", "")))
        return {"time": now, "category": category, "message": clean_line(msg)}


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
    """Strict SaaS Multi-Tenant log buffer partitioned by (user_id, bot_id).

    Entries are stored as (timestamp, arabic, english-or-None) tuples and
    rendered in the requested language at read time, so the website language
    toggle switches the whole visible stream instantly.
    """
    _tenant_buffers: dict = {}  # {key: deque(maxlen=100) of (ts, ar, en|None)}

    @classmethod
    def _normalize(cls, bot_id: Optional[str], char_name: Optional[str] = None) -> str:
        if bot_id:
            return str(bot_id).strip().lower()
        return "bot-0"

    @classmethod
    def _prefix(cls, char_name: Optional[str], message: str) -> str:
        if char_name and f"[{char_name}]" not in message:
            return f"[{char_name}] {message}"
        return message

    @classmethod
    def emit(cls, bot_id: str, char_name: Optional[str] = None, message: str = "",
             user_id: Optional[str] = None, message_en: Optional[str] = None) -> None:
        try:
            message = clean_line(message)
            if message_en:
                message_en = clean_line(message_en)
        except Exception:
            pass
        bid = cls._normalize(bot_id, char_name)
        timestamp = time.strftime("%I:%M:%S %p")
        ar_line = cls._prefix(char_name, message or "")
        en_line = cls._prefix(char_name, message_en) if message_en else None
        content_sig = ar_line

        uid = str(user_id or "").strip()
        if not uid:
            try:
                from app.tenant_ctx import current_user_id
                cuid = current_user_id.get()
                if cuid:
                    uid = str(cuid).strip()
            except Exception:
                pass

        keys = [bid]
        if uid:
            keys.append(f"{uid}:{bid}")

        for k in keys:
            if k not in cls._tenant_buffers:
                cls._tenant_buffers[k] = deque(maxlen=100)
            buf = cls._tenant_buffers[k]
            if buf and buf[-1][1].endswith(content_sig):
                continue
            buf.append((timestamp, ar_line, en_line))

    @classmethod
    def _render(cls, entry: Tuple[str, str, Optional[str]], lang: str) -> str:
        ts, ar, en = entry
        if lang == "en" and en:
            return f"{ts} {en}"
        return f"{ts} {ar}"

    @classmethod
    def get_buffer(cls, bot_id: str, user_id: Optional[str] = None, lang: str = "ar") -> List[str]:
        if not bot_id and not user_id:
            return []
        lang = "en" if str(lang or "").lower().startswith("en") else "ar"
        bid = cls._normalize(bot_id)
        uid = str(user_id or "").strip()
        entries: List[Tuple[str, str, Optional[str]]] = []
        if uid:
            key = f"{uid}:{bid}"
            if key in cls._tenant_buffers:
                entries = list(cls._tenant_buffers[key])
        elif bid in cls._tenant_buffers and cls._tenant_buffers[bid]:
            entries = list(cls._tenant_buffers[bid])
        out: List[str] = []
        for e in entries:
            # Backward compatible: very old plain-string entries (if any).
            if isinstance(e, str):
                out.append(e)
            elif isinstance(e, (tuple, list)) and len(e) == 3:
                out.append(cls._render((str(e[0]), str(e[1]), e[2]), lang))
        return out

    @classmethod
    def clear(cls, bot_id: str, user_id: Optional[str] = None) -> None:
        bid = str(bot_id).strip()
        norm = cls._normalize(bid)
        uid = str(user_id or "").strip()
        keys = [bid, norm]
        if uid:
            keys.extend([f"{uid}:{bid}", f"{uid}:{norm}", f"{uid}:all"])
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
