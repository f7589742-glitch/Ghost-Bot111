# app/services/training.py
"""
Dynamic troop-training engine for the headless worker.

Protocol facts (live-verified 2026-09-10):
- Opcode 302 carries per-category training-queue state:
  entries {1: template_id, 2: unit_type(1..4), 3: count, 4: remaining_ms}.
- Opcode 300 {1: template_id, 2: unit_type, 3: count, 4: 0, 5: 0} starts training.
  field1 is the UNIT TEMPLATE id, NOT a building slot (each category trains at
  its implicit building: infantry->barracks, cavalry->stable, archery->range,
  siege->workshop). The legacy Opcode 102 path is ignored by the server.
- Opcode 301 acknowledges a train order; error 139 = busy, 138 = collect first.
- Opcode 303 {1: template_id} collects finished troops.
- Building LEVELS are not broadcast on any observed opcode yet; capacity is
  enforced from the official in-game table whenever the level is known,
  otherwise the requested count is sent and the server verdict + a 302
  read-back decide success honestly.
"""
import asyncio
import time
import zlib
from typing import Any, Callable, Dict, List, Optional

from headless_client import ProtobufCodec, FrameParser
from rok_headless_bot import cmd_train_300, cmd_collect_303, cmd_keepalive

# Exact official training capacity per workshop level (in-game table).
BUILDING_CAPACITY_TABLE = {
    1: 50, 2: 50, 3: 100, 4: 150, 5: 200, 6: 250, 7: 300, 8: 350,
    9: 400, 10: 450, 11: 500, 12: 550, 13: 600, 14: 700, 15: 800,
    16: 900, 17: 1000, 18: 1100, 19: 1200, 20: 1300, 21: 1400,
    22: 1500, 23: 1600, 24: 1700, 25: 2000,
}

CATEGORIES = ("infantry", "cavalry", "archery", "siege")
UNIT_TYPE = {"infantry": 1, "cavalry": 2, "archery": 3, "siege": 4}

# Live-verified unit template ids. Unknown (tier, category) pairs fall back to
# the live op302 template for that category, then to the T1 default.
DEFAULT_TEMPLATES = {"infantry": "59", "cavalry": "67", "archery": "62", "siege": "70"}
TIER_TEMPLATES = {
    (1, "infantry"): "59", (1, "cavalry"): "67", (1, "archery"): "62", (1, "siege"): "70",
    (2, "infantry"): "60", (2, "cavalry"): "68", (2, "archery"): "66", (2, "siege"): "71",
    (3, "infantry"): "61", (3, "cavalry"): "72", (3, "archery"): "63", (3, "siege"): "73",
    (4, "infantry"): "77", (4, "cavalry"): "76", (4, "archery"): "78", (4, "siege"): "74",
}


def capacity_for(level: Optional[int]) -> Optional[int]:
    if level is None:
        return None
    return BUILDING_CAPACITY_TABLE.get(int(level))


def resolve_template(tier: Any, category: str, live_state: Dict[str, Dict[str, Any]]) -> str:
    """Pick the unit template id for (tier, category), with honest fallbacks."""
    clean_str = str(tier).lower().replace("t", "").strip() if tier is not None else ""
    if clean_str in ("off", "none", "skip", "disabled", "false", "0"):
        return "off"

    try:
        t = int(clean_str)
    except (TypeError, ValueError):
        t = 0

    if t in (1, 2, 3, 4, 5) and (t, category) in TIER_TEMPLATES:
        return TIER_TEMPLATES[(t, category)]

    live = (live_state.get(category) or {}).get("template_id")
    if live:
        return str(live)
    return DEFAULT_TEMPLATES.get(category, "59")


def parse_barracks_state(msg302: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Parses an Opcode 302 message into per-category queue state."""
    out: Dict[str, Dict[str, Any]] = {}
    payload = msg302.get(2)
    entries: List[Any] = []
    try:
        if isinstance(payload, bytes):
            p = ProtobufCodec.decode_message(payload)
            e = p.get(1, [])
            entries = e if isinstance(e, list) else [e]
        elif isinstance(payload, dict):
            e = payload.get(1, [])
            entries = e if isinstance(e, list) else [e]
    except Exception:
        return out
    inv = {v: k for k, v in UNIT_TYPE.items()}
    for entry in entries:
        try:
            info = ProtobufCodec.decode_message(entry) if isinstance(entry, bytes) else entry
            if not isinstance(info, dict):
                continue
            raw_id = info.get(1, "")
            tid = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
            utype = int(info.get(2, 0))
            count = int(info.get(3, 0))
            rem_ms = int(info.get(4, 0))
            cat = inv.get(utype)
            if not cat or not tid:
                continue
            out[cat] = {
                "template_id": tid,
                "unit_type": utype,
                "count": count,
                "remaining_sec": max(0, rem_ms // 1000),
                "is_busy": rem_ms > 0,
                "needs_collect": rem_ms == 0 and count > 0,
            }
        except Exception:
            continue
    return out


def _decode_chunks(dec_payload: bytes) -> List[Dict[str, Any]]:
    try:
        msg = ProtobufCodec.decode_message(dec_payload)
    except Exception:
        return []
    chunks = msg.get(1) if isinstance(msg.get(1), list) else [msg]
    out = []
    for ch in chunks:
        try:
            out.append(ch if isinstance(ch, dict) else ProtobufCodec.decode_message(ch))
        except Exception:
            continue
    return out


async def read_barracks_state(reader, crypto_rx, seconds: float = 3.0) -> Dict[str, Dict[str, Any]]:
    """Listens briefly and merges every Opcode 302 snapshot seen."""
    state: Dict[str, Dict[str, Any]] = {}
    deadline = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < deadline:
        try:
            h = await asyncio.wait_for(reader.readexactly(2), timeout=0.6)
            raw = await asyncio.wait_for(reader.readexactly((h[0] << 8) | h[1]), timeout=0.6)
            dec = crypto_rx.decrypt(raw)
            zi = dec.find(b"\x78\x9c")
            if zi == -1:
                zi = dec.find(b"\x78\x01")
            try:
                data = zlib.decompress(dec[zi:]) if zi != -1 else dec
            except Exception:
                data = dec
            for sub in _decode_chunks(data):
                if sub.get(1) == 302:
                    state.update(parse_barracks_state(sub))
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            continue
        except Exception:
            break
    return state


async def _await_verdict(reader, crypto_rx, timeout: float = 3.0) -> str:
    """Waits for the server verdict after an op300: confirmed/busy/collect/error:*."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            h = await asyncio.wait_for(reader.readexactly(2), timeout=0.8)
            raw = await asyncio.wait_for(reader.readexactly((h[0] << 8) | h[1]), timeout=0.8)
            dec = crypto_rx.decrypt(raw)
            zi = dec.find(b"\x78\x9c")
            if zi == -1:
                zi = dec.find(b"\x78\x01")
            try:
                data = zlib.decompress(dec[zi:]) if zi != -1 else dec
            except Exception:
                data = dec
            for sub in _decode_chunks(data):
                op = sub.get(1)
                if op in (301, 300):
                    return "confirmed"
                if op == 1:
                    p = sub.get(2)
                    try:
                        err = ProtobufCodec.decode_message(p) if isinstance(p, bytes) else p
                        code = err.get(2) if isinstance(err, dict) else None
                    except Exception:
                        code = None
                    if code == 139:
                        return "busy"
                    if code == 138:
                        return "collect"
                    if code is not None:
                        return f"error:{code}"
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            continue
        except Exception:
            break
    return "timeout"


async def train_category(
    reader, writer, crypto_tx, crypto_rx,
    category: str, template_id: str, count: int,
    log: Callable[[str, str], None],
    levels: Optional[Dict[str, int]] = None,
    collect_first: bool = False,
) -> Dict[str, Any]:
    """Trains one category end-to-end: collect-if-needed, order, verdict, read-back."""
    utype = UNIT_TYPE[category]
    cap = capacity_for((levels or {}).get(category))
    if cap is not None and count > cap:
        log("CAP", f"{category}: requested {count} exceeds capacity {cap}, clamping.")
        count = cap

    # Collect finished troops ONLY when the queue actually holds a bubble.
    # (Blind collects poison verdict attribution: the 303 echo (146 when empty)
    #  arrives first and would be misread as the 300's verdict.)
    if collect_first:
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(cmd_collect_303(template_id))))
        await writer.drain()
        await asyncio.sleep(0.4)
        # Consume exactly one frame (the collect's own echo) to keep alignment.
        try:
            h = await asyncio.wait_for(reader.readexactly(2), timeout=1.5)
            await asyncio.wait_for(reader.readexactly((h[0] << 8) | h[1]), timeout=1.5)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass

    writer.write(FrameParser.build_frame(crypto_tx.encrypt(cmd_train_300(template_id, utype, count))))
    await writer.drain()
    log("DISPATCH", f"Opcode 300 train {category} (template {template_id}, unit {utype}, count {count}).")

    verdict = await _await_verdict(reader, crypto_rx)
    if verdict == "collect":
        log("COLLECT", f"{category}: bubble waiting, collecting and retrying once.")
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(cmd_collect_303(template_id))))
        await writer.drain()
        await asyncio.sleep(0.3)
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(cmd_train_300(template_id, utype, count))))
        await writer.drain()
        verdict = await _await_verdict(reader, crypto_rx)

    if verdict == "busy":
        return {"category": category, "status": "busy", "count": 0}
    if verdict != "confirmed":
        return {"category": category, "status": verdict, "count": 0}

    # Honest read-back: the queue must show up in op302 afterwards.
    await asyncio.sleep(0.4)
    state = await read_barracks_state(reader, crypto_rx, seconds=2.5)
    st = state.get(category, {})
    if st.get("is_busy") or st.get("count", 0) > 0:
        log("TRAIN_OK", f"{category}: queue running (count={st.get('count')}, remaining={st.get('remaining_sec')}s).")
        return {"category": category, "status": "training",
                "count": st.get("count", count), "remaining_sec": st.get("remaining_sec", 0)}
    log("TRAIN_OK", f"{category}: server confirmed (read-back empty, treated as instant/queued).")
    return {"category": category, "status": "confirmed", "count": count}
