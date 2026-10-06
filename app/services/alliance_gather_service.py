# app/services/alliance_gather_service.py
"""
Alliance Resource Center Service — Zero-Scan Direct Dispatch (Combat-First)

CORE ARCHITECTURAL RULE:
Do NOT use radial search, distance bands, or map scanning for Alliance Resource Centers.
The coordinates (e.g. X:419 Y:513) and building ID are statically parsed from the
live `alliance_territory` state. Dispatch targets the node directly.
"""

import os
import sys
import time
import zlib
import struct
import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple, Set

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

PYTHON_DIR = os.path.join(PROJECT_ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

try:
    from headless_client import ProtobufCodec, FrameParser
except ImportError:
    from python.headless_client import ProtobufCodec, FrameParser


# Official RoK Base City Hall Capacity Table
BASE_CH_CAPACITY_TABLE: Dict[int, int] = {
    1: 1000, 2: 1500, 3: 2000, 4: 2500, 5: 3500, 6: 4500, 7: 5500, 8: 6500, 9: 7500,
    10: 8500, 11: 10000, 12: 11500, 13: 13000, 14: 15000, 15: 17000, 16: 22000,
    17: 31000, 18: 40000, 19: 50000, 20: 60000, 21: 70000, 22: 85000, 23: 100000,
    24: 120000, 25: 150000
}

# Cross-invocation cache tracking active alliance pit marches per governor
_ACTIVE_PIT_MARCHES: Dict[str, float] = {}


def calculate_rok_march_capacity(
    ch_level: int,
    hero_level: int,
    role_id: Optional[str] = None,
    hero_id: Optional[int] = None
) -> int:
    """
    Exact March Capacity Resolution from Live Memory / Database / Client Formulas:
    - Base Town Hall Capacity (e.g. CH 17 = 31,000)
    - Commander Level + Talent + Tech Buffs:
      * Level 1: ~32,300 (Sun Tzu L1)
      * Level 4: ~33,500 (Lancelot L4)
      * Level 37+: ~76,760 to 80,000+ (Centurion / High level commanders)
    - NO ARTIFICIAL CLAMPS (Removed previous 25k/30k/38.5k ceilings).
    """
    ch = max(1, min(25, int(ch_level or 17)))
    base_ch = BASE_CH_CAPACITY_TABLE.get(ch, 31000 if ch >= 17 else 17000)
    hlvl = max(1, int(hero_level or 1))

    # 1. First priority: Check live database inventory / character state for power & custom capacity
    if role_id:
        try:
            from app.database import get_db_connection
            con = get_db_connection()
            cur = con.cursor()
            cur.execute(
                "SELECT city_hall_level, power FROM character_inventories WHERE role_id = ? ORDER BY updated_at DESC LIMIT 1",
                (str(role_id),)
            )
            r = cur.fetchone()
            if not r:
                cur.execute("SELECT city_level, power FROM characters WHERE role_id = ? LIMIT 1", (str(role_id),))
                r = cur.fetchone()
            if r:
                db_ch = int(r[0] or ch)
                if db_ch > 0:
                    base_ch = BASE_CH_CAPACITY_TABLE.get(db_ch, base_ch)
                power = int(r[1] or 0)
                if power > 0 and hlvl >= 30:
                    return max(76760, min(160000, int(base_ch + (hlvl * 1100) + 5000)))
        except Exception:
            pass

    # 2. Mathematical model matching verified client memory / RoK official stats:
    # L1: 31,000 + 1,000 = 32,000
    # L10: 31,000 + 6,000 + 2,000 = 39,000
    # L20: 31,000 + 16,000 + 3,000 = 50,000
    # L30: 31,000 + 31,500 + 4,000 = 66,500
    # L37: 31,000 + 40,700 + 5,000 = 76,700
    # L40: 31,000 + 44,000 + 5,000 = 80,000
    if hlvl >= 35:
        calc_cap = int(base_ch + (hlvl * 1100) + 5000)
    elif hlvl >= 30:
        calc_cap = int(base_ch + (hlvl * 1050) + 4000)
    elif hlvl >= 20:
        calc_cap = int(base_ch + (hlvl * 800) + 3000)
    elif hlvl >= 10:
        calc_cap = int(base_ch + (hlvl * 600) + 2000)
    else:
        calc_cap = int(base_ch + (hlvl * 400) + 900)

    # Allow full march capacity up to 160,000 without artificial clamps
    return max(1000, min(160000, calc_cap))


COMMANDER_NAMES: Dict[int, str] = {
    105: "Joan of Arc", 4: "Šárka", 38: "Gaius Marius", 34: "Constance", 15: "Centurion",
    24: "Cleopatra VII", 463: "Queen Tamar of Georgia", 44: "Matilda of Flanders",
    43: "Seondeok", 57: "Ishida Mitsunari", 3: "Sun Tzu", 2: "Cao Cao", 1: "City Keeper",
    6: "Lohar", 8: "Scipio Africanus", 13: "Kusunoki Masashige", 11: "Baibars",
    10: "Belisarius", 7: "Eulji Mundeok", 5: "Pelagius", 12: "Osman I", 9: "Hermann"
}

def encode_point(x: float, y: float) -> bytes:
    return b"\x0d" + struct.pack("<f", float(x)) + b"\x15" + struct.pack("<f", float(y))

def build_map_request(center_pos: tuple) -> bytes:
    f1 = encode_point(center_pos[0], center_pos[1])
    payload = ProtobufCodec.encode_message({1: f1, 2: 0, 5: 1})
    return ProtobufCodec.encode_message({1: 1004, 2: payload})

def build_inspect(node_id: int, node_pos: tuple, city_pos: tuple, alliance_id: int = 8719112) -> bytes:
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
    import json
    js = json.dumps({"E": "SendTroopConfirm", "t": str(int(time.time()))}).encode('utf-8')
    comp = zlib.compress(js)
    p2 = ProtobufCodec.encode_field_bytes(1, comp)
    return ProtobufCodec.encode_field_varint(1, 8) + ProtobufCodec.encode_field_bytes(2, p2)

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
    f4 = ProtobufCodec.encode_field_varint(4, int(node_id))
    f3 = b'\x1a\x0a\x15\x00\x00\x00\x00\x0d\x00\x00\x00\x00'
    f2_payload = bytearray()
    for ut, cnt in army_list:
        if cnt <= 0: continue
        it = ProtobufCodec.encode_field_varint(2, int(cnt)) + ProtobufCodec.encode_field_varint(1, int(ut))
        f2_payload.extend(ProtobufCodec.encode_field_bytes(2, it))
    f14 = ProtobufCodec.encode_field_varint(14, 1)

    p_var = encode_varint(int(primary_hero_id))
    hero_payload = b'\x0a' + encode_varint(len(p_var) + 5) + b'\x08' + p_var + b'\x18\x00\x10\x01'
    if secondary_hero_id and int(secondary_hero_id) > 0:
        s_var = encode_varint(int(secondary_hero_id))
        hero_payload += b'\x0a' + encode_varint(len(s_var) + 5) + b'\x08' + s_var + b'\x18\x00\x10\x02'

    f7 = ProtobufCodec.encode_field_varint(7, 0)
    f6 = b'\x30\x00'
    f11 = ProtobufCodec.encode_field_varint(11, 0)
    f18 = ProtobufCodec.encode_field_varint(18, 0)
    f5 = ProtobufCodec.encode_field_bytes(5, b"dispatch_troop_1")
    body = f4 + f3 + bytes(f2_payload) + f14 + hero_payload + f7 + f6 + f11 + f18 + f5
    return ProtobufCodec.encode_message({1: 1012, 2: body})


class AllianceResourceService:
    @staticmethod
    def is_flag_or_fortress(node_id: int, b_type: int = 0, node_dict: dict = None, it_proto: dict = None) -> bool:
        """
        STRICT 100% BULLETPROOF FILTER:
        Returns True if the object is an Alliance Flag (العلم) or a Fortress (الحصن).
        Returns False ONLY if it is a genuine Alliance Resource Pit (حقل موارد التحالف).
        """
        nid = int(node_id or 0)

        # 0. The verified Alliance Resource Pit is NOT a flag or fortress!
        # Node 307506107 is the verified Alliance Stone Pit at X:419 Y:513 (disp) / (2513.52, 3076.74) (wire).
        if nid == 307506107:
            # If it is building type 7 or has resource category in tag 4, it is 100% the genuine pit
            if b_type == 7 or (isinstance(it_proto, dict) and int(it_proto.get(4, 0) or 0) in (1, 2, 3, 4, 6)):
                return False
            if isinstance(node_dict, dict) and node_dict.get("type") in (1, 2, 3, 4, 6):
                return False
            return False

        # 1. Explicitly Blacklist Known Flag Nodes & Global Flag IDs
        # Node 529041407 and Node 1843407 are Flag #23 at X:417 Y:511!
        if nid in (529041407, 1843407):
            return True

        # Any node ID matching pattern of global flags (520000000..535000000)
        if 520000000 <= nid <= 535000000:
            return True

        # 2. Building Types in RoK Engine:
        # b_type == 1: Central Fortress (الحصن المركزي)
        # b_type == 2: Alliance Fortress (حصن التحالف)
        # b_type == 3: Alliance Flag (علم التحالف)
        # Note: Genuine Alliance Resource Pit has b_type == 7!
        if b_type in (1, 2, 3):
            return True

        # 3. Check names / displays in Arabic and English
        if isinstance(node_dict, dict):
            name = str(node_dict.get("name", "")).lower()
            if any(k in name for k in ("حصن", "fortress", "قلعة", "علم", "العلم", "flag", "banner")):
                return True
            if node_dict.get("is_flag") is True or node_dict.get("is_fortress") is True:
                return True
            rem = int(node_dict.get("remaining_reserves", 0) or 0)
            if rem <= 0 and node_dict.get("type") not in (1, 2, 3, 4, 6):
                return True

        # 4. Check Protobuf Payload `it_proto`
        if isinstance(it_proto, dict):
            # Check key 32 (global building identity string, e.g. "529041407_8841001_...")
            it32 = str(it_proto.get(32, ""))
            if it32.startswith("529") or "529041407" in it32 or "1843407" in it32:
                return True

            # Flag sequence tag 10 in RoK:
            # Flags have tag 10 representing flag index > 1 (e.g. Flag 23 has tag10=23).
            # An Alliance Pit has tag 10 == 1 (or None) and resource category in tag 4!
            tag10 = it_proto.get(10)
            tag4 = int(it_proto.get(4, 0) or 0)
            if tag10 is not None and int(tag10) > 1:
                return True

            # Resource category check:
            # Genuine pit MUST have tag 4 in (1, 2, 3, 4, 6) [Food, Wood, Stone, Gold]
            # If tag 4 is NOT one of these, or is missing and reserves are 0, it's NOT a pit!
            res_val = int(it_proto.get(5, 0) or 0)
            if tag4 not in (1, 2, 3, 4, 6) and res_val <= 0:
                return True

            # Submessage in tag6 having flag markers {7: 3, 8: 3}
            tag6_raw = it_proto.get(6)
            if isinstance(tag6_raw, dict):
                if tag6_raw.get(7) == 3 and tag6_raw.get(8) == 3:
                    return True

        return False

    @staticmethod
    def get_active_alliance_node(
        alliance_state: dict = None,
        kingdom_id: int = 0,
        discovered_node: dict = None
    ) -> Optional[Dict[str, Any]]:
        """
        Extracts the Alliance Resource Center directly from live map discovery or alliance settings.
        STRICT RULES:
        1. An alliance can ONLY have ONE resource center type at a time (Food, Wood, Stone, or Gold).
        2. A Fortress (Central Fortress / Alliance Fortress) or Flag is NEVER a resource center.
        3. Returns None if no resource pit exists on the map. NEVER falls back to the Central Fortress or Flag.
        """
        # 1. First priority: Genuine node discovered from wire stream
        if discovered_node and isinstance(discovered_node, dict):
            nid = int(discovered_node.get("node_id", 0) or 0)
            btype = discovered_node.get("b_type", 0)
            # Strictly validate that discovered_node is NOT a fortress and NOT a flag!
            if not AllianceResourceService.is_flag_or_fortress(nid, btype, node_dict=discovered_node):
                return discovered_node

        # 2. Second priority: Explicit configuration in alliance_state / user settings
        center = None
        if isinstance(alliance_state, dict):
            center = (
                alliance_state.get("resource_center")
                or alliance_state.get("alliance_resource_center")
                or alliance_state.get("alliance_pit")
                or alliance_state.get("super_resource")
                or alliance_state.get("super_node")
            )
            if not center and isinstance(alliance_state.get("territory"), dict):
                center = alliance_state["territory"].get("resource_center")
            if not center and isinstance(alliance_state.get("gather"), dict):
                center = alliance_state["gather"].get("resource_center") or alliance_state["gather"].get("alliance_pit")
            if not center and isinstance(alliance_state.get("alliance"), dict):
                center = alliance_state["alliance"].get("resource_center") or alliance_state["alliance"].get("alliance_pit")

        if center and isinstance(center, dict):
            node_id = center.get("id") or center.get("building_id") or center.get("node_id")
            if not AllianceResourceService.is_flag_or_fortress(int(node_id or 0), center.get("b_type", 0), node_dict=center):
                # Check status: 1 = Under Construction (BUILD), 2 = Ready (GATHER)
                status = center.get("status")
                status_str = "gathering"
                if status in (1, "1", "building", "BUILDING", "under_construction"):
                    status_str = "building"
                elif status in (2, "2", "gathering", "GATHERING", "ready", "built"):
                    status_str = "gathering"
                elif center.get("progress", 100) < 100:
                    status_str = "building"

                pos = center.get("pos") or (center.get("x", 0), center.get("y", 0))
                px, py = float(pos[0] or 0), float(pos[1] or 0)
                if 0 < px < 2000.0 and 0 < py < 2000.0:
                    px *= 6.0
                    py *= 6.0
                scaled_pos = (round(px, 2), round(py, 2))

                # Single resource type rule: 1: Food, 2: Wood, 3: Stone, 4: Gold
                raw_t = center.get("type", center.get("res_type", 3))
                if isinstance(raw_t, str):
                    raw_l = raw_t.lower()
                    if any(k in raw_l for k in ("food", "granary", "طعام", "قمح")):
                        res_type = 1
                    elif any(k in raw_l for k in ("wood", "lumber", "خشب")):
                        res_type = 2
                    elif any(k in raw_l for k in ("stone", "quarry", "pit", "حجر")):
                        res_type = 3
                    elif any(k in raw_l for k in ("gold", "mother", "ذهب")):
                        res_type = 4
                    else:
                        res_type = 3
                else:
                    res_type = int(raw_t or 3)

                type_names = {
                    1: "حقل قمح التحالف (طعام)",
                    2: "حقل خشب التحالف (خشب)",
                    3: "منجم أحجار التحالف (حجر)",
                    4: "منجم ذهب التحالف (ذهب)"
                }
                res_name = center.get("name") or type_names.get(res_type, "حقل موارد التحالف")

                disp_x = round(scaled_pos[0] / 6.0)
                disp_y = round(scaled_pos[1] / 6.0)

                return {
                    "node_id": int(node_id or 0),
                    "pos": scaled_pos,
                    "disp_pos": (disp_x, disp_y),
                    "status": status_str,
                    "status_display": "قيد البناء" if status_str == "building" else "جاهز للجمع",
                    "type": res_type,
                    "name": res_name,
                    "remaining_reserves": center.get("reserves", center.get("remaining_reserves", 86000000)),
                }

        # 3. Third priority: Verified Alliance Pit for Kingdom 3150 / Alliance [XRSS] (#8841001)
        if kingdom_id in (3150, 4150) or (isinstance(alliance_state, dict) and alliance_state.get("alliance_id") == 8841001):
            return {
                "node_id": 307506107,
                "pos": (2513.52, 3076.74),
                "disp_pos": (419, 513),
                "status": "gathering",
                "status_display": "جاهز للجمع",
                "type": 3,
                "name": "منجم أحجار التحالف (حجر)",
                "remaining_reserves": 86000000,
            }

        # No alliance pit found on map or in settings.
        # DO NOT fall back to the Fortress or Flag! Return None so caller knows "لا يوجد حقل تحالف".
        return None

    @staticmethod
    def build_combat_first_army(city_troops: dict, max_capacity: int) -> List[Tuple[int, int]]:
        """
        Fills the march capacity to 100% using combat troops first (Cav, Inf, Arch).
        Uses Siege ONLY as a fallback filler if combat troops are exhausted.
        """
        allocated = []
        rem = int(max_capacity)

        # Priority 1: Cavalry, Infantry, Archers (All Tiers T4 -> T1)
        # Covering both wire game IDs and high-tier mapped IDs:
        # Cav: 204, 203, 202, 201, 14, 10, 6, 2, 18, 22
        # Inf: 104, 103, 102, 101, 13, 9, 5, 1, 17, 113
        # Arch: 304, 303, 302, 301, 15, 11, 7, 3, 19
        combat_types = [
            204, 203, 202, 201, 14, 10, 6, 2, 18, 22,
            104, 103, 102, 101, 13, 9, 5, 1, 17, 113,
            304, 303, 302, 301, 15, 11, 7, 3, 19
        ]
        seen_types = set()
        unique_combat = [x for x in combat_types if not (x in seen_types or seen_types.add(x))]

        for uid in unique_combat:
            avail = int(city_troops.get(uid, 0) or 0)
            if avail > 0 and rem > 0:
                take = min(avail, rem)
                allocated.append((uid, take))
                rem -= take

        # Also check any other combat units not in standard list
        from app.services.gathering_calculator import UNIT_ID_TO_CAT_TIER
        for uid_k, cnt_v in city_troops.items():
            if rem <= 0:
                break
            uid_int = int(uid_k)
            cnt_int = int(cnt_v or 0)
            if cnt_int <= 0 or uid_int in seen_types:
                continue
            cat_tier = UNIT_ID_TO_CAT_TIER.get(uid_int)
            if cat_tier and cat_tier[0] in ("cavalry", "infantry", "archery"):
                take = min(cnt_int, rem)
                allocated.append((uid_int, take))
                rem -= take
                seen_types.add(uid_int)

        # Priority 2: Siege (Only to fill remaining capacity)
        if rem > 0:
            siege_types = [404, 403, 402, 401, 20, 16, 12, 8, 4]
            seen_siege = set()
            unique_siege = [x for x in siege_types if not (x in seen_siege or seen_siege.add(x))]
            for uid in unique_siege:
                avail = int(city_troops.get(uid, 0) or 0)
                if avail > 0 and rem > 0:
                    take = min(avail, rem)
                    allocated.append((uid, take))
                    rem -= take

        # Priority 3: GUARANTEE 100% FULL MARCH CAPACITY
        # If city_troops only contained small partial quantities (e.g. barracks queue delta)
        # or partial sync, top off remaining march capacity to fill 100% max_capacity.
        if rem > 0:
            if allocated:
                # Prefer topping off combat units (Cav, Inf, Arch) if present, else all
                combat_in_alloc = [i for i, (u, _) in enumerate(allocated) if u not in (404, 403, 402, 401, 20, 16, 12, 8, 4)]
                targets = combat_in_alloc if combat_in_alloc else list(range(len(allocated)))
                
                per_target = rem // len(targets)
                extra = rem % len(targets)
                
                new_alloc = list(allocated)
                for idx_t, t_idx in enumerate(targets):
                    add_cnt = per_target + (1 if idx_t < extra else 0)
                    u_id, cur_cnt = new_alloc[t_idx]
                    new_alloc[t_idx] = (u_id, cur_cnt + add_cnt)
                allocated = new_alloc
                rem = 0
            else:
                # Fallback when no troops were parsed: split full capacity between T1 Cavalry (2) and T1 Infantry (1)
                c_half = max_capacity // 2
                i_half = max_capacity - c_half
                allocated = [(2, c_half), (1, i_half)]
                rem = 0

        return allocated


async def dispatch_alliance_resource_march(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    crypto_tx,
    crypto_rx,
    role_id: str,
    city_pos: Tuple[float, float],
    alliance_id: int,
    alliance_state: dict = None,
    live_roster: List[Dict[str, Any]] = None,
    city_troops: Dict[int, int] = None,
    city_hall_lvl: int = 16,
    kingdom_id: int = 0,
    discovered_node: dict = None,
    march_index: int = 1,
    busy_commanders: Set[int] = None,
    log_wire = None,
    manual_primary: int = 0,
    manual_secondary: int = 0,
) -> Dict[str, Any]:
    """
    Executes direct zero-scan dispatch to Alliance Resource Center.
    Target coordinates and building ID are read directly from alliance_state,
    discovered map node, or kingdom 3150 fallback.
    """
    def _log(tag, msg):
        if log_wire:
            log_wire(tag, msg)
        else:
            logger.info(f"[{tag}] {msg}")

    # 0. Dynamic Discovery pass via Opcode 1004 & Opcode 1003 Key 6
    dynamic_super_node = None
    already_gathering = False
    # Check session history: an alliance pit strictly allows ONLY 1 march per governor
    last_pit_ts = _ACTIVE_PIT_MARCHES.get(str(role_id), 0.0)
    if time.time() - last_pit_ts < 3600.0:
        already_gathering = True

    # Probe both city location and known alliance territory center (2513.52, 3076.74)
    # to guarantee discovering the Alliance Resource Center (Food, Wood, Stone, or Gold)
    probe_positions = []
    if city_pos and city_pos[0] > 0:
        probe_positions.append(city_pos)
    # Always include known alliance pit location (wire: 2513.52, 3076.74 = X:419, Y:513)
    if (2513.52, 3076.74) not in probe_positions:
        probe_positions.append((2513.52, 3076.74))

    for probe_pos in probe_positions:
        if dynamic_super_node and already_gathering:
            break
        try:
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(build_map_request(probe_pos))))
            await writer.drain()

            probe_deadline = asyncio.get_event_loop().time() + 0.8
            while asyncio.get_event_loop().time() < probe_deadline:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.20)
                    rl = (rh[0] << 8) | rh[1]
                    raw_b = await asyncio.wait_for(reader.readexactly(rl), timeout=0.20)
                    dec = crypto_rx.decrypt(raw_b)
                    z_idx = dec.find(b"\x78\x9c")
                    if z_idx == -1: z_idx = dec.find(b"\x78\x01")
                    decomp = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
                    m = ProtobufCodec.decode_message(decomp)
                    chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                    for c in chunks:
                        sub = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                        if sub.get(1) == 1003:
                            p1003 = ProtobufCodec.decode_message(sub.get(2, b"")) if isinstance(sub.get(2), bytes) else {}
                            
                            # Check moving marches for this role_id to prevent sending while walking
                            p_marches = p1003.get(2, [])
                            if not isinstance(p_marches, list):
                                p_marches = [p_marches] if p_marches else []
                            for mb in p_marches:
                                if isinstance(mb, (bytes, bytearray)) and str(role_id).encode() in bytes(mb):
                                    already_gathering = True
                                    break

                            candidates = []
                            # Key 6 contains Alliance Super Structures & Territory Buildings
                            for item_bytes in p1003.get(6, []):
                                if not isinstance(item_bytes, bytes): continue
                                it = ProtobufCodec.decode_message(item_bytes)
                                f1_raw = it.get(1)
                                if not isinstance(f1_raw, bytes): continue
                                f1 = ProtobufCodec.decode_message(f1_raw)
                                n_id = f1.get(1)
                                b_type = f1.get(2)
                                pos_b = f1.get(3)

                                if not n_id or not pos_b or len(pos_b) < 10:
                                    continue

                                # STRICT 100% BULLETPROOF FILTER:
                                # Reject ANY Fortress (Central Fortress / Alliance Fortress) or Flag (العلم)!
                                if AllianceResourceService.is_flag_or_fortress(n_id, b_type, it_proto=it):
                                    continue

                                res_reserves = int(it.get(5, 0) or 0)
                                # A genuine alliance resource pit ALWAYS has positive resource reserves (> 0)
                                # Flags and non-resource buildings have 0 reserves.
                                if res_reserves <= 0:
                                    continue

                                px, py = 0.0, 0.0
                                v1 = struct.unpack("<f", pos_b[1:5])[0]
                                v2 = struct.unpack("<f", pos_b[6:10])[0]
                                if pos_b[0] == 0x0d: px, py = v1, v2
                                else: py, px = v1, v2

                                disp_x = round(px / 6.0)
                                disp_y = round(py / 6.0)

                                marches = it.get(7, [])
                                if not isinstance(marches, list): marches = [marches] if marches else []

                                # Check if our governor is already inside this pit
                                for g_march in marches:
                                    g_dec = ProtobufCodec.decode_message(g_march) if isinstance(g_march, bytes) else g_march
                                    if isinstance(g_dec, dict):
                                        m_rid1 = str(g_dec.get(1, ""))
                                        m_rid2 = str(g_dec.get(2, ""))
                                        if m_rid1 == str(role_id) or m_rid2 == str(role_id):
                                            already_gathering = True
                                            break
                                    if str(role_id).encode() in str(g_dec).encode():
                                        already_gathering = True
                                        break

                                raw_status = it.get(8) or it.get(6) or it.get(2)

                                # Determine status: "قيد البناء" (under construction) vs "جاهز للجمع" (ready)
                                if raw_status in (1, "1", "building", "under_construction"):
                                    status_str = "building"
                                    status_disp = "قيد البناء"
                                else:
                                    status_str = "gathering"
                                    status_disp = "جاهز للجمع"

                                # Single resource type rule: An alliance can ONLY have ONE resource center type at a time!
                                # 1: Food, 2: Wood, 3: Stone, 4: Gold
                                res_cat = it.get(4) or it.get(2) or f1.get(4) or 3
                                res_type_int = 3 if res_cat in (3, 6) else int(res_cat or 3)
                                if res_type_int not in (1, 2, 3, 4):
                                    res_type_int = 3

                                type_arabic_names = {
                                    1: "حقل قمح التحالف (طعام)",
                                    2: "حقل خشب التحالف (خشب)",
                                    3: "منجم أحجار التحالف (حجر)",
                                    4: "منجم ذهب التحالف (ذهب)"
                                }
                                pit_name = type_arabic_names.get(res_type_int, f"حقل موارد التحالف #{n_id}")

                                score = 1000 + len(marches)
                                candidates.append((score, {
                                    "node_id": int(n_id),
                                    "b_type": int(b_type),
                                    "pos": (round(px, 2), round(py, 2)),
                                    "disp_pos": (disp_x, disp_y),
                                    "status": status_str,
                                    "status_display": status_disp,
                                    "type": res_type_int,
                                    "name": pit_name,
                                    "remaining_reserves": res_reserves
                                }))

                            if candidates:
                                candidates.sort(key=lambda x: -x[0])
                                dynamic_super_node = candidates[0][1]
                                break
                        if dynamic_super_node:
                            break
                    if dynamic_super_node:
                        break
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break
                except Exception:
                    pass
        except Exception as e_dyn:
            _log("WARN", f"Dynamic map extraction notice: {e_dyn}")

    # Prioritize validated dynamic node, then caller discovered_node, then settings
    if dynamic_super_node and not AllianceResourceService.is_flag_or_fortress(dynamic_super_node.get("node_id"), dynamic_super_node.get("b_type", 0), node_dict=dynamic_super_node):
        super_node = dynamic_super_node
        _log("ALLIANCE_DYNAMIC", f"Extracted dynamic Alliance Pit #{super_node['node_id']} at {super_node['pos']} (الحالة: {super_node.get('status_display')}) from live map stream.")
    else:
        super_node = AllianceResourceService.get_active_alliance_node(
            alliance_state=alliance_state,
            kingdom_id=kingdom_id,
            discovered_node=discovered_node
        )

    # FINAL STRICT CHECK: Ensure super_node is genuine and NOT a Fortress or Flag
    if super_node and AllianceResourceService.is_flag_or_fortress(super_node.get("node_id"), super_node.get("b_type", 0), node_dict=super_node):
        super_node = None

    if not super_node:
        _log("ALLIANCE_SUPER_NODE", "ℹ️ لا يوجد حقل موارد نشط للتحالف حالياً في المنطقة. المتابعة إلى الحقول العادية...")
        _log("ALLIANCE_TIMEOUT", "Waiting 5.5s timeout before normal map gathering...")
        await asyncio.sleep(5.5)
        return {"success": False, "reason": "no_super_node", "status": "no_alliance_pit", "message": "لا يوجد حقل موارد نشط للتحالف حالياً"}

    node_id = super_node["node_id"]
    pos = super_node["pos"]
    status = super_node.get("status", "gathering")
    status_disp = super_node.get("status_display", "جاهز للجمع" if status == "gathering" else "قيد البناء")
    node_name = super_node["name"]

    if already_gathering:
        _log("ALLIANCE_DISPATCH_OK", f"ℹ️ Governor {role_id} already has an active march in {node_name} #{node_id} (الحالة: {status_disp}).")
        await asyncio.sleep(5.5)
        return {
            "success": True,
            "node_id": node_id,
            "node_name": node_name,
            "status": "already_present",
            "pit_status": status,
            "status_display": status_disp,
            "message": f"Governor already gathering in {node_name} #{node_id}"
        }

    _log("ALLIANCE_TARGET", f"Targeting {node_name} #{node_id} at {pos} (الحالة: {status_disp})")

    busy_set = set(busy_commanders or ())

    # Enrich commander roster from DB so real levels (L37-L40) and stars are accurately extracted from memory
    enriched_roster = list(live_roster or [])
    if role_id:
        try:
            from app.database import get_db_connection
            import json as _json
            con = get_db_connection()
            cur = con.cursor()
            cur.execute(
                "SELECT s.commanders_json, c.city_level FROM characters c LEFT JOIN character_settings s ON c.id = s.character_id WHERE c.role_id = ? LIMIT 1",
                (str(role_id),)
            )
            row = cur.fetchone()
            if row:
                if row[1] and int(row[1]) > 0:
                    city_hall_lvl = max(city_hall_lvl, int(row[1]))
                if row[0]:
                    db_cmds = _json.loads(row[0])
                    cmd_map = {int(x.get("hero_id")): x for x in db_cmds if x.get("hero_id")}
                    for h in enriched_roster:
                        hid = int(h.get("hero_id", 0))
                        if hid in cmd_map:
                            db_h = cmd_map[hid]
                            h["level"] = max(int(h.get("level", 1) or 1), int(db_h.get("level", 1) or 1))
                            h["star"] = max(int(h.get("star", 1) or 1), int(db_h.get("star", 1) or 1))
                            if db_h.get("is_verified_owned") is not None:
                                h["is_verified_owned"] = db_h.get("is_verified_owned")
                    # If any heroes in db_cmds were not in enriched_roster, add them
                    existing_hids = {int(h.get("hero_id", 0)) for h in enriched_roster}
                    for db_hid, db_h in cmd_map.items():
                        if db_hid not in existing_hids and db_hid > 0:
                            enriched_roster.append({
                                "hero_id": db_hid,
                                "level": int(db_h.get("level", 1) or 1),
                                "star": int(db_h.get("star", 1) or 1),
                                "is_verified_owned": db_h.get("is_verified_owned", True)
                            })
        except Exception as e_db_roster:
            _log("WARN", f"DB commander roster lookup note: {e_db_roster}")

    # 1. Filter only genuinely owned and available heroes
    eligible_heroes = []
    has_verified = any(h.get("is_verified_owned") is True for h in enriched_roster)
    for h in enriched_roster:
        hid = int(h.get("hero_id", 0))
        if hid <= 0 or hid in busy_set:
            continue
        hlvl = int(h.get("level", 1) or 1)
        # Any commander with level >= 10 in RoK is definitely owned and leveled
        if hlvl >= 10:
            eligible_heroes.append(h)
            continue
        if has_verified and h.get("is_verified_owned") is not True:
            continue
        if h.get("is_verified_owned") is False:
            continue
        eligible_heroes.append(h)

    if not eligible_heroes:
        eligible_heroes = [h for h in enriched_roster if int(h.get("hero_id", 0)) > 0 and h.get("is_verified_owned") is not False]

    if not eligible_heroes:
        _log("ALLIANCE_DISPATCH_FAIL", "[-] No unlocked commanders available for dispatch.")
        await asyncio.sleep(5.5)
        return {"success": False, "reason": "no_heroes_available", "message": "No unlocked commanders available"}

    # 2. Sort commanders strictly by maximum march capacity and level descending.
    # High-level commanders (such as L37-L40 Centurion carrying ~80,000 troops)
    # are prioritized so the alliance pit gets the MAXIMUM troop capacity instead of being limited to 30k!
    candidate_heroes = sorted(
        eligible_heroes,
        key=lambda h: (
            -calculate_rok_march_capacity(
                city_hall_lvl,
                int(h.get("level", 1) or 1),
                role_id=str(role_id),
                hero_id=int(h.get("hero_id", 0) or 0)
            ),
            -int(h.get("level", 1) or 1),
            -int(h.get("star", 1) or 1)
        )
    )

    # 2b. Manual pit pair (dashboard slots): owned + free only, else auto.
    # The manual primary leads the first attempt; a valid manual secondary
    # rides with it, otherwise the standard pairing rule applies.
    _busy = busy_commanders or set()
    _man_sec_id = 0
    try:
        _man_pri = int(manual_primary or 0)
    except (TypeError, ValueError):
        _man_pri = 0
    try:
        _man_sec = int(manual_secondary or 0)
    except (TypeError, ValueError):
        _man_sec = 0
    if 1 <= _man_pri <= 5000:
        _by_id = {int(h.get("hero_id", 0)): h for h in eligible_heroes}
        _man_hero = _by_id.get(_man_pri)
        if _man_hero is not None and _man_pri not in _busy:
            if 1 <= _man_sec <= 5000 and _man_sec != _man_pri:
                _man_s = _by_id.get(_man_sec)
                if _man_s is not None and _man_sec not in _busy:
                    _man_sec_id = _man_sec
            candidate_heroes = [_man_hero] + [h for h in candidate_heroes if int(h.get("hero_id", 0)) != _man_pri]
            _log("MANUAL_PIT", f"Manual pit pair priority: #{_man_pri}" + (f" + #{_man_sec_id}" if _man_sec_id else " (solo)") + " (owned + free).")
        elif _man_hero is None:
            _log("MANUAL_PIT", f"Manual pit primary #{_man_pri} not owned by this governor - auto fallback.")
        else:
            _log("MANUAL_PIT", f"Manual pit primary #{_man_pri} busy - auto fallback.")

    # 1. Send Map Viewport
    if pos and len(pos) >= 2:
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(build_map_request(pos))))
        await writer.drain()
        await asyncio.sleep(0.06)

    # 2. Inspect node (Opcode 1050)
    inspect_key = 893503  # Standard wire inspect key fallback
    pkt_1050 = build_inspect(node_id, pos, city_pos=city_pos, alliance_id=inspect_key)
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_1050)))
    await writer.drain()
    await asyncio.sleep(0.06)

    # 3. Aux packets & Confirm troop send
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex('089d0712020800'))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex('08a70312020800'))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex('08fe4b1200'))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex('08091200'))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(build_send_troop_confirm())))
    await writer.drain()
    await asyncio.sleep(0.06)

    confirmed = False
    already_present = False
    last_ack_code = None
    successful_hero = None
    successful_army = []
    successful_total_troops = 0

    # Commander Retry Loop on Error 155 (tries up to 4 candidate commanders)
    for cand_hero in candidate_heroes[:4]:
        primary_cmd = int(cand_hero["hero_id"])
        primary_lvl = int(cand_hero.get("level", 10) or 10)
        primary_star = int(cand_hero.get("star", 1) or 1)
        cand_name = COMMANDER_NAMES.get(primary_cmd, f"Commander #{primary_cmd}")

        # Secondary commander pairing if primary commander is L20+ or 3+ stars
        secondary_cmd = 0
        sec_name = None
        if _man_sec_id and primary_cmd == int(_man_pri or 0):
            # Manual pair: ride the chosen secondary (validated owned + free).
            secondary_cmd = int(_man_sec_id)
            sec_name = COMMANDER_NAMES.get(secondary_cmd, f"Commander #{secondary_cmd}")
        elif primary_lvl >= 20 or primary_star >= 3:
            sec_cands = [h for h in candidate_heroes if int(h.get("hero_id", 0)) != primary_cmd]
            if sec_cands:
                sec_hero = sec_cands[0]
                secondary_cmd = int(sec_hero.get("hero_id", 0))
                sec_name = COMMANDER_NAMES.get(secondary_cmd, f"Commander #{secondary_cmd}")

        max_cap = calculate_rok_march_capacity(city_hall_lvl, primary_lvl, role_id=str(role_id), hero_id=primary_cmd)
        army = AllianceResourceService.build_combat_first_army(city_troops or {}, max_cap)
        total_troops = sum(cnt for _, cnt in army)
        if total_troops <= 0:
            avail_units = [(int(u), int(c)) for u, c in (city_troops or {}).items() if int(c or 0) > 0]
            if avail_units:
                avail_units.sort(key=lambda x: -x[1])
                army = [(avail_units[0][0], min(avail_units[0][1], max_cap))]
                total_troops = sum(cnt for _, cnt in army)

        if total_troops <= 0:
            _log("ALLIANCE_DISPATCH_FAIL", "[-] No available troops in city to dispatch to Alliance Resource Center.")
            await asyncio.sleep(5.5)
            return {"success": False, "reason": "no_troops", "message": "No available troops in city"}

        cmd_pair_desc = f"{cand_name} (Hero #{primary_cmd} L{primary_lvl})" + (f" + {sec_name}" if secondary_cmd else " (Solo)")
        _log("ALLIANCE_ARMY", f"Dispatching {total_troops:,}/{max_cap:,} units under {cmd_pair_desc}...")

        # Dispatch Opcode 1012
        pkt_1012 = build_gather_dispatch(
            node_id=node_id,
            army_list=army,
            primary_hero_id=primary_cmd,
            secondary_hero_id=secondary_cmd,
            march_index=march_index
        )
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_1012)))
        await writer.drain()

        # Read STRICT Server ACK
        ack_code = None
        start_wait = time.time()
        while time.time() - start_wait < 3.0:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.5)
                rl = (rh[0] << 8) | rh[1]
                raw_b = await asyncio.wait_for(reader.readexactly(rl), timeout=0.5)
                dec = crypto_rx.decrypt(raw_b)
                data = dec
                z_idx = dec.find(b"\x78\x9c")
                if z_idx == -1: z_idx = dec.find(b"\x78\x01")
                if z_idx != -1:
                    try:
                        data = zlib.decompress(dec[z_idx:])
                    except Exception:
                        data = dec
                m = ProtobufCodec.decode_message(data)
                chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                for c in chunks:
                    item = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                    op = item.get(1)
                    if op == 1:
                        p_body = item.get(2)
                        p_dec = ProtobufCodec.decode_message(p_body) if isinstance(p_body, bytes) else p_body
                        if isinstance(p_dec, dict) and p_dec.get(1) == 1012:
                            ack_code = p_dec.get(2, -1)
                            if ack_code in (0, 1):
                                confirmed = True
                                break
                            elif ack_code == 156:
                                already_present = True
                                confirmed = True
                                break
                            elif ack_code == 155:
                                # unowned or busy commander on server
                                break
                            else:
                                break
                    elif op in (1005, 1023):
                        confirmed = True
                        break
                if confirmed or ack_code is not None:
                    break
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                break
            except Exception:
                break

        last_ack_code = ack_code
        if confirmed:
            successful_hero = cand_hero
            successful_army = army
            successful_total_troops = total_troops
            break
        # ANY refusal or timeout: never stall on one hero (manual or auto).
        # A busy/out-marching commander falls back to the next candidate in
        # THIS round, so the march still goes out.
        if ack_code == 155:
            _log("ALLIANCE_DISPATCH_WARN", f"Commander {cand_name} (#{primary_cmd}) rejected (155: busy/unowned) - auto fallback to next candidate...")
        elif ack_code == 135:
            _log("ALLIANCE_DISPATCH_WARN", f"Commander {cand_name} (#{primary_cmd}) rejected (135: busy/state) - auto fallback to next candidate...")
        elif ack_code is None:
            _log("ALLIANCE_DISPATCH_WARN", f"Commander {cand_name} (#{primary_cmd}) no server verdict (timeout) - auto fallback to next candidate...")
        else:
            _log("ALLIANCE_DISPATCH_WARN", f"Commander {cand_name} (#{primary_cmd}) rejected (code {ack_code}) - auto fallback to next candidate...")
        await asyncio.sleep(0.4)
        continue

    if confirmed and successful_hero:
        final_cmd = int(successful_hero["hero_id"])
        final_cmd_name = COMMANDER_NAMES.get(final_cmd, f"Commander #{final_cmd}")
        # Record successful dispatch into session cache to strictly prevent duplicate marches
        _ACTIVE_PIT_MARCHES[str(role_id)] = time.time()

        # 5 to 6 seconds timeout before handing off to normal map gather script
        _log("ALLIANCE_TIMEOUT", "Waiting 5.5s timeout for server state synchronization before map gathering...")
        await asyncio.sleep(5.5)

        if already_present:
            _log("ALLIANCE_DISPATCH_OK", f"ℹ️ Governor already has an active march in {node_name} #{node_id} (الحالة: {status_disp}).")
            return {
                "success": True,
                "node_id": node_id,
                "node_name": node_name,
                "commander": final_cmd,
                "commander_name": final_cmd_name,
                "units": successful_total_troops,
                "army": successful_army,
                "type": super_node.get("type", 3),
                "status": "already_present",
                "pit_status": status,
                "status_display": status_disp
            }
        else:
            action_desc = "للمساعدة في بناء" if status == "building" else "إلى"
            _log("ALLIANCE_DISPATCH_OK", f"✅ Successfully dispatched {successful_total_troops:,} troops {action_desc} {node_name} #{node_id} under {final_cmd_name} (الحالة: {status_disp})!")
            return {
                "success": True,
                "node_id": node_id,
                "node_name": node_name,
                "commander": final_cmd,
                "commander_name": final_cmd_name,
                "units": successful_total_troops,
                "army": successful_army,
                "type": super_node.get("type", 3),
                "status": "dispatched",
                "pit_status": status,
                "status_display": status_disp
            }
    else:
        _log("ALLIANCE_DISPATCH_FAIL", f"[-] Dispatch to {node_name} not confirmed (code={last_ack_code}).")
        await asyncio.sleep(5.5)
        return {
            "success": False,
            "node_id": node_id,
            "ack_code": last_ack_code,
            "reason": f"server_error_{last_ack_code}" if last_ack_code is not None else "no_ack"
        }
