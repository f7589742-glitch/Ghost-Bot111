"""
smart_gather_search.py - 100% Pure Headless Multi-March Dynamic Gather Engine
Deploys gather marches across all available queues until all free queues or troops are exhausted.
ZERO ADB, ZERO LDPlayer, ZERO emulator clicks. 100% server-streamed headless architecture.
"""

import asyncio
import os
import sys
import time
import math
import struct
import zlib
import json
import re
from typing import Dict, List, Tuple, Optional, Any, Set

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(current_dir) == "services":
    PROJECT_ROOT = os.path.dirname(os.path.dirname(current_dir))
else:
    PROJECT_ROOT = current_dir

sys.path.insert(0, os.path.join(PROJECT_ROOT, "python"))
sys.path.insert(0, PROJECT_ROOT)

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed
from cloud_role_switcher import ensure_character_active
try:
    from app.services.gathering_calculator import (
        GatheringLoadEngine,
        COMMANDER_LOAD_BONUS,
        BASE_LOAD_TABLE,
        UNIT_ID_TO_CAT_TIER,
        CAT_TIER_TO_UNIT_ID,
    )
except ImportError:
    from gathering_calculator import (
        GatheringLoadEngine,
        COMMANDER_LOAD_BONUS,
        BASE_LOAD_TABLE,
        UNIT_ID_TO_CAT_TIER,
        CAT_TIER_TO_UNIT_ID,
    )

try:
    from app.services.protocol.hero_parser import (
        parse_heroes_from_1201,
        parse_roster_from_1157,
        parse_heroes_from_1002,
        parse_heroes_from_367,
        parse_wall_garrison_from_1002,
        merge_rosters,
        persist_roster_to_db,
    )
except ImportError:
    try:
        from protocol.hero_parser import (
            parse_heroes_from_1201,
            parse_roster_from_1157,
            parse_heroes_from_1002,
            parse_heroes_from_367,
            parse_wall_garrison_from_1002,
            merge_rosters,
            persist_roster_to_db,
        )
    except ImportError:
        from hero_parser import (
            parse_heroes_from_1201,
            parse_roster_from_1157,
            parse_heroes_from_1002,
            parse_heroes_from_367,
            parse_wall_garrison_from_1002,
            merge_rosters,
            persist_roster_to_db,
        )

GATE_IP = "43.159.113.101"
GATE_PORT = 3101
ROLE_ID = 227658377
MAX_ACCOUNT_QUEUES = 5


def _collect_subs(msg, depth=0):
    """Recursively collect every {1: opcode} sub-message, digging through
    single-nested byte envelopes (the server wraps some replies, e.g. 367,
    inside an outer frame instead of sending them top-level)."""
    out = []
    if not isinstance(msg, dict) or depth > 3:
        return out
    f1 = msg.get(1)
    if isinstance(f1, int):
        out.append(msg)
    elif isinstance(f1, (bytes, bytearray)):
        try:
            out.extend(_collect_subs(ProtobufCodec.decode_message(bytes(f1)), depth + 1))
        except Exception:
            pass
    elif isinstance(f1, list):
        for it in f1:
            if isinstance(it, dict):
                out.extend(_collect_subs(it, depth + 1))
            elif isinstance(it, (bytes, bytearray)):
                try:
                    out.extend(_collect_subs(ProtobufCodec.decode_message(bytes(it)), depth + 1))
                except Exception:
                    pass
    return out

def decode_stream_chunks(frame: bytes):
    """Split ONE decrypted gateway frame into decoded {1: opcode} sub-messages.

    Handles single or concatenated zlib streams (78 9c / 78 01 / 78 da).
    Returns (data, subs): concatenated decompressed bytes + flat list of
    decoded dicts with nested byte-envelopes already unwrapped.
    This is the single choke point for all wire decoding (regression-tested).
    """
    datas: List[bytes] = []
    subs: List[Any] = []
    if not isinstance(frame, (bytes, bytearray)) or not frame:
        return b"", subs
    buf = bytes(frame)
    off = 0
    while off < len(buf):
        z1 = buf.find(b"\x78\x9c", off)
        z2 = buf.find(b"\x78\x01", off)
        z3 = buf.find(b"\x78\xda", off)
        cands = [z for z in (z1, z2, z3) if z != -1]
        if not cands:
            break
        z = min(cands)
        d = zlib.decompressobj()
        try:
            dec = d.decompress(buf[z:])
        except Exception:
            break
        consumed = len(buf[z:]) - len(d.unused_data)
        if consumed <= 0:
            break
        off = z + consumed
        datas.append(dec)
        try:
            m = ProtobufCodec.decode_message(dec)
        except Exception:
            continue
        chunks = m.get(1) if isinstance(m.get(1), list) else [m]
        for c in chunks:
            try:
                item = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
            except Exception:
                continue
            if isinstance(item, dict):
                subs.extend(_collect_subs(item))
            else:
                subs.append(item)
    return b"".join(datas), subs

def _note_march_cookies(blob: Any, active_role_id: Any,
                        busy_commanders: Set[int], active_marches: dict) -> None:
    """Record {role}_{queue}_{pri}[_{sec}] march cookies from any raw bytes.

    March state rides many opcodes (1005/1023/1024/1013/365/903), so every
    wait-loop snoops the raw decrypted frame with this single helper.
    """
    try:
        raw = bytes(blob) if isinstance(blob, (bytes, bytearray)) else b""
        if not raw:
            return
        for _mt in re.finditer(str(active_role_id).encode() + rb"_\d+_(\d+)(?:_(\d+))?", raw):
            _bp = int(_mt.group(1).decode())
            if _bp not in busy_commanders:
                busy_commanders.add(_bp)
                active_marches[f"m_{_bp}"] = _bp
            if _mt.group(2):
                _bs = int(_mt.group(2).decode())
                if _bs not in busy_commanders:
                    busy_commanders.add(_bs)
    except Exception:
        pass

def extract_inspect_key_from_1035(p2_bytes: bytes) -> Optional[int]:
    """Live map-inspect session key from Opcode 1035 (field 12).

    Ground truth (decoded_20261005_075706.txt S->C#33 and
    decoded_20260915_093117.txt S->C#33): the official client echoes this
    exact value as field 1 of every 1050 inspect. It is per-login-session
    (665603 / 682903 observed), NOT the alliance ID. Sending 1050 with the
    alliance ID (8M) instead of this key yields universal Error 135 on 1012.
    """
    try:
        if not isinstance(p2_bytes, (bytes, bytearray)) or not p2_bytes:
            return None
        m = ProtobufCodec.decode_message(bytes(p2_bytes))
        if not isinstance(m, dict):
            return None
        key = m.get(12)
        if isinstance(key, int) and not isinstance(key, bool) and 1000 <= key <= 99999999:
            return int(key)
    except Exception:
        pass
    return None


def get_max_marches_for_city_hall(ch: int) -> int:
    """Return physical concurrent march queues supported by Town Hall level."""
    if ch >= 22:
        return 5
    elif ch >= 17:
        return 4
    elif ch >= 11:
        return 3
    elif ch >= 5:
        return 2
    return 1
def parse_max_node_level(config: Any) -> int:
    """
    Parse maximum node level cap from dashboard settings/params.
    Supports keys: max_node_level, max_level, gather_max_level.
    Values: "No cap", "6", "5", "4", "3", "2", "1", None, 0, or ints.
    Clamps integer values between 1 and 6. Defaults to 6 (no cap).
    """
    val = None
    if isinstance(config, dict):
        for k in ("max_node_level", "max_level", "gather_max_level"):
            if k in config and config[k] is not None:
                val = config[k]
                break
    else:
        val = config

    if val is None:
        return 6

    if isinstance(val, str):
        cleaned = val.strip().lower()
        if cleaned in ("no cap", "nocap", "none", "", "all", "any"):
            return 6
        try:
            val = int(cleaned)
        except ValueError:
            return 6

    if isinstance(val, (int, float)):
        val = int(val)
        if val <= 0:
            return 6
        return max(1, min(6, val))

    return 6


RESOURCE_TYPE_MAP = {
    1: ("food", "Cropland"),
    2: ("wood", "Logging Camp"),
    3: ("stone", "Stone Deposit"),
    4: ("gold", "Gold Mine"),
    5: ("gem", "Gem Deposit"),
}

ALLOWED_GATHER_RESOURCES = {"food", "wood", "stone", "gold"}
def get_fleet_claimed_node_ids(kingdom_id: int) -> set:
    """Query SQLite NodeReservationDAO for active unexpired reservations across all fleet accounts."""
    try:
        from app.models import NodeReservationDAO
        # Use get_claimed_nodes which filters by expires_at > now
        claimed = NodeReservationDAO.get_claimed_nodes(int(kingdom_id))
        return set(claimed.keys())
    except Exception as e:
        print(f"[RESERVATION] DB query fallback: {e}")
        return set()

def get_configured_march_count(rss: str, cfg: dict) -> Optional[int]:
    """Extract explicit march count for a given resource type from configuration."""
    if not isinstance(cfg, dict):
        return None
    # Check direct keys (food_marches, wood_marches, stone_marches, gold_marches)
    if f"{rss}_marches" in cfg:
        try:
            return int(cfg[f"{rss}_marches"])
        except (ValueError, TypeError):
            pass
    # Check nested marches dict (marches: {"food": 1, ...})
    marches_dict = cfg.get("marches")
    if isinstance(marches_dict, dict) and rss in marches_dict:
        try:
            return int(marches_dict[rss])
        except (ValueError, TypeError):
            pass
    # Check alternative march_food, march_wood...
    if f"march_{rss}" in cfg:
        try:
            return int(cfg[f"march_{rss}"])
        except (ValueError, TypeError):
            pass
    return None

def determine_march_resource_targets(free_queues: int, config: dict, city_rss: dict) -> List[str]:
    """
    Dynamically determine resource targets for available march queues.
    
    1. Strict Zero-Allocation Exclusion:
       Any resource explicitly configured with 0 marches is strictly excluded.
    2. In-City Reserve Identification:
       Identifies the allowed resource with lowest current in-city reserve.
    3. 65% Weighted Queue Allocation:
       If auto_balance_lowest_rss is enabled:
         lowest_march_count = max(1, round(N * 0.65)) assigned to lowest reserve type.
         Remaining N - lowest_march_count distributed among other allowed types.
       If disabled:
         Uses static configured march counts/ratios.
    """
    rss_types = ["food", "wood", "stone", "gold"]
    configured_counts: Dict[str, int] = {}
    has_explicit = False

    for r in rss_types:
        cnt = get_configured_march_count(r, config)
        if cnt is not None:
            configured_counts[r] = cnt
            has_explicit = True

    if has_explicit:
        # Strict zero-allocation: only resources with count > 0 are allowed
        allowed_resources = [r for r in rss_types if configured_counts.get(r, 0) > 0]
    else:
        # Fall back to march_targets or targets
        raw = config.get("march_targets") or config.get("targets") or ["food", "wood", "stone"]
        if isinstance(raw, list) and raw:
            allowed_resources = [r for r in rss_types if r in [str(t).lower() for t in raw]]
        else:
            allowed_resources = ["food", "wood", "stone"]

    if not allowed_resources:
        if has_explicit:
            # Every resource explicitly set to 0: gathering disabled by
            # settings - no marches at all (never resurrect defaults).
            return []
        allowed_resources = ["food", "wood", "stone"]

    N = max(0, int(free_queues))
    auto_balance = bool(
        config.get("auto_balance_lowest_rss",
        config.get("auto_balance",
        config.get("prioritize_lowest_rss", False)))
    )

    if not auto_balance:
        pool = []
        for r in allowed_resources:
            cnt = configured_counts.get(r, 1) if has_explicit else 1
            pool.extend([r] * max(1, cnt))
        if not pool:
            pool = list(allowed_resources)
        return [pool[i % len(pool)] for i in range(N)]

    # Auto-balancing enabled: rank allowed resources by live city reserve
    # ascending. Lowest gets 65% (rounded, min 1); the remainder goes to the
    # NEXT-lowest first (not list order). Ties keep config order (stable).
    safe_city_rss = city_rss if isinstance(city_rss, dict) else {}
    ranked = sorted(allowed_resources,
                    key=lambda r: (int(safe_city_rss.get(r, 0) or 0),
                                   allowed_resources.index(r)))
    lowest_rss = ranked[0]
    lowest_count = max(1, round(N * 0.65))
    if lowest_count > N:
        lowest_count = N

    rem_count = N - lowest_count
    other_allowed = ranked[1:]

    if not other_allowed or rem_count == 0:
        return [lowest_rss] * N

    rem_marches = [other_allowed[i % len(other_allowed)] for i in range(rem_count)]
    return [lowest_rss] * lowest_count + rem_marches


def extract_tile_owner(item_dict) -> Tuple[int, str]:
    """True TILE ownership from 1003 item field 11.

    Ground truth (live probe on tile X:750 Y:706 owned by [4p57]):
    every node item carries field 11 = {1: owner_aid, 3: owner_tag},
    e.g. {1: 8614440, 3: b'4p57'}. The old f1.f6/f7 bytes are the OCCUPIER's
    (gatherer's) alliance, NOT the tile owner - using them let marches into
    enemy land labeled "neutral". Returns (0, "") when absent (=neutral).
    """
    try:
        if not isinstance(item_dict, dict):
            return 0, ""
        raw11 = item_dict.get(11)
        if not isinstance(raw11, (bytes, bytearray)):
            return 0, ""
        own = ProtobufCodec.decode_message(bytes(raw11))
        if not isinstance(own, dict):
            return 0, ""
        aid = own.get(1, 0)
        tag = own.get(3, b"")
        if isinstance(tag, (bytes, bytearray)):
            try:
                tag = bytes(tag).decode("utf-8", "ignore")
            except Exception:
                tag = ""
        aid = int(aid or 0)
        tag = str(tag or "").strip()
        if aid <= 0 and not tag:
            return 0, ""
        return aid, tag
    except Exception:
        return 0, ""

def is_tile_accessible(node, active_alliance_id, active_alliance_tag=None, avoid_territory=True, log_fn=None, logged_nodes=None):
    if not avoid_territory:
        return True
    try:
        # Prefer true tile ownership (field 11); fall back to legacy
        # occupier bytes when owner data is absent.
        tile_aid = node.get("owner_id")
        tile_tag = node.get("owner_tag")
        if tile_aid is None:
            tile_aid = int(node.get("alliance_id", 0) or 0)
            tile_tag = str(node.get("alliance_tag", "") or "").strip()
        else:
            tile_aid = int(tile_aid or 0)
            tile_tag = str(tile_tag or "").strip()
        my_aid = int(active_alliance_id or 0)
        my_tag = str(active_alliance_tag or "").strip()

        # Neutral Land (no owner alliance ID and no owner tag): always allowed.
        if tile_aid == 0 and not tile_tag:
            return True

        # Friendly Territory: positive match on tag OR on numeric ID.
        if my_tag and tile_tag and my_tag.upper() == tile_tag.upper():
            return True
        if my_aid > 0 and tile_aid > 0 and my_aid == tile_aid:
            return True

        # STRICT: any tile with an owner that is NOT positively ours is
        # rival territory and rejected (includes bare IDs without tags and
        # the own-unknown case, where only neutral tiles pass).
        rival = tile_tag or f"#{tile_aid}"
        if tile_aid > 0 and my_aid > 0 and tile_aid != my_aid:
            rival = f"{tile_tag}#{tile_aid}" if tile_tag else f"#{tile_aid}"
        nid = node.get("node_id")
        if log_fn:
            if logged_nodes is None or nid not in logged_nodes:
                if logged_nodes is not None and nid:
                    logged_nodes.add(nid)
                log_fn(f"[GATHER_FILTER] Node #{nid} rejected: alliance territory [{rival}] (own=[{my_tag}#{my_aid}]).")
        return False
    except Exception:
        return True

def extract_alliance_from_message(msg) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Recursively discover alliance (alliance_id, alliance_name, alliance_tag) from decoded protobuf messages."""
    found_id = None
    found_name = None
    found_tag = None

    def _walk(obj):
        nonlocal found_id, found_name, found_tag
        if found_id and found_tag:
            return
        if isinstance(obj, dict):
            # Pattern A: Standard alliance info struct {1: id, 2: name, 3: tag}
            a_id = obj.get(1)
            a_name = obj.get(2)
            a_tag = obj.get(3)
            if isinstance(a_id, int) and a_id > 1000:
                name_str = a_name.decode("utf-8", "ignore") if isinstance(a_name, bytes) else str(a_name or "")
                tag_str = a_tag.decode("utf-8", "ignore") if isinstance(a_tag, bytes) else str(a_tag or "")
                if (2 <= len(tag_str) <= 6) and (len(name_str) >= 1):
                    found_id = a_id
                    found_name = name_str
                    found_tag = tag_str
                    return

            # Pattern B: Tag 19 of player profile in Opcode 1002
            t19 = obj.get(19)
            if isinstance(t19, bytes) and 2 <= len(t19) <= 6:
                try:
                    s19 = t19.decode("utf-8", "ignore")
                    if s19.isalnum() and not found_tag:
                        found_tag = s19
                except Exception:
                    pass

            for k, v in obj.items():
                if isinstance(v, bytes) and len(v) >= 4:
                    try:
                        sub = ProtobufCodec.decode_message(v)
                        _walk(sub)
                    except Exception:
                        pass
                elif isinstance(v, (dict, list)):
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, bytes) and len(item) >= 4:
                    try:
                        sub = ProtobufCodec.decode_message(item)
                        _walk(sub)
                    except Exception:
                        pass
                elif isinstance(item, (dict, list)):
                    _walk(item)

    _walk(msg)
    return found_id, found_name, found_tag

def parse_level_filter(level_str: str) -> Tuple[int, str]:
    s = (level_str or "").strip().lower()
    if "no cap" in s or "highest" in s or s in ("0", "any"):
        return 0, "any"
    if "6 and above" in s or "6+" in s:
        return 6, "min"
    if "6 and below" in s or "6-" in s or s == "6":
        return 6, "max"
    if "5 and below" in s or "5-" in s or s == "5":
        return 5, "max"
    if "4 and below" in s or "4-" in s or s == "4":
        return 4, "max"
    if "3 and below" in s or "3-" in s or s == "3":
        return 3, "max"
    if "2 and below" in s or "2-" in s or s == "2":
        return 2, "max"
    if "1" in s:
        return 1, "exact"
    return 6, "max"

# Gathering specialists: wire IDs proven by troops-panel names matched 1:1
# with official 1012 packets (identical troop counts) + detail+367
# triangulation on two accounts. Constance=33 is medium confidence.
GATHERING_SPECIALIST_IDS: Set[int] = {
    15,  # Joan of Arc (proven)
    102, # Seondeok (proven)
    134, # Queen Tamar of Georgia (proven)
    24,  # Centurion (proven)
    32,  # Ishida Mitsunari (proven)
    572, # Matilda of Flanders (proven)
    38,  # Sarka (proven)
    34,  # Gaius Marius (proven)
    33,  # Constance (medium confidence)
}

# Verified farm account gatherers (owned across all farm accounts)
VERIFIED_FARM_GATHERERS: List[int] = [
    15,  # Joan of Arc (proven)
    38,  # Sarka (proven)
    34,  # Gaius Marius (proven)
    24,  # Centurion (proven)
    102, # Seondeok (proven)
    134, # Queen Tamar of Georgia (proven)
    32,  # Ishida Mitsunari (proven)
    572, # Matilda of Flanders (proven)
]

GATHERING_SPECIALISTS_ORDERED: List[int] = [
    15,  # Joan of Arc (proven)
    102, # Seondeok (proven)
    134, # Queen Tamar of Georgia (proven)
    24,  # Centurion (proven)
    32,  # Ishida Mitsunari (proven)
    572, # Matilda of Flanders (proven)
    38,  # Sarka (proven)
    34,  # Gaius Marius (proven)
    33,  # Constance (medium confidence)
]

# DYNAMIC ZERO-HARDCODING HERO SELECTION SYSTEM
# Levels and stars are dynamically parsed from packets / session metadata

def primary_gatherer_sort_key(h: Dict[str, Any]) -> Tuple[int, int, int]:
    lvl = int(h.get("level") or 1)
    star = int(h.get("star") or 1)
    return (-lvl, -star, h.get("hero_id", 0))

def _valid_hero_id(hid: Any) -> bool:
    return isinstance(hid, int) and not isinstance(hid, bool) and 1 <= hid <= 5000

def allocate_gathering_commanders(
    roster: List[Dict[str, Any]],
    target_queues: int,
    busy_commanders: Optional[Set[int]] = None,
    wall_garrison: Optional[Set[int]] = None,
    failed_heroes: Optional[Set[int]] = None,
    fallback_hero_ids: Optional[List[int]] = None,
) -> List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
    """
    LIVE ROSTER ONLY - ZERO HARDCODED / ZERO GUESSING:
    - Consumes ALL unlocked heroes from the live wire stream
      (op 367 authoritative catalogue + 1201/1157/1002 supplements, level >= 1).
    - Primary: gathering-category heroes first, then strongest
      (level desc, star desc). Wall/garrison commanders MAY gather.
      Only busy|failed are excluded.
    - Secondary: any owned leftover hero with level 1..10 (any category,
      weakest first so strong heroes stay primary). No level/star gate,
      no gatherer requirement. Solo when no eligible secondary exists.
    """
    if target_queues <= 0:
        return []

    busy = busy_commanders or set()
    failed = failed_heroes or set()
    wall_set = wall_garrison or set()
    # In RoK, wall garrison commanders CAN gather on the map (official game client)!
    # Do NOT exclude wall commanders. Only exclude commanders actively marching or failed this session.
    excluded = (busy - wall_set) | failed

    # All verified unlocked heroes with level >= 1 from the live stream
    unlocked_roster = []
    seen = set()
    for h in roster or []:
        hid = h.get("hero_id")
        lvl = int(h.get("level", 1) or 1)
        if hid and isinstance(hid, int) and hid not in excluded and hid not in seen:
            if lvl >= 1:
                seen.add(hid)
                h = dict(h)
                h["is_gatherer"] = bool(h.get("is_gatherer") or hid in GATHERING_SPECIALIST_IDS)
                h["is_verified_owned"] = True
                unlocked_roster.append(h)

    # Primaries: gathering specialists first, then strongest
    unlocked_roster.sort(key=lambda h: (
        0 if (h.get("hero_id") in GATHERING_SPECIALIST_IDS or h.get("is_gatherer")) else 1,
        -int(h.get("level", 1) or 1),
        -int(h.get("star", 1) or 1),
        int(h.get("hero_id", 0) or 0),
    ))

    primaries = unlocked_roster[:max(0, target_queues)]
    locked_primary_ids = {p["hero_id"] for p in primaries}

    # Secondaries: leftovers with 1 <= level <= 10, weakest first
    # (any category - they only add load, the primary leads).
    secondary_pool = [
        h for h in unlocked_roster
        if h["hero_id"] not in locked_primary_ids
        and 1 <= int(h.get("level", 1) or 1) <= 10
    ]
    secondary_pool.sort(key=lambda h: (
        int(h.get("level", 1) or 1),
        int(h.get("star", 1) or 1),
        int(h.get("hero_id", 0) or 0),
    ))

    allocations: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]] = []
    for p in primaries:
        secondary = None
        if secondary_pool:
            secondary = secondary_pool.pop(0)
        allocations.append((p, secondary))

    return allocations


def resolve_manual_pair(gather_config: dict, res_type: str, pair_idx: int,
                        roster: List[Dict[str, Any]],
                        busy: Optional[Set[int]] = None,
                        failed: Optional[Set[int]] = None
                        ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    """Manual commander pair for one march (dashboard slots).

    Returns (primary, secondary_or_None, note). The pair is honored ONLY when
    the heroes are owned (present in the live wire roster) and free; otherwise
    (None, None, reason) so the caller falls back to auto selection.
    """
    busy = busy or set()
    failed = failed or set()
    cfg = gather_config if isinstance(gather_config, dict) else {}
    if not cfg.get("manual_commanders_enabled", cfg.get("manualCommanders", False)):
        return None, None, "manual_disabled"
    pairs = cfg.get("custom_pairs", cfg.get("commanderPairs", {})) or {}
    lst = pairs.get(str(res_type).lower()) if isinstance(pairs, dict) else None
    if not isinstance(lst, list) or pair_idx < 0 or pair_idx >= len(lst):
        return None, None, "no_manual_pair"
    entry = lst[pair_idx] if isinstance(lst[pair_idx], dict) else {}
    try:
        want_pri = int(entry.get("primary") or 0)
    except (TypeError, ValueError):
        want_pri = 0
    try:
        want_sec = int(entry.get("secondary") or 0)
    except (TypeError, ValueError):
        want_sec = 0
    if not (1 <= want_pri <= 5000):
        return None, None, "empty_primary"
    by_id = {h.get("hero_id"): h for h in roster or [] if h.get("hero_id")}
    pri = by_id.get(want_pri)
    if pri is None:
        return None, None, f"primary_{want_pri}_not_owned"
    if want_pri in busy or want_pri in failed:
        return None, None, f"primary_{want_pri}_busy"
    sec = None
    if 1 <= want_sec <= 5000 and want_sec != want_pri:
        sec = by_id.get(want_sec)
        if sec is None or want_sec in busy or want_sec in failed:
            sec = None
    return dict(pri), (dict(sec) if sec else None), "manual_ok"


def get_role_march_capacity(role_id: int) -> int:
    rid = str(role_id)
    # Live-derived capacity only: City Hall level & power from DB/fleet.
    # No per-character hardcoded table.
    try:
        from app.database import get_db_connection
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT city_hall_level, power FROM character_inventories WHERE role_id = ? ORDER BY updated_at DESC LIMIT 1", (rid,))
        r = cur.fetchone()
        if not r:
            cur.execute("SELECT city_level, power FROM characters WHERE role_id = ? LIMIT 1", (rid,))
            r = cur.fetchone()
        if r:
            ch_lvl = int(r[0] or 1)
            power = int(r[1] or 0)
            base_ch_cap = max(35000, 10000 + (ch_lvl * 3000))
            if power > 0:
                return max(base_ch_cap, min(156200, int(power / 100)))
            return base_ch_cap
    except Exception:
        pass
    try:
        from fleet_manager import load_fleet
        fleet = load_fleet()
        for c in fleet:
            if str(c.get("role_id")) == rid:
                power = c.get("power", 0) or 0
                if power > 0:
                    return max(45000, min(156200, int(power / 100)))
    except Exception:
        pass
    return DEFAULT_MARCH_CAPACITY

COMMANDER_NAMES = {
    # Proven by troops-panel names matched 1:1 with official 1012 packets
    # (identical troop counts: Matilda 44,394; Sarka 11,570; Ishida 14,798):
    #   Sarka=38, Matilda=572, Ishida=32. Plus detail+367 triangulation:
    #   Joan=15, Seondeok=102, Tamar=134, Centurion=24, Gaius=34,
    #   Constance=33 (medium: legacy agreement + level progression),
    #   Belisarius=61 (attacker).
    15: "Joan of Arc",
    102: "Seondeok",
    134: "Queen Tamar of Georgia",
    24: "Centurion",
    32: "Ishida Mitsunari",
    572: "Matilda of Flanders",
    38: "Sarka",
    34: "Gaius Marius",
    33: "Constance",
    61: "Belisarius",  # proven attacker (NOT a gatherer)
    3: "Sun Tzu",
    2: "Cao Cao",
    1: "City Keeper",
    6: "Lohar",
    8: "Scipio Africanus",
    13: "Kusunoki Masashige",
    11: "Baibars",
    10: "Commander #10",  # NOT Belisarius (Belisarius proven = 61)
    7: "Eulji Mundeok",  # legacy: Eulji is likely 7 or 24 (L38 pair, unconfirmed)
    5: "Pelagius",  # legacy labels below are unverified wire folklore
    12: "Osman I",
    9: "Hermann",
    35: "Tomoe Gozen",
    36: "Lancelot",
    23: "Markswoman",
}

STANDARD_NODE_CAPACITIES = {
    1: {1: 105000, 2: 315000, 3: 472500, 4: 675000, 5: 1000000, 6: 1350000},  # Food
    2: {1: 105000, 2: 315000, 3: 472500, 4: 675000, 5: 1000000, 6: 1350000},  # Wood
    3: {1: 78750,  2: 236250, 3: 354375, 4: 506250, 5: 750000,  6: 1012500},  # Stone
    4: {1: 52500,  2: 105000, 3: 157500, 4: 225000, 5: 500000,  6: 450000},   # Gold
    5: {1: 10,     2: 20,     3: 30,     4: 40,     5: 50,      6: 60},       # Gem
}

def unpack_double_field(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        try:
            return float(struct.unpack('<d', struct.pack('<Q', int(val)))[0])
        except Exception:
            return float(val)
    return 0.0

DEFAULT_MARCH_CAPACITY = 85000
GATHER_LOAD_BONUS = 0.15  # Conservative gathering load boost so bot never overestimates troop capacity

# Real in-game unit loads for T1 through T5 across all Rise of Kingdoms accounts
NATIVE_BASE_UNIT_LOAD = {
    # T1
    4: 20.0,  # T1 Siege
    1: 10.0,  # T1 Infantry
    3: 9.0,   # T1 Archer
    2: 8.0,   # T1 Cavalry

    # T2
    8: 22.0,  # T2 Siege
    5: 11.0,  # T2 Infantry
    7: 10.0,  # T2 Archer
    6: 9.0,   # T2 Cavalry

    # T3
    12: 24.0, # T3 Siege
    9: 12.0,  # T3 Infantry
    11: 11.0, # T3 Archer
    10: 10.0, # T3 Cavalry

    # T4
    16: 26.0, # T4 Siege
    13: 13.0, # T4 Infantry
    15: 12.0, # T4 Archer
    14: 11.0, # T4 Cavalry

    # T5
    20: 28.0, # T5 Siege
    17: 14.0, # T5 Infantry
    19: 13.0, # T5 Archer
    18: 12.0, # T5 Cavalry
}

def get_unit_load(unit_type: int, load_bonus: float = GATHER_LOAD_BONUS) -> float:
    base = NATIVE_BASE_UNIT_LOAD.get(unit_type, 8.0)
    return round(base * (1.0 + load_bonus), 2)

NATIVE_UNIT_LOAD = {ut: get_unit_load(ut, GATHER_LOAD_BONUS) for ut in NATIVE_BASE_UNIT_LOAD}

STATUS_FILE = os.path.join(PROJECT_ROOT, "gather_status.json")

def save_gather_status(active_marches_dict: dict, total_city_troops: int, deployed_marches_details: list = None):
    marches_data = []
    if deployed_marches_details:
        for d in deployed_marches_details:
            cid = d.get("cmd_id")
            scid = d.get("sec_cmd_id", 0)
            cname = d.get("cmd_name")
            if not cname:
                p_name = COMMANDER_NAMES.get(cid, f"Commander #{cid}")
                s_name = COMMANDER_NAMES.get(scid, f"Commander #{scid}") if scid else ""
                cname = f"{p_name} / {s_name}" if s_name else p_name

            marches_data.append({
                "cmd_id": cid,
                "sec_cmd_id": scid,
                "cmd_name": cname,
                "type": d.get("type", "food"),
                "target": d.get("target", "Resource Tile"),
                "troops": d.get("troops", 0),
                "load": d.get("load", 0),
                "node_reserves": d.get("node_reserves", 0),
                "status": "Gathering"
            })
    for mid, cid in active_marches_dict.items():
        if not any(m["cmd_id"] == cid for m in marches_data):
            cname = COMMANDER_NAMES.get(cid, f"Commander #{cid}")
            marches_data.append({
                "cmd_id": cid,
                "sec_cmd_id": 0,
                "cmd_name": cname,
                "type": "resource",
                "target": f"Tile #{mid}",
                "status": "Gathering"
            })

    payload = {
        "active_marches_count": len(marches_data),
        "total_city_troops": total_city_troops,
        "marches": marches_data,
        "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def encode_point(x: float, y: float) -> bytes:
    # Tag 1 (0x0d) is fixed32 X, Tag 2 (0x15) is fixed32 Y
    return b"\x0d" + struct.pack("<f", float(x)) + b"" + struct.pack("<f", float(y))

def build_map_request(center_pos: tuple) -> bytes:
    f1 = encode_point(center_pos[0], center_pos[1])
    payload = ProtobufCodec.encode_message({1: f1, 2: 0, 5: 1})
    return ProtobufCodec.encode_message({1: 1004, 2: payload})

def generate_radial_viewports(cx: float, cy: float, max_km: int = 100):
    """
    Generates concentric radial viewports covering 360 degrees from origin (0km) to max_km.
    Wire scaling: 1 km = 6.0 wire units.
    """
    import math
    pts = [(cx, cy)]  # Ground zero: direct city perimeter
    km_rings = [2, 5, 10, 20, 35, 50, 75, 100]
    if max_km > 100:
        km_rings.extend([125, 150, 175, 200])
    for r_km in km_rings:
        r_wire = r_km * 6.0
        steps = 8 if r_km <= 20 else 12
        for i in range(steps):
            angle = (2 * math.pi / steps) * i
            px = round(cx + r_wire * math.cos(angle), 2)
            py = round(cy + r_wire * math.sin(angle), 2)
            pts.append((px, py))
    return pts


def build_inspect(node_id: int, node_pos: tuple, city_pos: tuple, alliance_id: int = 8719112) -> bytes:
    # F3 = City pos, F4 = Node pos, Tag 1 = LIVE inspect session key from
    # Opcode 1035 field 12 (param name kept as alliance_id for callers),
    # Tag 2 = node_id, Tag 5 = 0
    f3_city = encode_point(city_pos[0], city_pos[1])
    f4_node = encode_point(node_pos[0], node_pos[1])
    body = (
        ProtobufCodec.encode_field_bytes(3, f3_city)
        + ProtobufCodec.encode_field_varint(5, 0)
        + ProtobufCodec.encode_field_varint(2, node_id)
        + ProtobufCodec.encode_field_bytes(4, f4_node)
        + ProtobufCodec.encode_field_varint(1, alliance_id)
    )
    return ProtobufCodec.encode_message({1: 1050, 2: body})

def encode_varint(v: int) -> bytes:
    res = bytearray()
    while v > 0x7F:
        res.append((v & 0x7F) | 0x80)
        v >>= 7
    res.append(v & 0x7F)
    return bytes(res)

def build_gather_dispatch(
    node_id: int,
    army_list: list,
    primary_hero_id: int = 15,
    secondary_hero_id: int = 0,
    march_index: int = 1
) -> bytes:
    """
    Builds Opcode 1012 payload for gathering march dispatch:
    - Field 4: node_id (varint)
    - Field 3: zero point coordinates b'\\x1a\\x0a\\x15\\x00\\x00\\x00\\x00\\x0d\\x00\\x00\\x00\\x00'
    - Field 2: troops array {1: unit_type, 2: count}
    - Field 14: 1
    - Field 1: Slot 1 primary_hero_id (pos = 1)
               Slot 2 secondary_hero_id if > 0 (pos = 2)
    - Field 7: 0
    - Field 6: 0 (Gathering Mode flag, wire hex: 3000)
    - Field 11: 0
    - Field 18: 0
    - Field 5: b"dispatch_troop_1" (or dispatch_troop_{march_index})
    """
    f4 = ProtobufCodec.encode_field_varint(4, int(node_id))
    f3 = b'\x1a\x0a\x15\x00\x00\x00\x00\x0d\x00\x00\x00\x00'
    f2_payload = bytearray()
    for ut, cnt in army_list:
        if cnt <= 0: continue
        it = ProtobufCodec.encode_field_varint(2, int(cnt)) + ProtobufCodec.encode_field_varint(1, int(ut))
        f2_payload.extend(ProtobufCodec.encode_field_bytes(2, it))
    f14 = ProtobufCodec.encode_field_varint(14, 1)

    p_var = encode_varint(int(primary_hero_id))
    # Official wire shape (ground truth C->S 1012): hero slot =
    # {1: hero_id, 3: 0, 2: position} e.g. 0a06 080f 1800 1001.
    # The f3:0 element was missing and MUST be present.
    hero_payload = b'\x0a\x06\x08' + p_var + b'\x18\x00\x10\x01' if len(p_var) == 1 else (
        b'\x0a' + encode_varint(len(p_var) + 5) + b'\x08' + p_var + b'\x18\x00\x10\x01'
    )
    if secondary_hero_id and int(secondary_hero_id) > 0:
        s_var = encode_varint(int(secondary_hero_id))
        hero_payload += b'\x0a\x06\x08' + s_var + b'\x18\x00\x10\x02' if len(s_var) == 1 else (
            b'\x0a' + encode_varint(len(s_var) + 5) + b'\x08' + s_var + b'\x18\x00\x10\x02'
        )

    f7 = ProtobufCodec.encode_field_varint(7, 0)
    # Field 6 = 0: Gathering Mode (Wire hex: 0x30 0x00 -> "3000")
    f6 = b'\x30\x00'
    f11 = ProtobufCodec.encode_field_varint(11, 0)
    f18 = ProtobufCodec.encode_field_varint(18, 0)
    f5 = ProtobufCodec.encode_field_bytes(5, f"dispatch_troop_{march_index}".encode())
    body = f4 + f3 + bytes(f2_payload) + f14 + hero_payload + f7 + f6 + f11 + f18 + f5
    return ProtobufCodec.encode_message({1: 1012, 2: body})

def extract_city_and_heroes_from_op1002(p2_bytes: bytes) -> Tuple[Optional[Tuple[float, float]], List[int]]:
    """
    Extracts real city coordinates (wire units) and unlocked commanders from Opcode 1002 payload.
    Wire coordinates: 1 km = 6.0 wire units. (Display = wire / 6.0)
    """
    coords = None
    heroes = []
    if not p2_bytes:
        return None, []
    try:
        sub = ProtobufCodec.decode_message(p2_bytes)
        
        # 1. Coords from sub_f1 Tag 3
        f1 = sub.get(1)
        if isinstance(f1, bytes):
            sub_f1 = ProtobufCodec.decode_message(f1)
            c_bytes = sub_f1.get(3)
            if isinstance(c_bytes, bytes):
                m = re.search(b'\r(.{4})\x15(.{4})', c_bytes)
                if m:
                    fx = struct.unpack('<f', m.group(1))[0]
                    fy = struct.unpack('<f', m.group(2))[0]
                    if 10.0 <= fx <= 7200.0 and 10.0 <= fy <= 7200.0:
                        coords = (round(fx, 2), round(fy, 2))

        # 1b. Fallback: regex search across p2_bytes
        if not coords:
            m = re.search(b'\r(.{4})\x15(.{4})', p2_bytes)
            if m:
                fx = struct.unpack('<f', m.group(1))[0]
                fy = struct.unpack('<f', m.group(2))[0]
                if 10.0 <= fx <= 7200.0 and 10.0 <= fy <= 7200.0:
                    coords = (round(fx, 2), round(fy, 2))

        # 2. Heroes from Tag 12 subfield 5 or Tag 9 subfield 4
        for tag_id in (12, 9):
            val = sub.get(tag_id)
            if isinstance(val, bytes):
                sub_val = ProtobufCodec.decode_message(val)
                h_list = sub_val.get(5) or sub_val.get(4) or []
                if not isinstance(h_list, list): h_list = [h_list]
                for hb in h_list:
                    if isinstance(hb, bytes):
                        hm = ProtobufCodec.decode_message(hb)
                        hid = hm.get(1)
                        if isinstance(hid, int) and hid > 0 and hid not in heroes:
                            heroes.append(hid)
    except Exception:
        pass

    return coords, heroes

def resolve_city_coordinates(active_role_id, opcode_1002_bytes: bytes = None):
    if opcode_1002_bytes:
        coords, _ = extract_city_and_heroes_from_op1002(opcode_1002_bytes)
        if coords:
            return coords
    try:
        from app.models import CharacterDAO, CharacterSettingsDAO
        db_char = CharacterDAO.get_by_role_id(str(active_role_id))
        if db_char and db_char.get("id"):
            c_set = CharacterSettingsDAO.get_by_character_id(db_char["id"]) or {}
            g_cfg = c_set.get("gather", {}) or {}
            cx = float(g_cfg.get("city_x", 0))
            cy = float(g_cfg.get("city_y", 0))
            if cx > 0 and cy > 0:
                if cx < 2000.0:
                    cx *= 6.0
                    cy *= 6.0
                return (round(cx, 2), round(cy, 2))
        if db_char and db_char.get("city_x") and db_char.get("city_y"):
            cx = float(db_char["city_x"])
            cy = float(db_char["city_y"])
            if cx < 2000.0:
                cx *= 6.0
                cy *= 6.0
            return (round(cx, 2), round(cy, 2))
    except Exception:
        pass
    return None

async def execute_smart_gather(
    march_targets: List[str] = None,
    target_level: int = 0,
    level_mode: str = "any",
    role_id: int = None,
    gate_host: str = None,
    gate_port: int = None,
    city_pos: Tuple[float, float] = None,
    kingdom_id: int = None,
    only_finishable: bool = False,
    skip_partially: bool = True,
    avoid_territory: bool = True,
    alliance_tag: str = "",
    alliance_id: int = 0,
    log_callback = None,
    max_node_level: Any = None,
    **kwargs
):
    import builtins
    _native_print = builtins.print
    def print(*args, **kwargs):
        _native_print(*args, **kwargs)
        if log_callback:
            try:
                msg = " ".join(str(a) for a in args)
                log_callback(msg)
            except Exception:
                pass

    # Resolve dashboard filter toggles
    skip_partially = kwargs.get("skip_partially_gathered_nodes",
                     kwargs.get("skip_partially_depleted",
                     kwargs.get("skipPartial", skip_partially)))
    skip_partially = bool(skip_partially)

    avoid_territory = kwargs.get("avoid_other_alliance_territories",
                      kwargs.get("avoid_other_alliance_territory",
                      kwargs.get("avoidTerritory", avoid_territory)))
    avoid_territory = bool(avoid_territory)

    discovered_alliance_id = int(alliance_id or 0)
    discovered_alliance_tag = str(alliance_tag or "").strip()
    discovered_alliance_name = ""

    if not march_targets:
        march_targets = ["food", "wood", "stone"]

    active_role_id = role_id or ROLE_ID
    host = gate_host or GATE_IP
    port = gate_port or GATE_PORT

    # Resolve gathering configuration
    gather_config = kwargs.get("gather_config") or kwargs.get("gather")
    if not isinstance(gather_config, dict) or not gather_config:
        try:
            from app.models import CharacterDAO, CharacterSettingsDAO
            _char_rec = CharacterDAO.get_by_role_id(str(active_role_id))
            if _char_rec and _char_rec.get("id"):
                gather_config = (CharacterSettingsDAO.get_by_character_id(_char_rec["id"]) or {}).get("gather") or {}
        except Exception:
            gather_config = {}
    if not isinstance(gather_config, dict):
        gather_config = {}

    if "auto_balance_lowest_rss" in kwargs:
        gather_config["auto_balance_lowest_rss"] = bool(kwargs["auto_balance_lowest_rss"])

    # Resolve Max Node Level Cap (Strict Ceiling)
    if max_node_level is not None:
        max_allowed_level = parse_max_node_level(max_node_level)
    elif any(k in kwargs for k in ("max_node_level", "max_level", "gather_max_level")):
        max_allowed_level = parse_max_node_level(kwargs)
    else:
        max_allowed_level = parse_max_node_level(gather_config)
    gather_config["max_node_level"] = max_allowed_level
    print(f"[LEVEL_FILTER] Max cap enforced: Level {max_allowed_level}")

    # Initialize live city resources tracking (pre-populated from DB cache)
    live_city_rss = {"food": 0, "wood": 0, "stone": 0, "gold": 0}
    try:
        from app.database import get_db_connection as _gdb_rss
        _con_rss = _gdb_rss()
        _cur_rss = _con_rss.cursor()
        _cur_rss.execute("SELECT food, wood, stone, gold FROM character_inventories WHERE role_id = ? ORDER BY updated_at DESC LIMIT 1", (str(active_role_id),))
        _r_rss = _cur_rss.fetchone()
        if not _r_rss:
            _cur_rss.execute("SELECT food, wood, stone, gold FROM characters WHERE role_id = ? LIMIT 1", (str(active_role_id),))
            _r_rss = _cur_rss.fetchone()
        if _r_rss:
            live_city_rss["food"] = int(_r_rss[0] or 0)
            live_city_rss["wood"] = int(_r_rss[1] or 0)
            live_city_rss["stone"] = int(_r_rss[2] or 0)
            live_city_rss["gold"] = int(_r_rss[3] or 0)
    except Exception:
        pass

    from fleet_manager import load_fleet, resolve_login_bytes
    fleet = load_fleet()
    target_char = next((c for c in fleet if str(c.get("role_id")) == str(active_role_id)), None)
    if target_char is None:
        # Fallback to DB for farm accounts (3057) not in fleet file (3150)
        try:
            from app.models import CharacterDAO
            db_c = CharacterDAO.get_by_role_id(str(active_role_id))
            if db_c:
                target_char = db_c
                # Enrich with account credentials for cloud switch
                try:
                    from app.models import AccountDAO
                    from app.database import get_db_connection
                    con = get_db_connection()
                    acc_row = con.execute("SELECT * FROM accounts WHERE id = ?", (db_c.get("account_id"),)).fetchone()
                    if acc_row:
                        acc = dict(acc_row)
                        target_char = {**target_char, **{"app_uid": acc.get("app_uid"), "app_token": acc.get("app_token"), "udid": acc.get("udid"), "account_id": acc.get("id")}}
                except Exception:
                    pass
        except Exception:
            pass
    if target_char is None:
        target_char = fleet[0] if fleet else {}

    # Ensure active on Lilith Cloud
    print(f"[1/4] Ensuring active cloud character is {target_char.get('name', active_role_id)}...")
    ensure_character_active(target_char)

    login_bytes = kwargs.get("login_bytes")
    if not login_bytes:
        login_bytes = resolve_login_bytes(target_char or active_role_id)
    # Unified telemetry identifiers (fix NameError when city_pos provided)
    try:
        char_name = str(target_char.get("name") or target_char.get("character_name") or f"Role_{active_role_id}")
    except Exception:
        char_name = f"Role_{active_role_id}"
    tenant_id = str(kwargs.get("tenant_id") or kwargs.get("user_id") or kwargs.get("tenant") or target_char.get("user_id") or "")

    # Auto-discover city position from gateway if not provided
    if city_pos:
        active_city_pos = city_pos
        print(f"   [CITY] Using provided city position: {active_city_pos}")
    elif target_char.get("city_pos"):
        active_city_pos = tuple(target_char["city_pos"])
        print(f"   [CITY] Using fleet registry city position: {active_city_pos}")
    else:
        active_city_pos = None
        print(f"   [CITY] City position not configured — will auto-discover from map nodes")

    if not discovered_alliance_id:
        discovered_alliance_id = int(target_char.get("alliance_id", 0) or 0)
    if not discovered_alliance_tag:
        discovered_alliance_tag = str(target_char.get("alliance_tag", "") or "").strip()

    active_alliance_id = discovered_alliance_id
    active_alliance_tag = discovered_alliance_tag
    active_kid = kingdom_id or int(target_char.get("kingdom_id", 11543))
    lvl_desc = f"Max Cap: Level {max_allowed_level} (Descending Fallback)" if max_allowed_level < 6 else "No Cap (Level 1-6 Descending Fallback)"
    tag_str = f"[{active_alliance_tag}] " if active_alliance_tag else ""
    print("=" * 65)
    print("  PURE HEADLESS MULTI-MARCH DYNAMIC GATHER ENGINE")
    print(f"  Character: {target_char.get('name', active_role_id)} (Role {active_role_id})")
    print(f"  City Pos: {active_city_pos} | Kingdom: {active_kid} | Alliance: {tag_str}#{active_alliance_id}")
    print(f"  Filters: Avoid Rival Territory={avoid_territory} | Skip Partial (>=70%)={skip_partially}")
    print(f"  Targets: {', '.join(t.upper() for t in march_targets)} | Mode: {lvl_desc}")
    print("=" * 65)

    print(f"\n[2/4] Connecting to Gate {host}:{port}...")
    reader, writer = await asyncio.open_connection(host, port)

    # 1. Nonce Handshake
    hdr = await reader.readexactly(2)
    g_payload = await reader.readexactly((hdr[0] << 8) | hdr[1])
    g_fields = ProtobufCodec.decode_message(g_payload)
    sub = ProtobufCodec.decode_message(g_fields.get(2, b""))
    seed_tx, seed_rx = derive_seed(sub.get(1, 0), sub.get(2, 0))
    print(f"[SUCCESS] Handshake complete: TX=0x{seed_tx:08x}, RX=0x{seed_rx:08x}")

    crypto_tx = RokCrypto(seed_tx)
    crypto_rx = RokCrypto(seed_rx)

    # 2. Authenticate
    print("[3/4] Authenticating session and syncing real military inventory...")
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(login_bytes)))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 6404, 2: ProtobufCodec.encode_message({1: active_kid})}))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: b""}))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: b""}))))
    await writer.drain()
    await asyncio.sleep(0.5)
    # Request world map & player state (Opcode 1001 triggers Opcode 1002 response with city coords & heroes)
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b""}))))
    # Authoritative unlocked-commander catalogue (Opcode 366 -> 367 with id/level/star/skills)
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 366, 2: b""}))))
    await writer.drain()

    # PHASE A: Handshake State & Auto-Discover City Coordinates from Opcode 1002
    discovered_city_coords = None
    discovered_city_hall_lvl = None
    discovered_heroes = []
    live_hero_roster: List[Dict[str, Any]] = []
    wall_garrison_ids: Set[int] = set()
    troops_in_city = {}
    raw_units_125 = {}
    active_marches = {}
    busy_commanders = set()
    discovered_nodes = []
    seen_node_ids = set()
    synced_full_military = False
    # Live map-inspect session key (Opcode 1035 field 12). MUST be echoed as
    # field 1 of every 1050 inspect - never the alliance ID (see helper).
    live_inspect_key: Optional[int] = None

    # Load account's saved hero metadata from DB / fleet to guarantee real levels/stars
    saved_meta_heroes = []
    try:
        from app.models import CharacterDAO, CharacterSettingsDAO
        db_char = CharacterDAO.get_by_role_id(str(active_role_id))
        if db_char and db_char.get("id"):
            c_set = CharacterSettingsDAO.get_by_character_id(db_char["id"]) or {}
            saved_meta_heroes = c_set.get("commanders_meta") or []
    except Exception:
        saved_meta_heroes = []

    if saved_meta_heroes:
        live_hero_roster = merge_rosters(live_hero_roster, saved_meta_heroes)

    # QUIET ROSTER SESSION: dedicated short-lived connection that ONLY asks
    # for the commander catalogue (1001 -> 366 -> 367) with zero burst
    # traffic. Proven pattern: a quiet standalone session gets 367 instantly
    # (9 heroes incl. gatherers), while the main session's 366 is dropped
    # amid the login/viewport flood. Result is cached via persist (source
    # gather_quiet_367 overwrites stale data) for future runs.
    _quiet_wanted = len(live_hero_roster) < 3
    if not _quiet_wanted:
        print(f"   [HERO_DISCOVERY] Cached roster ({len(live_hero_roster)} heroes) - quiet session skipped.")
    else:
        try:
            _qr, _qw = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=10.0)
            try:
                _hh = await asyncio.wait_for(_qr.readexactly(2), timeout=6.0)
                _gp = await _qr.readexactly((_hh[0] << 8) | _hh[1])
                _sg = ProtobufCodec.decode_message(ProtobufCodec.decode_message(_gp).get(2, b""))
                _stx, _srx = derive_seed(_sg.get(1, 0), _sg.get(2, 0))
                _qtx, _qrx = RokCrypto(_stx), RokCrypto(_srx)
                _qw.write(FrameParser.build_frame(_qtx.encrypt(login_bytes)))
                for _qo, _qp in ((104, b""), (107, b""),
                        (6404, ProtobufCodec.encode_message({1: active_kid})),
                        (203, b""), (110, b"")):
                    _qw.write(FrameParser.build_frame(_qtx.encrypt(ProtobufCodec.encode_message({1: _qo, 2: _qp}))))
                await _qw.drain()
                await asyncio.sleep(0.5)
                _qw.write(FrameParser.build_frame(_qtx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b""}))))
                _qw.write(FrameParser.build_frame(_qtx.encrypt(ProtobufCodec.encode_message({1: 366, 2: b""}))))
                await _qw.drain()
                print("   [HERO_DISCOVERY] Quiet session: handshake+login+366 sent, listening...")
                _qend = asyncio.get_event_loop().time() + 9.0
                _qops = {}
                while asyncio.get_event_loop().time() < _qend:
                    try:
                        _fh = await asyncio.wait_for(_qr.readexactly(2), timeout=1.0)
                        _pl = (_fh[0] << 8) | _fh[1]
                        _rp = await asyncio.wait_for(_qr.readexactly(_pl), timeout=1.0)
                        _dc = _qrx.decrypt(_rp)
                        _, _qsubs = decode_stream_chunks(_dc)
                        for _mm in _qsubs:
                            if not isinstance(_mm, dict):
                                continue
                            if isinstance(_mm.get(1), int):
                                _qops[_mm.get(1)] = _qops.get(_mm.get(1), 0) + 1
                            if _mm.get(1) != 367:
                                continue
                            _pp = _mm.get(2)
                            if isinstance(_pp, bytes):
                                _qh = parse_heroes_from_367(_pp)
                                if _qh:
                                    live_hero_roster = merge_rosters(live_hero_roster, _qh)
                                    for _hhh in _qh:
                                        if _hhh["hero_id"] not in discovered_heroes:
                                            discovered_heroes.append(_hhh["hero_id"])
                                    print(f"   [HERO_DISCOVERY] Quiet session 367: {len(_qh)} heroes.")
                                    try:
                                        persist_roster_to_db(active_role_id, _qh, set(), source="gather_quiet_367")
                                    except Exception:
                                        pass
                                    _qend = 0
                                    break
                        if _qend == 0:
                            break
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        break
                print(f"   [HERO_DISCOVERY] Quiet session ops: {sorted(_qops)[:40]}")
            finally:
                try:
                    _qw.close()
                    await _qw.wait_closed()
                except Exception:
                    pass
        except Exception as _qe:
            print(f"   [HERO_DISCOVERY] quiet roster session note: {_qe}")

    deadline_init = asyncio.get_event_loop().time() + 5.0
    deadline_hard = deadline_init + 4.0
    seen_367 = False
    resent_366 = False
    while asyncio.get_event_loop().time() < deadline_init or (not seen_367 and asyncio.get_event_loop().time() < deadline_hard):
        if not seen_367 and not resent_366 and asyncio.get_event_loop().time() >= deadline_init:
            resent_366 = True
            try:
                writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 366, 2: b""}))))
                await writer.drain()
                print("   [HERO_DISCOVERY] Opcode 367 not yet seen - catalogue re-requested.")
            except Exception:
                pass
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.4)
            rl = (rh[0] << 8) | rh[1]
            raw_pkt = await asyncio.wait_for(reader.readexactly(rl), timeout=0.4)
            dec = crypto_rx.decrypt(raw_pkt)
            # decode_stream_chunks() unwraps nested envelopes, so 367 is
            # found directly (exact match keeps priority over the fuzzy
            # 1201 byte-sniff below).
            data, subs = decode_stream_chunks(dec)

            for m in subs:
                if not isinstance(m, dict):
                    continue
                op = m.get(1)
                if op == 367:
                    seen_367 = True
                    p367 = m.get(2)
                    if isinstance(p367, bytes):
                        parsed_367 = parse_heroes_from_367(p367)
                        if parsed_367:
                            live_hero_roster = merge_rosters(live_hero_roster, parsed_367)
                            for h in parsed_367:
                                if h["hero_id"] not in discovered_heroes:
                                    discovered_heroes.append(h["hero_id"])
                            print(f"   [HERO_DISCOVERY] Opcode 367: Parsed {len(parsed_367)} unlocked heroes (authoritative).")

                # Opcode 1201: Full unlocked commander catalogue
                elif op == 1201 or (isinstance(data, bytes) and b"\x08\xb1\t" in data):
                    p1201 = m.get(2) if op == 1201 else None
                    if not p1201 and isinstance(data, bytes) and b"\x08\xb1\t" in data:
                        idx_1201 = data.find(b"\x08\xb1\t")
                        sub_1201 = ProtobufCodec.decode_message(data[idx_1201:])
                        p1201 = sub_1201.get(2)
                    if isinstance(p1201, bytes):
                        parsed_1201 = parse_heroes_from_1201(p1201)
                        if parsed_1201:
                            live_hero_roster = merge_rosters(live_hero_roster, parsed_1201)
                            for h in parsed_1201:
                                if h["hero_id"] not in discovered_heroes:
                                    discovered_heroes.append(h["hero_id"])
                            print(f"   [HERO_DISCOVERY] Opcode 1201: Parsed {len(parsed_1201)} unlocked heroes.")

                # Opcode 367 handled first above (exact match priority).

                # Opcode 1157: Supplemental roster
                elif op == 1157:
                    p1157 = m.get(2)
                    if isinstance(p1157, bytes):
                        parsed_1157 = parse_roster_from_1157(p1157)
                        if parsed_1157:
                            live_hero_roster = merge_rosters(live_hero_roster, parsed_1157)
                            for h in parsed_1157:
                                if h["hero_id"] not in discovered_heroes:
                                    discovered_heroes.append(h["hero_id"])

                # Real Governor State & City Coords & Commanders from Opcode 1002
                elif op == 1002 or (isinstance(data, bytes) and b"\x08\xea\x07" in data):
                    p2 = m.get(2) if op == 1002 else None
                    if not p2 and isinstance(data, bytes) and b"\x08\xea\x07" in data:
                        idx_1002 = data.find(b"\x08\xea\x07")
                        sub_msg = ProtobufCodec.decode_message(data[idx_1002:])
                        p2 = sub_msg.get(2)
                    if isinstance(p2, bytes):
                        c_tuple, h_list = extract_city_and_heroes_from_op1002(p2)
                        if c_tuple and not discovered_city_coords:
                            discovered_city_coords = c_tuple
                        if h_list:
                            for h in h_list:
                                if h not in discovered_heroes:
                                    discovered_heroes.append(h)
                        parsed_1002 = parse_heroes_from_1002(p2)
                        if parsed_1002:
                            live_hero_roster = merge_rosters(live_hero_roster, parsed_1002)
                        gar_1002 = parse_wall_garrison_from_1002(p2)
                        if gar_1002:
                            wall_garrison_ids.update(gar_1002)
                            print(f"   [WALL_GARRISON] Detected Wall Garrison heroes: {sorted(wall_garrison_ids)}")
                        sub1002 = ProtobufCodec.decode_message(p2)
                        try:
                            from app.services.city_state_parser import parse_city_state_1002
                            from app.models import InventoryDAO
                            _snap = parse_city_state_1002(p2)
                            if _snap:
                                if _snap.get('city_hall_level'):
                                    discovered_city_hall_lvl = int(_snap['city_hall_level'])
                                for _k in ("food", "wood", "stone", "gold"):
                                    if _k in _snap and _snap[_k] is not None and int(_snap[_k]) > 0:
                                        live_city_rss[_k] = int(_snap[_k])
                                _bid = kwargs.get('bot_id') or kwargs.get('user_bot_id') or ''
                                _cname = kwargs.get('char_name') or _snap.get('name') or ''
                                InventoryDAO.upsert(
                                    bot_id=_bid,
                                    role_id=str(active_role_id),
                                    name=_cname,
                                    kingdom_id=int(_snap.get('kingdom_id') or active_kingdom_id or 0),
                                    city_hall_level=int(_snap.get('city_hall_level') or 0),
                                    power=int(_snap.get('power') or 0)
                                )
                                print(f"   [INVENTORY-1002] Profile parsed for {_cname}: CH={_snap.get('city_hall_level', 0)} Power={_snap.get('power', 0):,}")
                        except Exception as _inv_err:
                            print(f"   [WARN] inventory 1002 sync: {_inv_err}")

                        # Dynamic Automatic Alliance Discovery directly from wire stream
                        if not discovered_alliance_tag or not discovered_alliance_id or discovered_alliance_id == 8719112:
                            _d_id, _d_name, _d_tag = extract_alliance_from_message(sub1002)
                            if not _d_tag and not _d_id:
                                _d_id, _d_name, _d_tag = extract_alliance_from_message(m)
                            if _d_tag or _d_id:
                                if _d_id and (not discovered_alliance_id or discovered_alliance_id == 8719112):
                                    discovered_alliance_id = _d_id
                                    active_alliance_id = _d_id
                                if _d_tag and not discovered_alliance_tag:
                                    discovered_alliance_tag = _d_tag
                                    active_alliance_tag = _d_tag
                                if _d_name:
                                    discovered_alliance_name = _d_name
                                print(f"[ALLIANCE_DISCOVERY] Discovered Alliance: [{discovered_alliance_tag}] (ID: {discovered_alliance_id}) directly from server stream.")
                                try:
                                    from app.database import get_db_connection
                                    _db_con = get_db_connection()
                                    _db_con.execute(
                                        "UPDATE characters SET alliance_tag = ?, alliance_id = ? WHERE role_id = ?",
                                        (discovered_alliance_tag, discovered_alliance_id, str(active_role_id))
                                    )
                                    _db_con.commit()
                                except Exception:
                                    pass

                        tag19_raw = sub1002.get(19)
                        if isinstance(tag19_raw, bytes):
                            inner = ProtobufCodec.decode_message(tag19_raw)
                            for item_b in inner.get(1, []):
                                if isinstance(item_b, bytes):
                                    it = ProtobufCodec.decode_message(item_b)
                                    uid = it.get(1)
                                    cnt = it.get(3) or it.get(2) or 0
                                    if uid and cnt > 0:
                                        troops_in_city[uid] = cnt
                            if troops_in_city:
                                synced_full_military = True

                # Fallback garrison sync from Opcode 125
                elif op == 125 and not synced_full_military:
                    p = ProtobufCodec.decode_message(m.get(2, b"")) if isinstance(m.get(2), bytes) else m.get(2, {})
                    items = p.get(1, [])
                    if not isinstance(items, list): items = [items]
                    for it in items:
                        if isinstance(it, bytes):
                            sub_it = ProtobufCodec.decode_message(it)
                            u_key = sub_it.get(1)
                            sub2_raw = sub_it.get(2)
                            if isinstance(sub2_raw, bytes):
                                sub2 = ProtobufCodec.decode_message(sub2_raw)
                                ut = sub2.get(1, 0)
                                cnt = sub2.get(2, 0)
                                if ut > 0 and cnt > 0:
                                    raw_units_125[u_key] = (ut, cnt)

                # Keepalive / Acknowledge Opcode 8003 -> server sends Opcode 121 (liquid resources)
                elif op == 8003:
                    try:
                        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({
                            1: 9, 2: ProtobufCodec.encode_message({1: 1})
                        }))))
                        await writer.drain()
                    except Exception:
                        pass

                # Opcode 121: Real in-city liquid resources (Food, Wood, Stone, Gold, Gems)
                elif op == 121:
                    try:
                        from app.models import InventoryDAO
                        from app.services.city_state_parser import parse_resources_121
                        p121 = m.get(2) or data
                        _rss = parse_resources_121(p121)
                        if _rss:
                            for _k in ("food", "wood", "stone", "gold"):
                                if _k in _rss and _rss[_k] is not None:
                                    live_city_rss[_k] = int(_rss[_k])
                            _bid = kwargs.get('bot_id') or kwargs.get('user_bot_id') or ''
                            _cname = kwargs.get('char_name') or getattr(active_char, 'name', '') or ''
                            InventoryDAO.upsert(
                                bot_id=_bid,
                                role_id=str(active_role_id),
                                name=_cname,
                                food=_rss.get('food', 0),
                                wood=_rss.get('wood', 0),
                                stone=_rss.get('stone', 0),
                                gold=_rss.get('gold', 0),
                                gems=_rss.get('gems', 0)
                            )
                            print(f"   [INVENTORY-121] Live Liquid Resources for {_cname}: Food={_rss.get('food', 0):,} Wood={_rss.get('wood', 0):,} Stone={_rss.get('stone', 0):,} Gold={_rss.get('gold', 0):,} Gems={_rss.get('gems', 0):,}")
                    except Exception as _rss_err:
                        print(f"   [WARN] opcode 121 sync error: {_rss_err}")

                # Opcode 1035: live map-inspect session key (field 12).
                # The official client echoes this as field 1 of 1050.
                elif op == 1035:
                    try:
                        _p1035 = m.get(2)
                        if isinstance(_p1035, (bytes, bytearray)):
                            _key = extract_inspect_key_from_1035(bytes(_p1035))
                            if _key and _key != live_inspect_key:
                                live_inspect_key = _key
                                print(f"   [INSPECT_KEY] Live 1035 session key: {live_inspect_key}")
                    except Exception:
                        pass

                # Active marches (cookies may also ride other march-state
                # opcodes, so snoop the whole sub-message payload too)
                elif op in (1005, 1023):
                    p_march = ProtobufCodec.decode_message(m.get(2, b"")) if isinstance(m.get(2), bytes) else m.get(2, {})
                    f1 = p_march.get(1, b"") if isinstance(p_march, dict) else b""
                    _note_march_cookies(f1, active_role_id, busy_commanders, active_marches)
                    _note_march_cookies(m.get(2), active_role_id, busy_commanders, active_marches)
        except asyncio.TimeoutError:
            if discovered_city_coords and synced_full_military and seen_367:
                break
            continue
        except Exception:
            pass

    # Resolve active city position
    if discovered_city_coords:
        active_city_pos = discovered_city_coords
        disp_x = round(active_city_pos[0] / 6.0, 1)
        disp_y = round(active_city_pos[1] / 6.0, 1)
        print(f"   [CITY AUTO-DISCOVERED] Real City Pos from Game Server: Wire {active_city_pos} -> Display ({disp_x}, {disp_y})")
        # Persist to database so web UI and future queries have it
        try:
            from app.models import CharacterDAO, CharacterSettingsDAO
            db_c2 = CharacterDAO.get_by_role_id(str(active_role_id))
            if db_c2 and db_c2.get("id"):
                c_settings = CharacterSettingsDAO.get_by_character_id(db_c2["id"]) or {}
                g_cfg = c_settings.get("gather", {}) or {}
                if abs(float(g_cfg.get("city_x", 0)) - disp_x) > 0.1 or abs(float(g_cfg.get("city_y", 0)) - disp_y) > 0.1:
                    g_cfg["city_x"] = disp_x
                    g_cfg["city_y"] = disp_y
                    CharacterSettingsDAO.upsert(db_c2["id"], gather=g_cfg)
                    print(f"   [CITY PERSIST] Saved city coordinates ({disp_x}, {disp_y}) to database.")
                try:
                    from app.database import get_db_connection as _gdb3
                    _con3 = _gdb3()
                    cols = [r[1] for r in _con3.execute("PRAGMA table_info(characters)").fetchall()]
                    if "city_x" in cols and "city_y" in cols:
                        _con3.execute("UPDATE characters SET city_x=?, city_y=? WHERE role_id=?", (disp_x, disp_y, str(active_role_id)))
                        _con3.commit()
                except Exception:
                    pass
        except Exception as e_save:
            print(f"   [CITY PERSIST] notice: {e_save}")
    elif active_city_pos is None:
        active_city_pos = resolve_city_coordinates(active_role_id, None)
        print(f"   [CITY FALLBACK] Resolved city position from settings: {active_city_pos}")

    if active_city_pos is None:
        active_city_pos = (4332.0, 4194.0)

    cx, cy = active_city_pos[0], active_city_pos[1]


    for h in live_hero_roster:
        hid = h.get("hero_id")
        if hid:
            h["is_gatherer"] = (hid in GATHERING_SPECIALIST_IDS)

    # Log discovered heroes per specification
    hero_desc_list = []
    for h in sorted(live_hero_roster, key=primary_gatherer_sort_key):
        hid = h["hero_id"]
        hname = COMMANDER_NAMES.get(hid, f"Commander #{hid}")
        hlvl = h.get("level", 1)
        hstar = h.get("star", 1)
        hero_desc_list.append(f"{hname} (Level {hlvl}, {hstar} Stars)")
    if hero_desc_list:
        print(f"\n[HERO_DISCOVERY] Discovered {', '.join(hero_desc_list)}")

    print("\n[HERO_INVENTORY]")
    for h in sorted(live_hero_roster, key=primary_gatherer_sort_key):
        hid = h.get("hero_id")
        lvl = int(h.get("level", 1) or 1)
        effective_stars = int(h.get("star", 1) or 1)
        is_gath = bool(h.get("is_gatherer") or hid in GATHERING_SPECIALIST_IDS)
        is_busy = bool(hid in busy_commanders)  # in RoK, only heroes marching on map are busy
        print(f"[HERO_INVENTORY] Hero #{hid}: Level {lvl}, Stars {effective_stars}, is_gatherer={is_gath}, busy={is_busy}")

    try:
        persist_roster_to_db(active_role_id, live_hero_roster, wall_garrison_ids, source="live_gather_stream")
    except Exception as e_pers:
        pass

    print(f"\n[COMMANDERS ROSTER SYNC]")
    print(f"   * Total Live Unlocked Heroes: {len(live_hero_roster)}")
    if wall_garrison_ids:
        print(f"   * Wall Garrison (Active Defense in City, Free to Gather): {sorted(wall_garrison_ids)}")
    if busy_commanders:
        print(f"   * Active Marches on Map: {sorted(busy_commanders)}")

    # PHASE B: Stream radial map viewports centered on the REAL city position
    viewports = generate_radial_viewports(cx, cy, max_km=100)
    for i, vp in enumerate(viewports):
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(build_map_request(vp))))
        if i % 8 == 0:
            await writer.drain()
            await asyncio.sleep(0.03)
    await writer.drain()

    # PHASE C: Stream & collect nearby resource nodes (Opcode 1003)
    deadline_map = asyncio.get_event_loop().time() + 4.0
    while asyncio.get_event_loop().time() < deadline_map:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
            rl = (rh[0] << 8) | rh[1]
            raw_pkt = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
            dec = crypto_rx.decrypt(raw_pkt)
            data, subs = decode_stream_chunks(dec)

            for m in subs:
                if not isinstance(m, dict):
                    continue
                op = m.get(1)
                # Resource nodes from Opcode 1003
                if op == 1003:
                    pmsg = ProtobufCodec.decode_message(m.get(2, b"")) if isinstance(m.get(2), bytes) else {}
                    for item_bytes in pmsg.get(5, []):
                        if not isinstance(item_bytes, bytes): continue
                        obj = ProtobufCodec.decode_message(item_bytes)
                        f1 = ProtobufCodec.decode_message(obj.get(1, b"")) if isinstance(obj.get(1), bytes) else {}
                        node_id = f1.get(1)
                        if not node_id or node_id in seen_node_ids: continue
                        pos_b = f1.get(3)
                        px, py = 0.0, 0.0
                        if pos_b and len(pos_b) >= 10:
                            v1 = struct.unpack("<f", pos_b[1:5])[0]
                            v2 = struct.unpack("<f", pos_b[6:10])[0]
                            if pos_b[0] == 0x0d: px, py = v1, v2  # Tag 1 is X, Tag 2 is Y
                            else: py, px = v1, v2  # Tag 2 is Y, Tag 1 is X

                        type_id = obj.get(2, 1)
                        level = obj.get(3, 1)
                        occupier = obj.get(7, 0)
                        march_st = obj.get(8, 0)
                        is_free = (not occupier or occupier == 0 or occupier == b"") and (not march_st or march_st == 0)

                        wire_dist = math.hypot(px - active_city_pos[0], py - active_city_pos[1])
                        map_km_dist = round(wire_dist / 6.0, 2)
                        dist = map_km_dist
                        res_name_key, res_display = RESOURCE_TYPE_MAP.get(type_id, ("food", "Resource Field"))

                        max_res = unpack_double_field(obj.get(4))
                        rem_res = unpack_double_field(obj.get(5))
                        std_cap = float(STANDARD_NODE_CAPACITIES.get(type_id, {}).get(level, 472500.0))
                        if max_res <= 0.0: max_res = std_cap
                        if rem_res <= 0.0: rem_res = max_res

                        if type_id == 5 or res_name_key == "gem":
                            seen_node_ids.add(node_id)
                            continue
                        tile_alliance_id = f1.get(6, 0) or 0
                        sub7 = ProtobufCodec.decode_message(f1.get(7)) if isinstance(f1.get(7), bytes) else (f1.get(7) if isinstance(f1.get(7), dict) else {})
                        tile_alliance_tag = sub7.get(3, b"")
                        if isinstance(tile_alliance_tag, bytes):
                            tile_alliance_tag = tile_alliance_tag.decode("utf-8", "ignore")
                        tile_alliance_tag = str(tile_alliance_tag or "").strip()
                        if not tile_alliance_id and sub7.get(1):
                            tile_alliance_id = sub7.get(1)
                        tile_alliance_id = int(tile_alliance_id or 0)
                        # True tile owner (field 11). f1.f6/f7 are the
                        # OCCUPIER's alliance, not the tile owner's.
                        owner_aid, owner_tag = extract_tile_owner(obj)

                        seen_node_ids.add(node_id)
                        discovered_nodes.append({
                            "node_id": node_id,
                            "pos": (round(px, 2), round(py, 2)),
                            "dist": dist,
                            "type": res_name_key,
                            "type_id": type_id,
                            "name": res_display,
                            "level": level,
                            "free": is_free,
                            "max_reserves": max_res,
                            "remaining_reserves": rem_res,
                            "alliance_id": tile_alliance_id,
                            "alliance_tag": tile_alliance_tag,
                            "owner_id": owner_aid,
                            "owner_tag": owner_tag
                        })

            # Snoop live 1035 inspect key anywhere in the frame (nested safe)
            if live_inspect_key is None:
                for _sub1035 in subs:
                    if isinstance(_sub1035, dict) and _sub1035.get(1) == 1035:
                        _pb1035 = _sub1035.get(2)
                        if isinstance(_pb1035, (bytes, bytearray)):
                            _k1035 = extract_inspect_key_from_1035(bytes(_pb1035))
                            if _k1035:
                                live_inspect_key = _k1035
                                print(f"   [INSPECT_KEY] Live 1035 session key: {live_inspect_key}")
                                break

            # March cookies ride many opcodes: snoop the raw frame bytes.
            _note_march_cookies(data, active_role_id, busy_commanders, active_marches)

            # Check if Opcode 1002 was present anywhere in raw frame stream
            pos1002 = data.find(b"\x08\xea\x07")
            if pos1002 != -1:
                sub_d = ProtobufCodec.decode_message(data[pos1002:])
                p2 = sub_d.get(2)
                if isinstance(p2, bytes):
                    sub2_d = ProtobufCodec.decode_message(p2)
                    tag19_raw = sub2_d.get(19)
                    if isinstance(tag19_raw, bytes):
                        inner = ProtobufCodec.decode_message(tag19_raw)
                        temp_military = {}
                        for item_b in inner.get(1, []):
                            if isinstance(item_b, bytes):
                                it = ProtobufCodec.decode_message(item_b)
                                uid = it.get(1)
                                cnt = it.get(3) or it.get(2) or 0
                                if uid and cnt > 0:
                                    temp_military[uid] = cnt
                        if temp_military:
                            troops_in_city.clear()
                            troops_in_city.update(temp_military)
                            synced_full_military = True
        except asyncio.TimeoutError:
            break
        except Exception:
            pass

    # PHASE A2: late authoritative commander catalogue. The early 366 is
    # often dropped while the server streams the login flood; a late query
    # after sync lands reliably (verified: standalone probe gets 367 instantly).
    if not seen_367:
        try:
            print("   [HERO_DISCOVERY] Late catalogue query (366)...")
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 366, 2: b""}))))
            await writer.drain()
            _end367 = asyncio.get_event_loop().time() + 4.0
            _late_ops = {}
            _late_ack366 = []
            while asyncio.get_event_loop().time() < _end367:
                try:
                    _rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.6)
                    _rl = (_rh[0] << 8) | _rh[1]
                    _raw = await asyncio.wait_for(reader.readexactly(_rl), timeout=0.6)
                    _dec = crypto_rx.decrypt(_raw)
                    _data, _subs = decode_stream_chunks(_dec)
                    for _m in _subs:
                        if not isinstance(_m, dict):
                            continue
                        _op = _m.get(1)
                        if isinstance(_op, int):
                            _late_ops[_op] = _late_ops.get(_op, 0) + 1
                            if _op == 1:
                                try:
                                    _pd = ProtobufCodec.decode_message(_m.get(2, b"")) if isinstance(_m.get(2), bytes) else {}
                                    if isinstance(_pd, dict) and _pd.get(1) == 366:
                                        _late_ack366.append(_pd.get(2))
                                except Exception:
                                    pass
                        if _m.get(1) == 367:
                            seen_367 = True
                            _p = _m.get(2)
                            if isinstance(_p, bytes):
                                _h367 = parse_heroes_from_367(_p)
                                if _h367:
                                    live_hero_roster = merge_rosters(live_hero_roster, _h367)
                                    for _h in _h367:
                                        if _h["hero_id"] not in discovered_heroes:
                                            discovered_heroes.append(_h["hero_id"])
                                    print(f"   [HERO_DISCOVERY] Opcode 367 (late): Parsed {len(_h367)} unlocked heroes.")
                            _end367 = 0
                            break
                        if _m.get(1) in (1005, 1023):
                            _note_march_cookies(_m.get(2), active_role_id, busy_commanders, active_marches)
                            _note_march_cookies(_data, active_role_id, busy_commanders, active_marches)
                        if _m.get(1) == 1035:
                            _p1035b = _m.get(2)
                            if isinstance(_p1035b, (bytes, bytearray)):
                                _k1035b = extract_inspect_key_from_1035(bytes(_p1035b))
                                if _k1035b and _k1035b != live_inspect_key:
                                    live_inspect_key = _k1035b
                                    print(f"   [INSPECT_KEY] Live 1035 session key: {live_inspect_key}")
                    if _end367 == 0:
                        break
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
            print(f"   [HERO_DISCOVERY] Late window ops: {sorted(_late_ops)} | 366-acks: {_late_ack366}")
        except Exception as _e367:
            print(f"   [HERO_DISCOVERY] late 367 query note: {_e367}")

    # Consolidate Opcode 125 military state without overwriting distinct units
    if raw_units_125 and not synced_full_military:
        troops_in_city.clear()
        for u_key, (ut, cnt) in raw_units_125.items():
            troops_in_city[ut] = troops_in_city.get(ut, 0) + cnt
        synced_full_military = True

    # If troops not captured from 125, set fallback default based on known live garrison
    if not troops_in_city:
        troops_in_city = {4: 15000, 1: 10000, 3: 8000, 2: 5000}

    total_avail_soldiers = sum(troops_in_city.values())
    active_marches_count = len(active_marches)

    # Determine real physical march capacity from discovered City Hall level (or DB)
    if not discovered_city_hall_lvl and active_role_id:
        try:
            from app.models import CharacterDAO
            _c_rec = CharacterDAO.get_by_role_id(str(active_role_id))
            if _c_rec:
                discovered_city_hall_lvl = int(_c_rec.get("city_hall") or _c_rec.get("city_level") or 0)
        except Exception:
            pass
    effective_ch = int(discovered_city_hall_lvl or 16)
    account_max_queues = get_max_marches_for_city_hall(effective_ch)
    free_queues = max(0, account_max_queues - active_marches_count)

    print(f"\n[ENGINE] Status Sync Completed:")
    print(f"   * Available Army in City: {total_avail_soldiers:,} soldiers")
    for ut, cnt in sorted(troops_in_city.items(), key=lambda x: -NATIVE_UNIT_LOAD.get(x[0], 8.0)):
        load_val = NATIVE_UNIT_LOAD.get(ut, 8.0)
        print(f"      - Unit Type #{ut}: {cnt:,} soldiers (Load: {load_val} | Cap: {int(cnt * load_val):,})")
    print(f"   * City Hall Level: {effective_ch} -> Maximum March Queues: {account_max_queues}")
    print(f"   * Active Marches: {active_marches_count}/{account_max_queues} queues")
    print(f"   * Free March Queues: {free_queues}")
    # CRITICAL PATCH: Disable only_finishable gate - allow all levels even if army cannot fully clear
    only_finishable = False
    # Ensure skip_partially toggle is respected (from function argument or CharacterSettingsDAO)
    if not skip_partially and active_role_id:
        try:
            from app.models import CharacterDAO, CharacterSettingsDAO
            _dbc = CharacterDAO.get_by_role_id(str(active_role_id))
            if _dbc and _dbc.get("id"):
                _cset = CharacterSettingsDAO.get_by_character_id(_dbc["id"]) or {}
                _gcfg = _cset.get("gather", {})
                skip_partially = bool(_gcfg.get("skip_partially", _gcfg.get("skip_partially_depleted", True)))
        except Exception:
            pass
    if skip_partially:
        print(f"   [FILTER] Skip Partially Gathered Nodes: ENABLED (Filter >= 70% full capacity)")
    else:
        print(f"   [FILTER] Skip Partially Gathered Nodes: DISABLED")

    # Flush stale reservations (15min) so local 2.2km tiles become available
    try:
        from app.models import NodeReservationDAO
        if hasattr(NodeReservationDAO, "cleanup_stale_reservations"):
            NodeReservationDAO.cleanup_stale_reservations(max_age_minutes=15)
        else:
            from app.database import get_db_connection
            import datetime as _dt
            now_s = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            con = get_db_connection()
            with con:
                try:
                    con.execute("DELETE FROM claimed_resource_nodes WHERE expires_at <= ?", (now_s,))
                except: pass
                try:
                    con.execute("DELETE FROM claimed_resource_nodes WHERE claimed_at <= datetime('now', '-15 minutes')")
                except: pass
    except Exception as e:
        print(f"[RESERVATION] Cleanup notice: {e}")

    logged_skipped_level = set()

    def is_node_level_allowed(node) -> bool:
        try:
            lvl = int(node.get("level", 1))
            nid = node.get("node_id") or node.get("id") or 0
            if lvl > max_allowed_level:
                if nid not in logged_skipped_level:
                    logged_skipped_level.add(nid)
                    print(f"[LEVEL_FILTER] Node #{nid} (Level {lvl}) skipped: exceeds max cap ({max_allowed_level}).")
                return False
            return True
        except Exception:
            return True

    free_nodes = [n for n in discovered_nodes if n["free"] and n.get("type") in ALLOWED_GATHER_RESOURCES and n.get("type_id") != 5 and is_node_level_allowed(n)]
    print(f"\n[SEARCH] Discovered {len(free_nodes)} free resource deposits (enforcing max level {max_allowed_level}):")

    # Tile-alliance field diagnostics: sampled so we can verify whether
    # territory ownership bytes are actually populated on map tiles.
    try:
        _with_owner = [n for n in discovered_nodes if int(n.get("owner_id", 0) or 0) > 0 or str(n.get("owner_tag", "") or "").strip()]
        print(f"   [TERRITORY_DIAG] Tiles with owner bytes: {len(_with_owner)}/{len(discovered_nodes)} | own=[{active_alliance_tag}#{active_alliance_id}] avoid={avoid_territory}")
        for _sn in discovered_nodes[:6]:
            print(f"   [TERRITORY_DIAG] Node #{_sn.get('node_id')} { _sn.get('type')} L{_sn.get('level')} owner={_sn.get('owner_tag') or ''}#{_sn.get('owner_id', 0)}")
    except Exception:
        pass

    for fn in sorted(free_nodes, key=lambda x: (-int(x.get("level", 1)), float(x.get("dist", 999.0))))[:8]:
        print(f"   * {fn['name']} #{fn['node_id']} (Lvl {fn['level']}) at {fn['pos']} - Reserves: {int(fn['remaining_reserves']):,} - Dist: {fn['dist']}km")

    if free_queues == 0:
        print("\n[SUCCESS] All march queues are currently gathering on the map!")
        save_gather_status(active_marches, total_avail_soldiers)
        writer.close()
        await writer.wait_closed()
        return {
            "success": True,
            "dispatched_count": 0,
            "active_marches_count": len(active_marches),
            "max_marches": account_max_queues,
            "free_queues": 0,
            "reason": "all_queues_busy",
            "dispatches": [],
            "dispatched_details": []
        }

    # Persist city coordinates to DB for newly registered accounts
    if active_city_pos and active_city_pos != (0.0, 0.0):
        try:
            from app.models import CharacterDAO, CharacterSettingsDAO
            disp_x = round(active_city_pos[0] / 6.0, 1)
            disp_y = round(active_city_pos[1] / 6.0, 1)
            try:
                CharacterDAO.update_city_position(str(active_role_id), disp_x, disp_y)
            except Exception:
                # Fallback: direct SQL if method missing
                try:
                    from app.database import get_db_connection as _gdb
                    _con = _gdb()
                    cols = [r[1] for r in _con.execute("PRAGMA table_info(characters)").fetchall()]
                    if "city_x" in cols and "city_y" in cols:
                        _con.execute("UPDATE characters SET city_x=?, city_y=? WHERE role_id=?", (disp_x, disp_y, str(active_role_id)))
                        _con.commit()
                except Exception:
                    pass
            db_c = CharacterDAO.get_by_role_id(str(active_role_id))
            if db_c and db_c.get("id"):
                c_set = CharacterSettingsDAO.get_by_character_id(db_c["id"]) or {}
                g_cfg = c_set.get("gather", {})
                g_cfg["city_x"] = disp_x
                g_cfg["city_y"] = disp_y
                CharacterSettingsDAO.upsert(db_c["id"], gather=g_cfg)
        except Exception:
            pass

    # 4. Multi-March Dispatch Loop — RELENTLESS ARCHITECTURE (Error 135/155 decoupled)
    # Strictly enforce dashboard max node level cap with descending fallback ranking
    target_level = max_allowed_level
    level_mode = "descending_fallback"
    target_dispatches = free_queues
    # NEVER exceed the site's configured march counts: total configured
    # (food+wood+stone+gold) and max_marches are hard ceilings, so a 4-queue
    # city with only 2 configured marches sends at most 2.
    try:
        _cfg_total = 0
        _has_cfg = False
        for _r in ("food", "wood", "stone", "gold"):
            _c = get_configured_march_count(_r, gather_config)
            if _c is not None:
                _has_cfg = True
                _cfg_total += max(0, int(_c))
        if _has_cfg and _cfg_total >= 0:
            target_dispatches = min(target_dispatches, _cfg_total)
        _cfg_max = gather_config.get("max_marches", gather_config.get("maxMarches"))
        if _cfg_max is not None:
            target_dispatches = min(target_dispatches, max(0, int(_cfg_max)))
        # Absolute engine ceiling: never more than 5 marches per run.
        target_dispatches = min(target_dispatches, 5)
    except Exception:
        pass
    if target_dispatches < free_queues:
        print(f"   [MARCH_CAP] Site settings cap: {target_dispatches} dispatch(es) "
              f"(free queues: {free_queues}) - never exceeding configured counts.")
    dispatched = 0
    dispatched_count = 0
    failed_nodes_session = set()
    failed_heroes_session = set()
    assigned_nodes = set()
    dispatched_details = []

    # Compute march targets with dynamic auto-balancing and strict zero-allocation exclusion
    march_targets = determine_march_resource_targets(
        free_queues=target_dispatches,
        config=gather_config,
        city_rss=live_city_rss,
    )
    auto_balance_active = bool(
        gather_config.get("auto_balance_lowest_rss",
        gather_config.get("auto_balance",
        gather_config.get("prioritize_lowest_rss", False)))
    )
    print(f"[AUTO-BALANCE] Enabled: {auto_balance_active} | City Reserves: Food={live_city_rss.get('food', 0):,} Wood={live_city_rss.get('wood', 0):,} Stone={live_city_rss.get('stone', 0):,} Gold={live_city_rss.get('gold', 0):,}")
    print(f"[AUTO-BALANCE] Target allocation for {target_dispatches} queues: {march_targets}")

    # Determine allowed gather types (strictly excluding any resource with explicit 0 allocation)
    _cfg_counts = {r: get_configured_march_count(r, gather_config) for r in ["food", "wood", "stone", "gold"]}
    if any(cnt is not None for cnt in _cfg_counts.values()):
        allowed_gather_types = [r for r in ["food", "wood", "stone", "gold"] if (_cfg_counts.get(r) or 0) > 0]
    else:
        allowed_gather_types = list(dict.fromkeys(march_targets))
    if not allowed_gather_types:
        allowed_gather_types = ["food", "wood", "stone"]

    print(f"\n[4/4] Dispatching up to {target_dispatches} march(es) — RELENTLESS MODE...")

    logged_skipped_partial = set()
    logged_rejected_territory = set()

    def is_node_full_enough(node, skip_flag=True, min_ratio=0.70):
        if not skip_flag:
            return True
        try:
            t_id = int(node.get("type_id", 1))
            lvl = int(node.get("level", 1))
            std_cap = float(STANDARD_NODE_CAPACITIES.get(t_id, {}).get(lvl, 472500.0))
            max_r = float(node.get("max_reserves") or std_cap)
            if max_r <= 0:
                max_r = std_cap
            rem_r = float(node.get("remaining_reserves") if node.get("remaining_reserves") is not None else max_r)
            if rem_r <= 0:
                rem_r = max_r
            capacity_ratio = rem_r / max_r if max_r > 0 else 1.0
            if capacity_ratio < min_ratio:
                nid = node.get("node_id")
                if nid not in logged_skipped_partial:
                    logged_skipped_partial.add(nid)
                    print(f"[GATHER_FILTER] Node #{nid} skipped: partially depleted ({int(rem_r):,}/{int(max_r):,} - {capacity_ratio:.1%}).")
                return False
            return True
        except Exception:
            return True

    def _select_next_node(req_type, exclude_nodes):
        # Dynamic real-time claim query - re-read DB on every selection to prevent cross-farm collision
        try:
            live_claimed_nodes = get_fleet_claimed_node_ids(int(active_kid or kingdom_id or 3057))
        except Exception:
            live_claimed_nodes = set()

        # Descending fallback: prefer highest available level <= max_allowed_level within normal gathering radius (up to 35km)
        for target_lvl in range(max_allowed_level, 0, -1):
            for max_km in [5.0, 15.0, 35.0]:
                cands = [
                    n for n in free_nodes
                    if n["type"] == req_type
                    and n["type"] in ALLOWED_GATHER_RESOURCES
                    and int(n.get("level", 1)) == target_lvl
                    and n["node_id"] not in assigned_nodes
                    and n["node_id"] not in exclude_nodes
                    and n["node_id"] not in live_claimed_nodes
                    and 0.01 <= float(n.get("dist", 999.0)) <= max_km
                    and is_node_level_allowed(n)
                    and is_tile_accessible(n, active_alliance_id, active_alliance_tag, avoid_territory=avoid_territory, log_fn=print, logged_nodes=logged_rejected_territory)
                    and is_node_full_enough(n, skip_partially, min_ratio=0.70)
                ]
                if cands:
                    cands.sort(key=lambda x: (-int(x.get("level", 1)), float(x.get("dist", 999.0))))
                    return cands[0]

        # If nothing found within 35km, expand search up to 100km across all permitted levels
        for max_km in [50.0, 75.0, 100.0]:
            cands = [
                n for n in free_nodes
                if n["type"] == req_type
                and n["type"] in ALLOWED_GATHER_RESOURCES
                and n["node_id"] not in assigned_nodes
                and n["node_id"] not in exclude_nodes
                and n["node_id"] not in live_claimed_nodes
                and 0.01 <= float(n.get("dist", 999.0)) <= max_km
                and is_node_level_allowed(n)
                and is_tile_accessible(n, active_alliance_id, active_alliance_tag, avoid_territory=avoid_territory, log_fn=print, logged_nodes=logged_rejected_territory)
                and is_node_full_enough(n, skip_partially, min_ratio=0.70)
            ]
            if cands:
                print(f"   [SEARCH] Expanded to {int(max_km)}km map ({int(max_km*6)} wire) for {req_type}: {len(cands)} nodes")
                cands.sort(key=lambda x: (-int(x.get("level", 1)), float(x.get("dist", 999.0))))
                return cands[0]

        # Fallback substitution: strictly enforce zero-allocation exclusion
        for _fallback in [r for r in allowed_gather_types if r != req_type]:
            for target_lvl in range(max_allowed_level, 0, -1):
                for max_km in [5.0, 15.0, 35.0]:
                    cands = [
                        n for n in free_nodes
                        if n["type"] == _fallback
                        and n["type"] in ALLOWED_GATHER_RESOURCES
                        and int(n.get("level", 1)) == target_lvl
                        and n["node_id"] not in assigned_nodes
                        and n["node_id"] not in exclude_nodes
                        and n["node_id"] not in live_claimed_nodes
                        and 0.01 <= float(n.get("dist", 999.0)) <= max_km
                        and is_node_level_allowed(n)
                        and is_tile_accessible(n, active_alliance_id, active_alliance_tag, avoid_territory=avoid_territory, log_fn=print, logged_nodes=logged_rejected_territory)
                        and is_node_full_enough(n, skip_partially, min_ratio=0.70)
                    ]
                    if cands:
                        print(f"   [SEARCH] Substituted {_fallback} (Lvl {target_lvl}) for {req_type}: {len(cands)} nodes within {int(max_km)}km")
                        cands.sort(key=lambda x: (-int(x.get("level", 1)), float(x.get("dist", 999.0))))
                        return cands[0]

            for max_km in [50.0, 100.0]:
                cands = [
                    n for n in free_nodes
                    if n["type"] == _fallback
                    and n["type"] in ALLOWED_GATHER_RESOURCES
                    and n["node_id"] not in assigned_nodes
                    and n["node_id"] not in exclude_nodes
                    and n["node_id"] not in live_claimed_nodes
                    and 0.01 <= float(n.get("dist", 999.0)) <= max_km
                    and is_node_level_allowed(n)
                    and is_tile_accessible(n, active_alliance_id, active_alliance_tag, avoid_territory=avoid_territory, log_fn=print, logged_nodes=logged_rejected_territory)
                    and is_node_full_enough(n, skip_partially, min_ratio=0.70)
                ]
                if cands:
                    print(f"   [SEARCH] Substituted {_fallback} for {req_type}: {len(cands)} nodes within {int(max_km)}km")
                    cands.sort(key=lambda x: (-int(x.get("level", 1)), float(x.get("dist", 999.0))))
                    return cands[0]
        return None

    cmd_155_rejections: Dict[int, int] = {}
    cross_135_streak = 0
    server_busy_abort = False
    key_missing_abort = False
    while dispatched_count < target_dispatches:
        current_march_num = active_marches_count + dispatched_count + 1
        queue_confirmed = False
        if total_avail_soldiers <= 0:
            print(f"[ENGINE] All city troops deployed. Deployed {dispatched_count}/{target_dispatches}.")
            break
        remaining_queues_needed = target_dispatches - dispatched_count
        candidate_allocations = allocate_gathering_commanders(
            roster=live_hero_roster,
            target_queues=remaining_queues_needed,
            busy_commanders=busy_commanders,
            wall_garrison=wall_garrison_ids,
            failed_heroes=failed_heroes_session,
            fallback_hero_ids=VERIFIED_FARM_GATHERERS,
        )
        if not candidate_allocations:
            print(f"[ENGINE] Exhausted eligible commanders. Deployed {dispatched_count}/{target_dispatches}.")
            break
        if not any(p.get("hero_id") not in failed_heroes_session
                   and p.get("hero_id") not in busy_commanders
                   for p, _ in candidate_allocations):
            print(f"[ENGINE] All remaining commanders busy/failed - nothing to dispatch. "
                  f"Deployed {dispatched_count}/{target_dispatches}.")
            break

        req_type = march_targets[dispatched_count % len(march_targets)].lower()
        # Manual commander pairs (dashboard slots): the Nth confirmed march of
        # this resource uses custom_pairs[res][N]. Owned + free heroes only;
        # otherwise the queue falls back to auto selection (logged).
        _pair_idx = sum(1 for _d in dispatched_details if str(_d.get("type", "")).lower() == req_type)
        # NOTE: failed_heroes_session is deliberately NOT consulted here - a
        # manual pair refused on one (possibly bad) node is retried first on
        # the next node; only truly busy (server-known) heroes are skipped.
        _man_pri, _man_sec, _man_note = resolve_manual_pair(
            gather_config, req_type, _pair_idx,
            live_hero_roster, busy_commanders, set())
        if _man_note == "manual_ok":
            _mp = _man_pri["hero_id"]
            _ms = _man_sec["hero_id"] if _man_sec else 0
            _man_ids = {_mp} | ({_ms} if _ms else set())
            candidate_allocations = [(_man_pri, _man_sec)] + [
                (ap, ase) for (ap, ase) in candidate_allocations
                if ap.get("hero_id") not in _man_ids]
            _sec_txt = f" + #{_ms}" if _ms else " (solo)"
            print(f"[MANUAL] Queue #{current_march_num} ({req_type} #{_pair_idx + 1}): "
                  f"manual pair #{_mp}{_sec_txt} (owned + free) - priority over auto.")
        elif (gather_config or {}).get("manual_commanders_enabled", (gather_config or {}).get("manualCommanders", False)):
            print(f"[MANUAL] Queue #{current_march_num} ({req_type} #{_pair_idx + 1}): "
                  f"manual pair unusable ({_man_note}) - auto fallback.")
        target_node = _select_next_node(req_type, failed_nodes_session)
        if not target_node:
            # Emergency fallback: ONLY resources allowed by site settings.
            # A resource with 0 configured marches (e.g. gold) must NEVER
            # receive a march, even when it is the lowest reserve.
            for any_rss in [r for r in allowed_gather_types if r in ALLOWED_GATHER_RESOURCES]:
                target_node = _select_next_node(any_rss, failed_nodes_session)
                if target_node:
                    print(f"   [SEARCH] Fallback resource selected: {any_rss} node #{target_node['node_id']} for queue #{current_march_num}")
                    break
        if not target_node:
            print(f"[ENGINE] Exhausted available resource tiles for all resource types. Deployed {dispatched_count}/{target_dispatches}.")
            break

        assigned_nodes.add(target_node["node_id"])
        node_135_count = 0
        # Claim node in DB before sending opcode to prevent sister farm collision
        try:
            from app.models import NodeReservationDAO
            NodeReservationDAO.claim_node(
                node_id=int(target_node["node_id"]),
                kingdom_id=int(active_kid or kingdom_id or 3057),
                role_id=str(active_role_id),
                character_name=char_name,
                resource_type=str(target_node.get("type","")),
                node_level=int(target_node.get("level",1)),
                pos_x=float(target_node["pos"][0]) if isinstance(target_node.get("pos"), (list,tuple)) and len(target_node["pos"])>0 else 0.0,
                pos_y=float(target_node["pos"][1]) if isinstance(target_node.get("pos"), (list,tuple)) and len(target_node["pos"])>1 else 0.0,
                duration_minutes=120
            )
        except Exception as e:
            print(f"[RESERVATION] claim failed for {target_node['node_id']}: {e}")

        node_reserves = target_node.get("remaining_reserves") or target_node.get("max_reserves") or 472500.0
        buffered_node_reserves = int(node_reserves) + 30000

        ack_code_last = None
        error_155_flag = False
        error_node_flag = False
        # Pre-loop defaults: if EVERY candidate is skipped as busy/failed,
        # the for body (and its per-attempt init) never runs - the tail
        # below must still see bound flags, never UnboundLocalError.
        confirmed = False
        error_135 = False
        error_155 = False
        error_node = False
        error_max_queues = False
        saw_spawn = False
        saw_903 = False

        for pri_info, sec_info in candidate_allocations:
            p_id = pri_info["hero_id"]
            if p_id in failed_heroes_session or p_id in busy_commanders:
                continue
            s_id = 0
            if sec_info and sec_info.get("hero_id", 0) > 0:
                cand_s = sec_info["hero_id"]
                if cand_s not in failed_heroes_session and cand_s not in busy_commanders and cand_s != p_id:
                    s_id = cand_s

            primary_cmd = p_id
            sec_cmd = s_id

            primary_load_bonus = min(COMMANDER_LOAD_BONUS.get(primary_cmd, 0.0), 5.0)
            sec_load_bonus = min(COMMANDER_LOAD_BONUS.get(sec_cmd, 0.0), 5.0) if sec_cmd else 0.0
            total_cmd_bonus = primary_load_bonus + sec_load_bonus
            role_max_cap = get_role_march_capacity(int(active_role_id))
            pri_level = int(pri_info.get("level") or 1)
            # RoK march capacity is governed by City Hall level and military tech.
            # Never artificially throttle marches to 2,000 units (which caused the 40k gather limit bug).
            effective_march_cap = role_max_cap

            tech_bonuses = {"global_load_pct": GATHER_LOAD_BONUS * 100.0}

            calc_result = GatheringLoadEngine.calculate_required_march_composition(
                target_resource_amount=buffered_node_reserves,
                available_troops=troops_in_city,
                account_bonuses=tech_bonuses,
                commander_bonus_pct=total_cmd_bonus,
                march_cap=effective_march_cap,
                remaining_queues=remaining_queues_needed,
                safety_margin_pct=5.0,
                flat_cushion=30000
            )
            allocated_army = calc_result["wire_army"]
            total_units = calc_result["total_units"]
            march_load = calc_result["total_load"]
            selected_troops_dict = calc_result["troops"]
            if not allocated_army or total_units <= 0:
                print(f"[ENGINE] Insufficient troops for March #{current_march_num}. Skipping node #{target_node['node_id']}.")
                failed_nodes_session.add(target_node["node_id"])
                break

            print(f"   [TERRITORY] Node #{target_node['node_id']} owner={target_node.get('owner_tag', '')}#{target_node.get('owner_id', 0)} "
                  f"passed avoid-territory filter (neutral or own).")
            primary_name = COMMANDER_NAMES.get(primary_cmd, f"Commander #{primary_cmd}")
            pri_level = int(pri_info.get("level", 1) or 1)
            if sec_cmd and int(sec_cmd) > 0:
                sec_name = COMMANDER_NAMES.get(sec_cmd, f"Commander #{sec_cmd}")
                sec_level = int(sec_info.get("level", 1) or 1) if sec_info else 1
                cmd_display = f"{primary_name} (L{pri_level}) + {sec_name} (L{sec_level})"
                print(f"\n[DISPATCH] March #{current_march_num} -> {target_node['name']} #{target_node['node_id']} (Lvl {target_node['level']})")
                print(f"   Target Reserves: {int(node_reserves):,} | Distance: {target_node['dist']}km")
                print(f"   Commanders: {cmd_display} | Units: {total_units:,} | Load: {int(march_load):,}")
                print(f"   [MARCH_COMPOSE] Queue #{current_march_num}: Primary {primary_name} (L{pri_level}) + Secondary {sec_name} (L{sec_level})")
            else:
                cmd_display = f"{primary_name} (L{pri_level}) (Solo)"
                print(f"\n[DISPATCH] March #{current_march_num} -> {target_node['name']} #{target_node['node_id']} (Lvl {target_node['level']})")
                print(f"   Target Reserves: {int(node_reserves):,} | Distance: {target_node['dist']}km")
                print(f"   Commanders: {cmd_display} | Units: {total_units:,} | Load: {int(march_load):,}")
                print(f"   [MARCH_COMPOSE] Queue #{current_march_num}: Primary {primary_name} (L{pri_level}) SOLO")

            writer.write(FrameParser.build_frame(crypto_tx.encrypt(build_map_request(target_node["pos"]))))
            await writer.drain()
            await asyncio.sleep(0.05)
            # Live 1035 key is MANDATORY as 1050 field 1 (official parity).
            # Refresh it if the session rotated it; abort this queue honestly
            # rather than sending the alliance ID (guaranteed 135).
            _inspect_field1 = live_inspect_key or 0
            if not _inspect_field1:
                try:
                    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b""}))))
                    await writer.drain()
                    _kend = time.time() + 2.0
                    while time.time() < _kend and not _inspect_field1:
                        try:
                            _kh = await asyncio.wait_for(reader.readexactly(2), timeout=0.4)
                            _kl = (_kh[0] << 8) | _kh[1]
                            _kr = await asyncio.wait_for(reader.readexactly(_kl), timeout=0.4)
                            _kd = crypto_rx.decrypt(_kr)
                            _kz = _kd.find(b"\x78\x9c")
                            if _kz == -1:
                                _kz = _kd.find(b"\x78\x01")
                            _kdata = zlib.decompress(_kd[_kz:]) if _kz != -1 else _kd
                            _km = ProtobufCodec.decode_message(_kdata)
                            for _ksub in _collect_subs(_km):
                                if isinstance(_ksub, dict) and _ksub.get(1) == 1035:
                                    _pbk = _ksub.get(2)
                                    if isinstance(_pbk, (bytes, bytearray)):
                                        _kk = extract_inspect_key_from_1035(bytes(_pbk))
                                        if _kk:
                                            live_inspect_key = _kk
                                            _inspect_field1 = _kk
                                            print(f"   [INSPECT_KEY] Refreshed 1035 session key: {live_inspect_key}")
                                            break
                        except asyncio.TimeoutError:
                            continue
                        except Exception:
                            break
                except Exception:
                    pass
            if not _inspect_field1:
                print(f"[-] Queue #{current_march_num}: no live 1035 inspect key - aborting run honestly (would be 135). Node #{target_node['node_id']} NOT blacklisted.")
                key_missing_abort = True
                break
            pkt_1050 = build_inspect(target_node["node_id"], target_node["pos"], city_pos=active_city_pos, alliance_id=_inspect_field1)
            print(f"      [INSPECT 1050] Node #{target_node['node_id']} key={_inspect_field1}")
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_1050)))
            await writer.drain()
            _t1050 = time.time()
            # Ground truth (decoded_20261005_075706.txt): the official client
            # sends ONLY 1050 (inspect), waits ~4s, then 1012. It NEVER sends
            # the legacy 089d07/08a703/08fe4b/0809 hex packets nor the
            # SendTroopConfirm(op 8) JSON blob - removed, they risk confusing
            # march state and triggering 135 refusals.
            start_ack = time.time()
            inspect_1051 = None
            while time.time() - start_ack < 2.0:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
                    rl = (rh[0] << 8) | rh[1]
                    raw_b = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
                    dec = crypto_rx.decrypt(raw_b)
                    data, subs1051 = decode_stream_chunks(dec)
                    for _m1051 in subs1051:
                        if not isinstance(_m1051, dict):
                            continue
                        if _m1051.get(1) == 1051:
                            inspect_1051 = _m1051.get(2)
                        if _m1051.get(1) == 1035:
                            _pbk2 = _m1051.get(2)
                            if isinstance(_pbk2, (bytes, bytearray)):
                                _kk2 = extract_inspect_key_from_1035(bytes(_pbk2))
                                if _kk2 and _kk2 != live_inspect_key:
                                    live_inspect_key = _kk2
                    got_1051 = any(isinstance(_s, dict) and _s.get(1) == 1051 for _s in subs1051)
                    if got_1051:
                        break
                    # Fresh march-state snoop: cookies also ride 1024/1013/365/903.
                    _note_march_cookies(data, active_role_id, busy_commanders, active_marches)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
            if inspect_1051 is not None:
                try:
                    _d1051 = ProtobufCodec.decode_message(bytes(inspect_1051)) if isinstance(inspect_1051, (bytes, bytearray)) else inspect_1051
                    print(f"      [INSPECT 1051] Node #{target_node['node_id']}: {repr(_d1051)[:300]}")
                except Exception:
                    pass
            await asyncio.sleep(0.05)
            # Official pacing: ~3.5-4s between 1050 inspect and 1012 dispatch.
            _elapsed1050 = time.time() - _t1050
            if _elapsed1050 < 3.5:
                await asyncio.sleep(3.5 - _elapsed1050)
            pkt_1012 = build_gather_dispatch(
                target_node["node_id"],
                army_list=allocated_army,
                primary_hero_id=primary_cmd,
                secondary_hero_id=sec_cmd,
                march_index=current_march_num
            )
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_1012)))
            await writer.drain()
            confirmed = False
            error_135 = False
            error_155 = False
            error_node = False
            error_max_queues = False
            ack_code_last = None
            saw_spawn = False
            saw_903 = False
            start_wait = time.time()
            while time.time() - start_wait < 3.5:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.6)
                    rl = (rh[0] << 8) | rh[1]
                    raw_b = await asyncio.wait_for(reader.readexactly(rl), timeout=0.6)
                    dec = crypto_rx.decrypt(raw_b)
                    data, subs = decode_stream_chunks(dec)
                    for item in subs:
                        if not isinstance(item, dict):
                            continue
                        op = item.get(1)
                        if op is not None:
                            p_body = item.get(2)
                            p_dec = ProtobufCodec.decode_message(p_body) if isinstance(p_body, bytes) else p_body
                            print(f"      [GATEWAY ACK] Opcode: {op} | Payload: {p_dec}")
                            if op == 1035:
                                if isinstance(p_body, (bytes, bytearray)):
                                    _kk3 = extract_inspect_key_from_1035(bytes(p_body))
                                    if _kk3 and _kk3 != live_inspect_key:
                                        live_inspect_key = _kk3
                            if op in (1005, 1023):
                                _note_march_cookies(item.get(2), active_role_id, busy_commanders, active_marches)
                            if op == 903:
                                saw_903 = True
                            if op in (1023, 1024, 1005, 1013, 365):
                                saw_spawn = True
                            if op == 1 and isinstance(p_dec, dict):
                                if p_dec.get(1) == 1012:
                                    code = p_dec.get(2, -1)
                                    ack_code_last = code
                                    if code in (0, 1):
                                        confirmed = True
                                        break
                                    elif code == 135:
                                        error_135 = True
                                        break
                                    elif code == 155:
                                        error_155 = True
                                        break
                                    elif code == 164:
                                        error_max_queues = True
                                        ack_code_last = 164
                                        break
                                    elif code in (30, 31, 102):
                                        error_node = True
                                        break
                                    else:
                                        ack_code_last = code
                                        break
                    if confirmed or error_135 or error_155 or error_node or error_max_queues or saw_903:
                        break
                    # Fresh march-state snoop on the raw decrypted frame: march
                    # cookies also ride 1024/1013/365/903, not just 1005/1023.
                    _note_march_cookies(data, active_role_id, busy_commanders, active_marches)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
            # Verdict priority: an explicit 1012 refusal always wins over stray
            # spawn frames; 903/explicit-OK confirms; spawn-only (1023 etc.
            # with no explicit verdict) confirms weakly as before.
            if not confirmed and not (error_135 or error_155 or error_node or error_max_queues):
                if saw_903:
                    confirmed = True
                    ack_code_last = 0
                elif saw_spawn:
                    confirmed = True
                    ack_code_last = 0
                    print(f"      [GATEWAY ACK] spawn-only confirm (no explicit 1012 verdict)")
            if confirmed:
                cross_135_streak = 0
                GatheringLoadEngine.deduct_troops(troops_in_city, selected_troops_dict)
                total_avail_soldiers = sum(troops_in_city.values())
                print(f"[SUCCESS] March #{current_march_num} CONFIRMED deployed with {cmd_display} on Node #{target_node['node_id']}!")
                busy_commanders.add(primary_cmd)
                failed_heroes_session.add(primary_cmd)
                if sec_cmd:
                    busy_commanders.add(sec_cmd)
                    failed_heroes_session.add(sec_cmd)
                active_marches[f"m_{primary_cmd}"] = primary_cmd
                dispatched_details.append({
                    "cmd_id": primary_cmd,
                    "sec_cmd_id": sec_cmd,
                    "cmd_name": cmd_display,
                    "cmd_level": int(pri_info.get("level", 1) or 1),
                    "sec_level": int(sec_info.get("level", 1) or 1) if sec_info else 0,
                    "type": target_node["type"],
                    "target": f"{target_node['name']} #{target_node['node_id']} (Lvl {target_node['level']})",
                    "troops": total_units,
                    "load": int(march_load),
                    "node_reserves": int(node_reserves)
                })
                # Ultra-detailed telemetry for dashboard (per spec)
                try:
                    primary_unit_str = "T1 Siege"
                    if allocated_army:
                        try:
                            top_unit_id = max(allocated_army, key=lambda x: x[1])[0]
                            cat_tier = UNIT_ID_TO_CAT_TIER.get(int(top_unit_id), ("siege", 1))
                            primary_unit_str = f"T{cat_tier[1]} {cat_tier[0].capitalize()}"
                        except Exception:
                            pass
                    dash_gather_msg = (
                        f"Sent gatherer [{cmd_display}] to {target_node['type'].capitalize()} level {target_node['level']} "
                        f"({total_units:,} troops [{primary_unit_str}], cargo {int(march_load):,}, node reserves {int(node_reserves):,})"
                    )
                    print(f"[DASHBOARD] {dash_gather_msg}")
                    try:
                        from app.models import TaskLogDAO, CharacterDAO
                        db_c = CharacterDAO.get_by_role_id(str(active_role_id))
                        TaskLogDAO.create(
                            task_id=f"gather_{active_role_id}_{current_march_num}_{int(time.time())}",
                            role_id=str(active_role_id),
                            task_type="gather_dispatch",
                            status="SUCCESS",
                            details={
                                "message": dash_gather_msg,
                                "character_name": char_name,
                                "resource": target_node["type"],
                                "level": target_node["level"],
                                "units": total_units,
                                "tier": primary_unit_str,
                                "cargo": int(march_load),
                                "node_reserves": int(node_reserves),
                                "node_id": target_node["node_id"]
                            },
                            character_id=int(db_c["id"]) if db_c and db_c.get("id") else None
                        )
                    except Exception as e_log:
                        print(f"[-] TaskLogDAO gather write error: {e_log}")
                    try:
                        from app.services.activity_stream import activity_stream
                        import asyncio as _asyncio2
                        _asyncio2.create_task(activity_stream.broadcast(dash_gather_msg, user_id=tenant_id or ""))
                    except Exception:
                        pass
                except Exception as e_tele:
                    print(f"[-] gather telemetry error: {e_tele}")
                dispatched += 1
                dispatched_count += 1
                queue_confirmed = True
                await asyncio.sleep(1.4) # Rate-limit: 1.4s sleep between dispatch packets
                break
            elif error_max_queues:
                print(f"[ENGINE] Maximum march queues reached for this character (code 164). All available queues deployed!")
                break
            elif error_135:
                cross_135_streak += 1
                node_135_count += 1
                print(f"[-] Commander {cmd_display} rejected (Error 135: busy/unowned).")
                failed_heroes_session.add(primary_cmd)
                if sec_cmd:
                    failed_heroes_session.add(sec_cmd)
                if cross_135_streak >= 4:
                    print(f"[ENGINE] Server refused {cross_135_streak} dispatches in a row (135) across different commanders/nodes - "
                          f"account-level refusal, not commander state. Stopping run honestly; will retry next cycle.")
                    server_busy_abort = True
                    target_dispatches = dispatched_count
                    break
                if node_135_count >= 2:
                    # Two different commanders refused on the SAME node: the
                    # node/queue (not the commanders) is the problem. Blacklist
                    # it, release this attempt's commanders back to the pool,
                    # and move to the next node.
                    print(f"[-] Node #{target_node['node_id']} refused 135 twice - blacklisting node, trying next node...")
                    failed_nodes_session.add(target_node["node_id"])
                    failed_heroes_session.discard(primary_cmd)
                    if sec_cmd:
                        failed_heroes_session.discard(sec_cmd)
                    error_155_flag = True
                    break
                print(f"[-] Retrying SAME node with next candidate...")
                await asyncio.sleep(0.4)
                continue
            elif error_155 or error_node:
                code_str = ack_code_last if ack_code_last is not None else "155/node"
                print(f"[-] Node #{target_node['node_id']} rejected (Error {code_str}: occupied/invalid or commander overflow). Blacklisting node...")
                failed_nodes_session.add(target_node["node_id"])
                if sec_cmd:
                    print(f"[-] Dual-commander {cmd_display} rejected (Error {code_str}). Blacklisting secondary commander #{sec_cmd} to allow primary to deploy solo...")
                    failed_heroes_session.add(sec_cmd)
                cmd_155_rejections[primary_cmd] = cmd_155_rejections.get(primary_cmd, 0) + 1
                if cmd_155_rejections[primary_cmd] >= 6 and not sec_cmd:
                    print(f"[-] Commander {cmd_display} rejected across {cmd_155_rejections[primary_cmd]} nodes (Error {code_str}). Marking commander as busy/unavailable for this session.")
                    failed_heroes_session.add(primary_cmd)
                error_155_flag = error_155
                error_node_flag = error_node
                break
            else:
                print(f"[-] Commander {cmd_display} dispatch not confirmed (code={ack_code_last}). Retrying SAME node with next candidate...")
                failed_heroes_session.add(primary_cmd)
                if sec_cmd:
                    failed_heroes_session.add(sec_cmd)
                await asyncio.sleep(0.4)
                continue
        if error_max_queues:
            print(f"[ENGINE] Halting dispatch loop — governor capacity reached.")
            break
        if server_busy_abort:
            break
        if key_missing_abort:
            break
        if not queue_confirmed:
            if error_155_flag or error_node_flag:
                continue
            if candidate_allocations and target_node["node_id"] not in failed_nodes_session:
                print(f"[ENGINE] All commander candidates rejected on Node #{target_node['node_id']}. Blacklisting node and retrying queue.")
                failed_nodes_session.add(target_node["node_id"])
                continue


    print("\n" + "=" * 65)
    print(f"  [SUMMARY] Dispatched {dispatched} new march(es) | Active Marches: {len(active_marches)}/{account_max_queues}")
    print(f"  Available City Army: {total_avail_soldiers:,} soldiers remaining")
    print("=" * 65)

    save_gather_status(active_marches, total_avail_soldiers, dispatched_details)
    writer.close()
    await writer.wait_closed()
    _reason = "completed" if dispatched > 0 else ("all_queues_busy" if len(active_marches) >= account_max_queues else "no_eligible_nodes")
    if server_busy_abort and dispatched == 0:
        _reason = "server_busy_135"
    if key_missing_abort and dispatched == 0:
        _reason = "no_inspect_key"
    return {
        "success": dispatched > 0 or len(active_marches) > 0,
        "dispatched_count": dispatched,
        "active_marches_count": len(active_marches),
        "max_marches": account_max_queues,
        "free_queues": max(0, account_max_queues - len(active_marches)),
        "reason": _reason,
        "dispatches": dispatched_details,
        "dispatched_details": dispatched_details
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Headless Gather Engine")
    parser.add_argument("targets", nargs="?", default="food,wood,stone", help="Comma-separated resource targets")
    parser.add_argument("level", nargs="?", type=int, default=0, help="Target resource node level (default: 0 = highest available)")
    parser.add_argument("--level-mode", choices=["exact", "max", "min", "any"], default="any", help="Level filter constraint")
    parser.add_argument("--target-role", "--role-id", dest="target_role", type=int, default=None, help="Character Role ID")
    parser.add_argument("--kingdom", "--kingdom-id", dest="kingdom_id", type=int, default=None, help="Kingdom Server ID")
    parser.add_argument("--city-pos", dest="city_pos", default=None, help="City position as X,Y")
    parser.add_argument("--only-finishable", action="store_true", help="Only target nodes current army capacity can fully drain")
    parser.add_argument("--skip-partially", action="store_true", help="Skip nodes that have already been partially gathered")
    args = parser.parse_args()

    t_args = [t.strip() for t in args.targets.split(",") if t.strip()] if args.targets else ["food", "wood", "stone"]
    cpos = None
    if args.city_pos:
        parts = args.city_pos.split(",")
        cpos = (float(parts[0]), float(parts[1]))

    asyncio.run(execute_smart_gather(
        march_targets=t_args,
        target_level=args.level,
        level_mode=args.level_mode,
        role_id=args.target_role,
        kingdom_id=args.kingdom_id,
        city_pos=cpos,
        only_finishable=args.only_finishable,
        skip_partially=args.skip_partially
    ))
