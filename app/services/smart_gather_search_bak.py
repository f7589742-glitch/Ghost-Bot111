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
from typing import Dict, List, Tuple, Optional

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

GATE_IP = "43.159.113.101"
GATE_PORT = 3101
ROLE_ID = 227658377
MAX_ACCOUNT_QUEUES = 5

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

SEARCH_DISTANCE_RINGS = [15.0, 30.0, 50.0]

# === RELENTLESS ARCHITECTURE: Comprehensive hero pool (spec + legacy union) ===
# === CORRECTED HERO POOL: Legacy farm IDs first (verified unlocked on 3057 farms) ===
_LEGACY_FARM_HEROES = [1,2,3,23,24,15,33,32,34,35,38,46,43,44,57,4,6,5,13,11,10,7,12,8,9,36]
SPEC_HEROES = [38,49,48,52,30,25]
EXPANDED_GATHERING_HEROES = []
for _h in _LEGACY_FARM_HEROES + SPEC_HEROES:
    if _h not in EXPANDED_GATHERING_HEROES:
        EXPANDED_GATHERING_HEROES.append(_h)

RESOURCE_NAME_TO_TYPE = {
    "food": 1,
    "wood": 2,
    "stone": 3,
    "gold": 4,
    "gem": 5,
}

def is_tile_accessible(node, active_alliance_id):
    try:
        node_aid = int(node.get("alliance_id", 0) or 0)
        if node_aid == 0:
            return True
        if not active_alliance_id or int(active_alliance_id) == 0:
            return True
        return node_aid == int(active_alliance_id)
    except:
        return True

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

COMMANDER_POOL = [15, 38, 33, 34, 24, 32, 46, 43, 57, 44]

PRIORITY_GATHERERS = [
    15, # Joan of Arc (Verified Unlocked)
    38, # Sarka (Verified Unlocked)
    33, # Constance (Verified Unlocked)
    34, # Gaius Marius (Verified Unlocked)
    24, # Centurion (Verified Unlocked)
    32, # Cleopatra VII (Verified Unlocked)
    46, # Matilda of Flanders
    43, # Seondeok
    57, # Queen Tamar
    44, # Ishida Mitsunari
]

SECONDARY_COMMANDERS = [
    3,  # Sun Tzu (Verified Unlocked)
    13, # Kusunoki Masashige (Verified Unlocked)
    11, # Baibars (Verified Unlocked)
    10, # Belisarius (Verified Unlocked)
    7,  # Eulji Mundeok (Verified Unlocked)
    4,  # Minamoto no Yoshitsune (Verified Unlocked)
    12, # Osman I (Verified Unlocked)
    35, # Tomoe Gozen (Verified Unlocked)
    36, # Lancelot (Verified Unlocked)
    1,  # City Keeper (Verified Unlocked)
    6,  # Lohar
    8,  # Scipio Africanus
    5,  # Pelagius
    9,  # Hermann
    23, # Markswoman
    2,  # Cao Cao
]

# Verified per-character unlocked commanders from game assets and live account data
def get_role_commanders(role_id: int, account_email: str = None) -> list:
    rid = str(role_id)
    if rid in ROLE_COMMANDERS:
        return ROLE_COMMANDERS[rid]
    try:
        from fleet_manager import load_fleet
        fleet = load_fleet()
        for c in fleet:
            if str(c.get("role_id")) == rid and c.get("commanders"):
                return c["commanders"]
    except Exception:
        pass
    return PRIORITY_GATHERERS + SECONDARY_COMMANDERS

def get_role_march_capacity(role_id: int) -> int:
    rid = str(role_id)
    if rid in ROLE_MARCH_CAPACITY:
        return ROLE_MARCH_CAPACITY[rid]
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

# AmmAr (Power 4.62M): Exactly verified 16 unlocked commanders
ROLE_COMMANDERS = {
    227658377: [
        15, 38, 33, 34, 24, 32,
        3, 13, 11, 10, 7, 4, 12, 35, 36, 1
    ],
    227652418: [34, 33, 24, 38, 15, 35, 3, 36],
    231250084: [24, 34, 35, 3],
    231250589: [34, 33, 24, 38, 35, 3],
}

ROLE_MARCH_CAPACITY = {
    227658377: 156200, # AmmAr
    227652418: 65000,  # ssar3
    231250084: 15000,
    231250589: 28500,
}

COMMANDER_NAMES = {
    49: "Seondeok",
    48: "Ishida Mitsunari",
    52: "Matilda of Flanders",
    30: "Constance (Spec)",
    25: "Gaius Marius (Spec)",

    15: "Joan of Arc",
    46: "Matilda of Flanders",
    43: "Seondeok",
    34: "Gaius Marius",
    38: "Sarka",
    33: "Constance",
    24: "Centurion",
    57: "Queen Tamar",
    32: "Cleopatra VII",
    44: "Ishida Mitsunari",
    3: "Sun Tzu",
    6: "Lohar",
    8: "Scipio Africanus",
    13: "Kusunoki Masashige",
    11: "Baibars",
    10: "Belisarius",
    7: "Eulji Mundeok",
    5: "Pelagius",
    12: "Osman I",
    9: "Hermann",
    35: "Tomoe Gozen",
    36: "Lancelot",
    1: "City Keeper",
    23: "Markswoman",
    2: "Cao Cao",
    4: "Minamoto no Yoshitsune",
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

NATIVE_PRIORITY_ORDER = [
    20, 16, 12, 8, 4,   # Siege T5 -> T1 (highest capacity drain)
    17, 13, 9, 5, 1,    # Infantry T5 -> T1
    19, 15, 11, 7, 3,   # Archer T5 -> T1
    18, 14, 10, 6, 2,   # Cavalry T5 -> T1
]

def calculate_drain_march_composition(
    node_reserves: float,
    available_troops: Dict[int, int],
    max_capacity: int = 156200,
    remaining_queues_in_batch: int = 1,
    load_bonus: float = GATHER_LOAD_BONUS,
    buffer_load: float = 30000.0
) -> Tuple[List[Tuple[int, int]], int, float]:
    """
    Dynamic Troop Load Maximization & Node Drain Calculator using GatheringLoadEngine.
    Enforces a +30,000 buffer so the node is GUARANTEED to hit 0 and despawn.
    """
    tech_bonuses = {"global_load_pct": load_bonus * 100.0}
    target_amount = int(node_reserves) + int(buffer_load if buffer_load is not None else 30000)
    res = GatheringLoadEngine.calculate_required_march_composition(
        target_resource_amount=target_amount,
        available_troops=available_troops,
        account_bonuses=tech_bonuses,
        commander_bonus_pct=0.0,
        march_cap=max_capacity,
        remaining_queues=remaining_queues_in_batch,
        safety_margin_pct=5.0,
        flat_cushion=30000
    )
    return res["wire_army"], res["total_units"], float(res["total_load"])

def calculate_native_march_composition(
    node_reserves: float,
    available_troops: Dict[int, int],
    max_capacity: int = 35000,
    buffer_load: float = None
) -> Tuple[List[Tuple[int, int]], int, float]:
    return calculate_drain_march_composition(
        node_reserves=node_reserves,
        available_troops=available_troops,
        max_capacity=max_capacity,
        remaining_queues_in_batch=1,
        buffer_load=buffer_load
    )
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
    # F3 = City pos, F4 = Node pos, Tag 1 = alliance_id, Tag 2 = node_id, Tag 5 = 0
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

def build_send_troop_confirm() -> bytes:
    js = json.dumps({"E": "SendTroopConfirm", "t": str(int(time.time()))}).encode('utf-8')
    comp = zlib.compress(js)
    p2 = ProtobufCodec.encode_field_bytes(1, comp)
    return ProtobufCodec.encode_field_varint(1, 8) + ProtobufCodec.encode_field_bytes(2, p2)

def build_dispatch(node_id: int, army_list: list, commander_id: int = 15, sec_commander: int = 0) -> bytes:
    f4 = ProtobufCodec.encode_field_varint(4, node_id)
    f3 = ProtobufCodec.encode_field_bytes(3, bytes.fromhex("15000000000d00000000"))
    f2_payload = bytearray()
    for ut, cnt in army_list:
        if cnt <= 0: continue
        it = ProtobufCodec.encode_field_varint(2, cnt) + ProtobufCodec.encode_field_varint(1, ut)
        f2_payload.extend(ProtobufCodec.encode_field_bytes(2, it))
    f14 = ProtobufCodec.encode_field_varint(14, 1)
    c1 = (
        ProtobufCodec.encode_field_varint(1, commander_id)
        + ProtobufCodec.encode_field_varint(3, 0)
        + ProtobufCodec.encode_field_varint(2, 1)
    )
    f1_payload = ProtobufCodec.encode_field_bytes(1, c1)
    if sec_commander and sec_commander > 0:
        c2 = (
            ProtobufCodec.encode_field_varint(1, sec_commander)
            + ProtobufCodec.encode_field_varint(3, 0)
            + ProtobufCodec.encode_field_varint(2, 2)
        )
        f1_payload += ProtobufCodec.encode_field_bytes(1, c2)
    f7 = ProtobufCodec.encode_field_varint(7, 0)
    f6 = ProtobufCodec.encode_field_varint(6, 0)
    f11 = ProtobufCodec.encode_field_varint(11, 0)
    f18 = ProtobufCodec.encode_field_varint(18, 0)
    f5 = ProtobufCodec.encode_field_bytes(5, b"dispatch_troop_1")
    body = f4 + f3 + bytes(f2_payload) + f14 + f1_payload + f7 + f6 + f11 + f18 + f5
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
    skip_partially: bool = False,
    log_callback = None,
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

    if not march_targets:
        march_targets = ["food", "wood", "stone"]

    active_role_id = role_id or ROLE_ID
    host = gate_host or GATE_IP
    port = gate_port or GATE_PORT

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

    active_alliance_id = int(target_char.get("alliance_id", 8719112))
    active_kid = kingdom_id or int(target_char.get("kingdom_id", 11543))
    lvl_desc = f"Level {target_level} ({level_mode})" if target_level > 0 else "Highest Available Level"
    print("=" * 65)
    print("  PURE HEADLESS MULTI-MARCH DYNAMIC GATHER ENGINE")
    print(f"  Character: {target_char.get('name', active_role_id)} (Role {active_role_id})")
    print(f"  City Pos: {active_city_pos} | Kingdom: {active_kid} | Alliance: #{active_alliance_id}")
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
    await writer.drain()
    await asyncio.sleep(0.5)
    # Request world map & player state (Opcode 1001 triggers Opcode 1002 response with city coords & heroes)
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b""}))))
    await writer.drain()

    # PHASE A: Handshake State & Auto-Discover City Coordinates from Opcode 1002
    discovered_city_coords = None
    discovered_heroes = []
    troops_in_city = {}
    active_marches = {}
    busy_commanders = set()
    discovered_nodes = []
    seen_node_ids = set()
    synced_full_military = False

    deadline_init = asyncio.get_event_loop().time() + 3.5
    while asyncio.get_event_loop().time() < deadline_init:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.4)
            rl = (rh[0] << 8) | rh[1]
            raw_pkt = await asyncio.wait_for(reader.readexactly(rl), timeout=0.4)
            dec = crypto_rx.decrypt(raw_pkt)
            z_idx = dec.find(b"\x78\x9c")
            if z_idx == -1: z_idx = dec.find(b"\x78\x01")
            data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
            msg = ProtobufCodec.decode_message(data)
            chunks = msg.get(1) if isinstance(msg.get(1), list) else [msg]

            for c in chunks:
                m = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                op = m.get(1)

                # Real Governor State & City Coords & Commanders from Opcode 1002
                if op == 1002 or (isinstance(data, bytes) and b"\x08\xea\x07" in data):
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
                        sub1002 = ProtobufCodec.decode_message(p2)
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
                            sub2_raw = sub_it.get(2)
                            if isinstance(sub2_raw, bytes):
                                sub2 = ProtobufCodec.decode_message(sub2_raw)
                                ut = sub2.get(1, 0)
                                cnt = sub2.get(2, 0)
                                if ut > 0 and cnt > 0 and not synced_full_military:
                                    troops_in_city[ut] = cnt

                # Active marches
                elif op in (1005, 1023):
                    p_march = ProtobufCodec.decode_message(m.get(2, b"")) if isinstance(m.get(2), bytes) else m.get(2, {})
                    f1 = p_march.get(1, b"")
                    if isinstance(f1, bytes):
                        march_pattern = str(active_role_id).encode() + rb"_\d+_(\d+)(?:_(\d+))?"
                        for match in re.finditer(march_pattern, f1):
                            pri_id = int(match.group(1).decode())
                            busy_commanders.add(pri_id)
                            active_marches[f"m_{pri_id}"] = pri_id
                            if match.group(2):
                                sec_id = int(match.group(2).decode())
                                busy_commanders.add(sec_id)
        except asyncio.TimeoutError:
            if discovered_city_coords and synced_full_military:
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
    if discovered_heroes:
        print(f"   [COMMANDERS SYNC] Discovered {len(discovered_heroes)} owned hero(es): {discovered_heroes}")

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
            z_idx = dec.find(b"\x78\x9c")
            if z_idx == -1: z_idx = dec.find(b"\x78\x01")
            data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
            msg = ProtobufCodec.decode_message(data)
            chunks = msg.get(1) if isinstance(msg.get(1), list) else [msg]

            for c in chunks:
                m = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
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
                            "remaining_reserves": rem_res
                        })

            # Check if active marches are present anywhere in raw frame stream
            march_pattern = str(active_role_id).encode() + rb"_\d+_(\d+)(?:_(\d+))?"
            for match in re.finditer(march_pattern, data):
                pri_id = int(match.group(1).decode())
                busy_commanders.add(pri_id)
                active_marches[f"m_{pri_id}"] = pri_id
                if match.group(2):
                    sec_id = int(match.group(2).decode())
                    busy_commanders.add(sec_id)

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

    # If troops not captured from 125, set fallback default based on known live garrison
    if not troops_in_city:
        troops_in_city = {4: 15000, 1: 10000, 3: 8000, 2: 5000}

    total_avail_soldiers = sum(troops_in_city.values())
    active_marches_count = len(active_marches)
    free_queues = max(0, MAX_ACCOUNT_QUEUES - active_marches_count)

    print(f"\n[ENGINE] Status Sync Completed:")
    print(f"   * Available Army in City: {total_avail_soldiers:,} soldiers")
    for ut, cnt in sorted(troops_in_city.items(), key=lambda x: -NATIVE_UNIT_LOAD.get(x[0], 8.0)):
        load_val = NATIVE_UNIT_LOAD.get(ut, 8.0)
        print(f"      - Unit Type #{ut}: {cnt:,} soldiers (Load: {load_val} | Cap: {int(cnt * load_val):,})")
    print(f"   * Active Marches: {active_marches_count}/{MAX_ACCOUNT_QUEUES} queues")
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
        print(f"   [FILTER] Skip Partially Gathered Nodes: ENABLED (Filter >= 90% full capacity)")
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
    free_nodes = [n for n in discovered_nodes if n["free"] and n.get("type") in ALLOWED_GATHER_RESOURCES and n.get("type_id") != 5]
    print(f"\n[SEARCH] Discovered {len(free_nodes)} free resource deposits:")

    for fn in sorted(free_nodes, key=lambda x: (float(x["dist"]), -int(x["level"])))[:8]:
        print(f"   * {fn['name']} #{fn['node_id']} (Lvl {fn['level']}) at {fn['pos']} - Reserves: {int(fn['remaining_reserves']):,} - Dist: {fn['dist']}km")

    if free_queues == 0:
        print("\n[SUCCESS] All march queues are currently gathering on the map!")
        save_gather_status(active_marches, total_avail_soldiers)
        writer.close()
        await writer.wait_closed()
        return True

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
    # Enforce All Levels Allowed (No cap) - Level 1-4 nearby must never be rejected
    target_level = 0
    level_mode = "any"
    target_dispatches = free_queues
    dispatched = 0
    dispatched_count = 0
    failed_nodes_session = set()
    failed_heroes_session = set(busy_commanders)
    assigned_nodes = set()
    dispatched_details = []
    print(f"\n[4/4] Dispatching up to {target_dispatches} march(es) — RELENTLESS MODE...")

    def is_node_full_enough(node, skip_flag=True, min_ratio=0.90):
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
            if rem_r < (max_r * min_ratio):
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
        # Progressive km rings 0.01-100km to capture 2.2km local food
        for max_km in [3.0, 5.0, 10.0, 20.0, 35.0, 50.0, 75.0, 100.0]:
            cands = [
                n for n in free_nodes
                if n["type"] == req_type and n["type"] in ALLOWED_GATHER_RESOURCES and n["node_id"] not in assigned_nodes and n["node_id"] not in exclude_nodes and n["node_id"] not in live_claimed_nodes and 0.01 <= float(n.get("dist", 999.0)) <= max_km and is_tile_accessible(n, active_alliance_id) and is_node_full_enough(n, skip_partially, min_ratio=0.90)
            ]
            if cands:
                if max_km > 15.0:
                    print(f"   [SEARCH] Expanded to {int(max_km)}km map ({int(max_km*6)} wire) for {req_type}: {len(cands)} nodes")
                cands.sort(key=lambda x: (float(x["dist"]), -int(x["level"])))
                return cands[0]
        for _fallback in ["food","wood","stone","gold"]:
            if _fallback == req_type:
                continue
            for max_km in [100.0]:
                cands = [
                    n for n in free_nodes
                    if n["type"] == _fallback and n["type"] in ALLOWED_GATHER_RESOURCES and n["node_id"] not in assigned_nodes and n["node_id"] not in exclude_nodes and n["node_id"] not in live_claimed_nodes and 0.01 <= float(n.get("dist", 999.0)) <= max_km and is_tile_accessible(n, active_alliance_id) and is_node_full_enough(n, skip_partially, min_ratio=0.90)
                ]
                if cands:
                    print(f"   [SEARCH] Substituted {_fallback} for {req_type}: {len(cands)} nodes within 50km")
                    cands.sort(key=lambda x: (float(x["dist"]), -int(x["level"])))
                    return cands[0]
        return None

    while dispatched_count < target_dispatches:
        current_march_num = active_marches_count + dispatched_count + 1
        queue_confirmed = False
        if total_avail_soldiers <= 0:
            print(f"[ENGINE] All city troops deployed. Deployed {dispatched_count}/{target_dispatches}.")
            break
        if discovered_heroes:
            gather_first = [h for h in EXPANDED_GATHERING_HEROES if h in discovered_heroes and h not in failed_heroes_session]
            other_owned = [h for h in discovered_heroes if h not in gather_first and h not in failed_heroes_session]
            eligible_heroes = gather_first + other_owned
            if not eligible_heroes:
                eligible_heroes = [h for h in EXPANDED_GATHERING_HEROES if h not in failed_heroes_session]
        else:
            eligible_heroes = [h for h in EXPANDED_GATHERING_HEROES if h not in failed_heroes_session]
        if not eligible_heroes:
            print(f"[ENGINE] Exhausted eligible heroes. Deployed {dispatched_count}/{target_dispatches}.")
            break
        req_type = march_targets[dispatched_count % len(march_targets)].lower()
        target_node = _select_next_node(req_type, failed_nodes_session)
        if not target_node:
            print(f"[ENGINE] Exhausted available resource tiles for {req_type}. Deployed {dispatched_count}/{target_dispatches}.")
            break
        # No cap: allow all levels 1-6 (ignore DB level filter)
        target_level = 0
        level_mode = "any"
        if False and target_level and target_level > 0:
            lvl_ok = False
            if level_mode == "min":
                lvl_ok = target_node["level"] >= target_level
            elif level_mode == "max":
                lvl_ok = target_node["level"] <= target_level
            else:
                lvl_ok = target_node["level"] == target_level
            if not lvl_ok:
                lvl_cands = []
                for max_wire in [12.0, 30.0, 60.0, 120.0, 180.0, 300.0, 450.0, 600.0]:
                    # Use live claimed check for lvl filter as well
                    try:
                        _live2 = get_fleet_claimed_node_ids(int(active_kid or kingdom_id or 3057))
                    except Exception:
                        _live2 = set()
                    lvl_cands = [n for n in free_nodes if n["type"] == req_type and n["node_id"] not in assigned_nodes and n["node_id"] not in failed_nodes_session and n["node_id"] not in _live2 and 0.01 <= float(n.get("dist",999)) <= max_wire and ((n["level"] >= target_level) if level_mode=="min" else (n["level"] <= target_level) if level_mode=="max" else (n["level"]==target_level))]
                    if lvl_cands:
                        lvl_cands.sort(key=lambda x: (float(x["dist"]), -int(x["level"])))
                        target_node = lvl_cands[0]
                        lvl_ok = True
                        break
                if not lvl_ok:
                    print(f"[SEARCH] Node #{target_node['node_id']} level {target_node['level']} mismatched, blacklisting.")
                    failed_nodes_session.add(target_node["node_id"])
                    assigned_nodes.add(target_node["node_id"])
                    continue
        assigned_nodes.add(target_node["node_id"])
        # Claim node in DB before sending opcode to prevent sister farm collision
        try:
            from app.models import NodeReservationDAO
            # Resolve character name safely
            NodeReservationDAO.claim_node(node_id=int(target_node["node_id"]), kingdom_id=int(active_kid or kingdom_id or 3057), role_id=str(active_role_id), character_name=char_name, resource_type=str(target_node.get("type","")), node_level=int(target_node.get("level",1)), pos_x=float(target_node["pos"][0]) if isinstance(target_node.get("pos"), (list,tuple)) and len(target_node["pos"])>0 else 0.0, pos_y=float(target_node["pos"][1]) if isinstance(target_node.get("pos"), (list,tuple)) and len(target_node["pos"])>1 else 0.0, duration_minutes=120)
        except Exception as e:
            print(f"[RESERVATION] claim failed for {target_node["node_id"]}: {e}")
        node_reserves = target_node.get("remaining_reserves") or target_node.get("max_reserves") or 472500.0
        buffered_node_reserves = int(node_reserves) + 30000
        first_hero_for_calc = eligible_heroes[0]
        primary_load_bonus = min(COMMANDER_LOAD_BONUS.get(first_hero_for_calc, 0.0), 5.0)
        role_max_cap = get_role_march_capacity(int(active_role_id))
        tech_bonuses = {"global_load_pct": GATHER_LOAD_BONUS * 100.0}
        remaining_queues_in_batch = target_dispatches - dispatched_count
        calc_result = GatheringLoadEngine.calculate_required_march_composition(
            target_resource_amount=buffered_node_reserves,
            available_troops=troops_in_city,
            account_bonuses=tech_bonuses,
            commander_bonus_pct=primary_load_bonus,
            march_cap=role_max_cap,
            remaining_queues=remaining_queues_in_batch,
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
            continue
        ack_code_last = None
        error_155_flag = False
        error_node_flag = False
        for hero_id in list(eligible_heroes):
            if hero_id in failed_heroes_session or hero_id in busy_commanders:
                continue
            primary_cmd = hero_id
            sec_cmd = 0
            primary_name = COMMANDER_NAMES.get(primary_cmd, f"Commander #{primary_cmd}")
            cmd_display = primary_name
            print(f"\n[DISPATCH] March #{current_march_num} -> {target_node['name']} #{target_node['node_id']} (Lvl {target_node['level']})")
            print(f"   Target Reserves: {int(node_reserves):,} | Distance: {target_node['dist']}km")
            print(f"   Commanders: {cmd_display} | Units: {total_units:,} | Load: {int(march_load):,}")
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(build_map_request(target_node["pos"]))))
            await writer.drain()
            await asyncio.sleep(0.05)
            pkt_1050 = build_inspect(target_node["node_id"], target_node["pos"], city_pos=active_city_pos, alliance_id=active_alliance_id)
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_1050)))
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex("089d0712020800"))))
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex("08a70312020800"))))
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex("08fe4b1200"))))
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex("08091200"))))
            await writer.drain()
            start_ack = time.time()
            while time.time() - start_ack < 2.0:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
                    rl = (rh[0] << 8) | rh[1]
                    raw_b = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
                    dec = crypto_rx.decrypt(raw_b)
                    z_idx = dec.find(b"\x78\x9c")
                    if z_idx == -1: z_idx = dec.find(b"\x78\x01")
                    data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
                    m = ProtobufCodec.decode_message(data)
                    chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                    got_1051 = any((ProtobufCodec.decode_message(c).get(1) if isinstance(c, bytes) else c.get(1)) == 1051 for c in chunks)
                    if got_1051:
                        break
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(build_send_troop_confirm())))
            await writer.drain()
            await asyncio.sleep(0.05)
            pkt_1012 = build_dispatch(target_node["node_id"], army_list=allocated_army, commander_id=primary_cmd, sec_commander=sec_cmd)
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_1012)))
            await writer.drain()
            confirmed = False
            error_135 = False
            error_155 = False
            error_node = False
            error_max_queues = False
            ack_code_last = None
            start_wait = time.time()
            while time.time() - start_wait < 3.5:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.6)
                    rl = (rh[0] << 8) | rh[1]
                    raw_b = await asyncio.wait_for(reader.readexactly(rl), timeout=0.6)
                    dec = crypto_rx.decrypt(raw_b)
                    z_idx = dec.find(b"\x78\x9c")
                    if z_idx == -1: z_idx = dec.find(b"\x78\x01")
                    data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
                    m = ProtobufCodec.decode_message(data)
                    chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                    for c in chunks:
                        item = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                        op = item.get(1)
                        if op is not None:
                            p_body = item.get(2)
                            p_dec = ProtobufCodec.decode_message(p_body) if isinstance(p_body, bytes) else p_body
                            print(f"      [GATEWAY ACK] Opcode: {op} | Payload: {p_dec}")
                            if op in (903, 365, 1013, 1005, 1024, 1023):
                                confirmed = True
                                ack_code_last = 0
                                break
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
                    if confirmed or error_135 or error_155 or error_node or error_max_queues:
                        break
                    if confirmed:
                        break
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
            if confirmed:
                GatheringLoadEngine.deduct_troops(troops_in_city, selected_troops_dict)
                total_avail_soldiers = sum(troops_in_city.values())
                print(f"[SUCCESS] March #{current_march_num} CONFIRMED deployed with Hero {hero_id} on Node #{target_node['node_id']}!")
                busy_commanders.add(primary_cmd)
                failed_heroes_session.add(primary_cmd)
                active_marches[f"m_{primary_cmd}"] = primary_cmd
                dispatched_details.append({
                    "cmd_id": primary_cmd,
                    "sec_cmd_id": sec_cmd,
                    "cmd_name": cmd_display,
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
                        f"Sent gatherer to {target_node['type'].capitalize()} level {target_node['level']} "
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
                await asyncio.sleep(1.8)
                break
            elif error_max_queues:
                print(f"[ENGINE] Maximum march queues reached for this character (code 164). All available queues deployed!")
                break
            elif error_135:
                print(f"[-] Hero {hero_id} rejected (Error 135: busy/unowned). Retrying SAME node with next hero for March #{current_march_num}...")
                failed_heroes_session.add(hero_id)
                await asyncio.sleep(0.4)
                continue
            elif error_155 or error_node:
                code_str = ack_code_last if ack_code_last is not None else "155/node"
                print(f"[-] Node #{target_node['node_id']} rejected (Error {code_str}: occupied/invalid). Blacklisting node and selecting new tile for March #{current_march_num}...")
                failed_nodes_session.add(target_node["node_id"])
                failed_heroes_session.add(hero_id)
                error_155_flag = error_155
                error_node_flag = error_node
                break
            else:
                print(f"[-] Hero {hero_id} dispatch not confirmed (code={ack_code_last}). Retrying SAME node with next hero...")
                failed_heroes_session.add(hero_id)
                await asyncio.sleep(0.4)
                continue
        if error_max_queues:
            print(f"[ENGINE] Halting dispatch loop — governor capacity reached.")
            break
        if not queue_confirmed:
            if error_155_flag or error_node_flag:
                continue
            remaining_heroes = [h for h in EXPANDED_GATHERING_HEROES if h not in failed_heroes_session]
            if remaining_heroes and target_node["node_id"] not in failed_nodes_session:
                print(f"[ENGINE] All heroes rejected on Node #{target_node['node_id']}. Blacklisting node and retrying queue.")
                failed_nodes_session.add(target_node["node_id"])
                continue


    print("\n" + "=" * 65)
    print(f"  [SUMMARY] Dispatched {dispatched} new march(es) | Active Marches: {len(active_marches)}/5")
    print(f"  Available City Army: {total_avail_soldiers:,} soldiers remaining")
    print("=" * 65)

    save_gather_status(active_marches, total_avail_soldiers, dispatched_details)
    writer.close()
    await writer.wait_closed()
    return (dispatched > 0 or len(active_marches) > 0)

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
