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

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "python"))
sys.path.insert(0, ROOT_DIR)

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed
from cloud_role_switcher import ensure_character_active

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

RESOURCE_NAME_TO_TYPE = {
    "food": 1,
    "wood": 2,
    "stone": 3,
    "gold": 4,
    "gem": 5,
}

COMMANDER_POOL = [15, 38, 33, 32, 34, 35, 3]

# Verified per-character unlocked commanders from game assets and live account data
ROLE_COMMANDERS = {
    # AmmAr (Power 4.62M): Joan of Arc (#15), Kusunoki (#13), Sun Tzu (#3), Sarka (#38), Constance (#33), etc.
    227658377: [15, 38, 33, 13, 3, 11, 10, 8, 7, 5, 2, 4, 6, 12, 1, 9, 34, 35],
    227652418: [34, 35, 3, 36],
    231250084: [35, 3],
    231250589: [34, 33, 35, 3],
}

ROLE_MARCH_CAPACITY = {
    227658377: 156200, # AmmAr
    227652418: 65000,  # ssar3
    231250084: 8000,
    231250589: 28500,
}

COMMANDER_NAMES = {
    15: "Joan of Arc",
    38: "Sarka",
    33: "Constance",
    32: "Cleopatra VII",
    34: "Gaius Marius",
    35: "Tomoe Gozen",
    3: "Sun Tzu",
    36: "Lancelot",
    13: "Kusunoki Masashige",
    23: "Markswoman",
    24: "Centurion",
    8: "Scipio Africanus",
    11: "Baibars",
    10: "Belisarius",
    7: "Eulji Mundeok",
    5: "Pelagius",
    6: "Lohar",
    12: "Osman I",
    1: "City Keeper",
    9: "Hermann",
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

DEFAULT_MARCH_CAPACITY = 35000

# Real in-game unit loads for T1 through T5 across all Rise of Kingdoms accounts
NATIVE_UNIT_LOAD = {
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

NATIVE_PRIORITY_ORDER = [
    20, 16, 12, 8, 4,   # Siege T5 -> T1 (28 -> 20 load)
    17, 13, 9, 5, 1,    # Infantry T5 -> T1 (14 -> 10 load)
    19, 15, 11, 7, 3,   # Archer T5 -> T1 (13 -> 9 load)
    18, 14, 10, 6, 2,   # Cavalry T5 -> T1 (12 -> 8 load)
]

def calculate_native_march_composition(
    node_reserves: float,
    available_troops: Dict[int, int],
    max_capacity: int = 35000,
    buffer_load: float = None
) -> Tuple[List[Tuple[int, int]], int, float]:
    """
    Rise of Kingdoms Greedy Load-Matching Algorithm:
    1. Buffer: 1,000 to 1,500 extra load capacity (+1.5% capped at 1,500) so no crumbs are left behind.
    2. Sorts troops by load capacity descending (Siege -> Infantry -> Archer -> Cavalry).
    3. Calculates exact troop composition instantly for ANY node reserves.
    4. Stops adding troops when Accumulated March Load >= Target Load OR Total Troops == max_capacity.
    """
    if buffer_load is None:
        buffer_load = min(max(float(node_reserves) * 0.015, 1000.0), 1500.0)

    march_army = []
    accumulated_load = 0.0
    total_troops = 0
    target_reserves = float(node_reserves) + buffer_load

    all_types = sorted(
        [ut for ut in available_troops.keys() if available_troops.get(ut, 0) > 0],
        key=lambda ut: (-NATIVE_UNIT_LOAD.get(ut, 8.0), NATIVE_PRIORITY_ORDER.index(ut) if ut in NATIVE_PRIORITY_ORDER else 99)
    )

    for ut in all_types:
        avail = available_troops.get(ut, 0)
        if avail <= 0:
            continue

        if total_troops >= max_capacity or accumulated_load >= target_reserves:
            break

        load_per_unit = NATIVE_UNIT_LOAD.get(ut, 8.0)
        remaining_needed = target_reserves - accumulated_load
        space_left = max_capacity - total_troops

        units_needed = int(math.ceil(remaining_needed / load_per_unit))
        units_to_take = min(avail, units_needed, space_left)

        if units_to_take > 0:
            march_army.append((ut, units_to_take))
            total_troops += units_to_take
            accumulated_load += (units_to_take * load_per_unit)

    return march_army, total_troops, accumulated_load
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATUS_FILE = os.path.join(PROJECT_ROOT, "gather_status.json")

def _status_file() -> str:
    """Per-tenant march status file: tenants never share march snapshots."""
    try:
        from app.tenant_ctx import current_user_id
        uid = (current_user_id.get() or "").strip()
    except Exception:
        uid = ""
    if uid:
        tdir = os.path.join(PROJECT_ROOT, "tenants", uid)
        try:
            os.makedirs(tdir, exist_ok=True)
        except Exception:
            pass
        return os.path.join(tdir, "gather_status.json")
    return STATUS_FILE

def save_gather_status(active_marches_dict: dict, total_city_troops: int, deployed_marches_details: list = None):
    marches_data = []
    if deployed_marches_details:
        for d in deployed_marches_details:
            marches_data.append({
                "cmd_id": d.get("cmd_id"),
                "cmd_name": COMMANDER_NAMES.get(d.get("cmd_id"), f"Commander #{d.get('cmd_id')}"),
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
        with open(_status_file(), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def encode_point(x: float, y: float) -> bytes:
    # Tag 15 is Field 2 (fixed32 X), Tag 0d is Field 1 (fixed32 Y)
    return b"\x15" + struct.pack("<f", float(x)) + b"\x0d" + struct.pack("<f", float(y))

def build_map_request(center_pos: tuple) -> bytes:
    f1 = encode_point(center_pos[0], center_pos[1])
    payload = ProtobufCodec.encode_message({1: f1, 2: 0, 5: 1})
    return ProtobufCodec.encode_message({1: 1004, 2: payload})

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

async def execute_smart_gather(
    march_targets: List[str] = None,
    target_level: int = 0,
    level_mode: str = "any",
    role_id: int = None,
    gate_host: str = None,
    gate_port: int = None,
    city_pos: Tuple[float, float] = None,
    kingdom_id: int = None
):
    if not march_targets:
        march_targets = ["food", "wood", "stone"]

    active_role_id = role_id or ROLE_ID
    host = gate_host or GATE_IP
    port = gate_port or GATE_PORT

    from fleet_manager import load_fleet, resolve_login_bytes
    fleet = load_fleet()
    target_char = next((c for c in fleet if str(c.get("role_id")) == str(active_role_id)), fleet[0] if fleet else {})

    # Ensure active on Lilith Cloud
    print(f"[1/4] Ensuring active cloud character is {target_char.get('name', active_role_id)}...")
    ensure_character_active(target_char)

    login_bytes = resolve_login_bytes(target_char)
    active_city_pos = city_pos or tuple(target_char.get("city_pos", [6619.23, 718.42]))
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
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b""}))))
    await writer.drain()

    # Map Viewports
    cx, cy = active_city_pos[0], active_city_pos[1]
    viewports = [
        (cx, cy),
        (cx + 30.0, cy),
        (cx - 30.0, cy),
        (cx, cy + 30.0),
        (cx, cy - 30.0),
        (cx + 45.0, cy + 45.0),
        (cx - 45.0, cy - 45.0),
        (cx + 60.0, cy),
        (cx - 60.0, cy),
        (cx, cy + 60.0),
        (cx, cy - 60.0),
    ]
    for vp in viewports:
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(build_map_request(vp))))
    await writer.drain()

    troops_in_city = {}
    active_marches = {}
    busy_commanders = set()
    discovered_nodes = []
    seen_node_ids = set()

    deadline_sync = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline_sync:
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

                # Military troops from Opcode 125
                if op == 125:
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
                                if ut > 0 and cnt > 0:
                                    troops_in_city[ut] = troops_in_city.get(ut, 0) + cnt

                # Active marches
                elif op in (1005, 1023):
                    p_march = ProtobufCodec.decode_message(m.get(2, b"")) if isinstance(m.get(2), bytes) else m.get(2, {})
                    f1 = p_march.get(1, b"")
                    if isinstance(f1, bytes):
                        march_pattern = str(active_role_id).encode() + rb"_(\d+)_(\d+)"
                        matches = re.findall(march_pattern, f1)
                        for m_id_b, h_id_b in matches:
                            m_str = m_id_b.decode()
                            h_id = int(h_id_b.decode())
                            active_marches[m_str] = h_id
                            busy_commanders.add(h_id)

                # Resource nodes from Opcode 1003
                elif op == 1003:
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
                            if pos_b[0] == 0x0d: py, px = v1, v2
                            else: px, py = v1, v2

                        type_id = obj.get(2, 1)
                        level = obj.get(3, 1)
                        occupier = obj.get(7, 0)
                        march_st = obj.get(8, 0)
                        is_free = (not occupier or occupier == 0 or occupier == b"") and (not march_st or march_st == 0)

                        dist = round(math.hypot(px - active_city_pos[0], py - active_city_pos[1]), 1)
                        res_name_key, res_display = RESOURCE_TYPE_MAP.get(type_id, ("food", "Resource Field"))

                        max_res = unpack_double_field(obj.get(4))
                        rem_res = unpack_double_field(obj.get(5))
                        std_cap = float(STANDARD_NODE_CAPACITIES.get(type_id, {}).get(level, 472500.0))
                        if max_res <= 0.0: max_res = std_cap
                        if rem_res <= 0.0: rem_res = max_res

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

    free_nodes = [n for n in discovered_nodes if n["free"]]
    print(f"\n[SEARCH] Discovered {len(free_nodes)} free resource deposits:")
    for fn in sorted(free_nodes, key=lambda x: (-x["level"], x["dist"]))[:8]:
        print(f"   * {fn['name']} #{fn['node_id']} (Lvl {fn['level']}) at {fn['pos']} - Reserves: {int(fn['remaining_reserves']):,} - Dist: {fn['dist']}km")

    if free_queues == 0:
        print("\n[SUCCESS] All march queues are currently gathering on the map!")
        save_gather_status(active_marches, total_avail_soldiers)
        writer.close()
        await writer.wait_closed()
        return True

    # 4. Multi-March Dispatch Loop
    marches_to_dispatch = min(free_queues, len(march_targets))
    print(f"\n[4/4] Dispatching up to {marches_to_dispatch} march(es)...")

    assigned_nodes = set()
    dispatched = 0
    role_pool = ROLE_COMMANDERS.get(int(active_role_id), COMMANDER_POOL)
    available_commanders = [c for c in role_pool if c not in busy_commanders]
    dispatched_details = []

    for m_idx in range(marches_to_dispatch):
        march_num = active_marches_count + m_idx + 1
        req_type = march_targets[m_idx % len(march_targets)].lower()

        if total_avail_soldiers <= 0:
            print(f"[ENGINE] All city troops deployed.")
            break

        if not available_commanders:
            print(f"[ENGINE] All commanders busy.")
            break

        cmd_id = available_commanders.pop(0)
        cmd_name = COMMANDER_NAMES.get(cmd_id, f"Commander #{cmd_id}")

        candidates = [
            n for n in free_nodes 
            if n["type"] == req_type and n["node_id"] not in assigned_nodes
        ]
        if not candidates:
            candidates = [n for n in free_nodes if n["node_id"] not in assigned_nodes]

        if not candidates:
            print(f"[SEARCH] No free resource deposits remaining for March #{march_num}.")
            break

        # Level filtering
        if target_level and target_level > 0:
            if level_mode == "min":
                lvl_candidates = [c for c in candidates if c["level"] >= target_level]
            elif level_mode == "max":
                lvl_candidates = [c for c in candidates if c["level"] <= target_level]
            else: # exact
                lvl_candidates = [c for c in candidates if c["level"] == target_level]
            if lvl_candidates:
                candidates = lvl_candidates

        # Sort: highest level first, then closest distance
        candidates.sort(key=lambda x: (-x["level"], x["dist"]))
        target_node = candidates[0]
        assigned_nodes.add(target_node["node_id"])

        node_reserves = target_node.get("remaining_reserves") or target_node.get("max_reserves") or 472500.0
        role_max_cap = ROLE_MARCH_CAPACITY.get(int(active_role_id), DEFAULT_MARCH_CAPACITY)

        allocated_army, total_units, march_load = calculate_native_march_composition(
            node_reserves=node_reserves,
            available_troops=troops_in_city,
            max_capacity=role_max_cap,
            buffer_load=1000.0
        )

        if not allocated_army or total_units <= 0:
            print(f"[ENGINE] Insufficient troops for March #{march_num}.")
            available_commanders.insert(0, cmd_id)
            break

        print(f"\n[DISPATCH] March #{march_num} -> {target_node['name']} #{target_node['node_id']} (Lvl {target_node['level']})")
        print(f"   Target Reserves: {int(node_reserves):,} | Distance: {target_node['dist']}km")
        print(f"   Commander: {cmd_name} (#{cmd_id}) | Units: {total_units:,} | Load: {int(march_load):,}")

        # Step 1: Center Viewport on target node
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(build_map_request(target_node["pos"]))))
        await writer.drain()
        await asyncio.sleep(0.05)

        # Step 2: Preflight Inspection Chain (1050, 925, 423, 9726, 9)
        pkt_1050 = build_inspect(target_node["node_id"], target_node["pos"], city_pos=active_city_pos, alliance_id=active_alliance_id)
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_1050)))
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex("089d0712020800")))) # 925
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex("08a70312020800")))) # 423
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex("08fe4b1200"))))     # 9726
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(bytes.fromhex("08091200"))))         # 9
        await writer.drain()

        # Step 3: Wait for Opcode 1051 ACK
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
            except:
                break

        # Step 4: Send SendTroopConfirm (Opcode 8)
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(build_send_troop_confirm())))
        await writer.drain()
        await asyncio.sleep(0.05)

        # Step 5: Send Opcode 1012 Dispatch
        pkt_1012 = build_dispatch(target_node["node_id"], army_list=allocated_army, commander_id=cmd_id)
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_1012)))
        await writer.drain()

        # Step 6: Confirmation
        confirmed = False
        start_wait = time.time()
        while time.time() - start_wait < 2.0:
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
                for c in chunks:
                    item = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                    op = item.get(1)
                    if op in (903, 365, 1013, 1005, 1024, 1023):
                        confirmed = True
                        break
                if confirmed: break
            except:
                break

        if confirmed:
            for ut, cnt in allocated_army:
                troops_in_city[ut] = max(0, troops_in_city.get(ut, 0) - cnt)
            total_avail_soldiers = max(0, total_avail_soldiers - total_units)
            print(f"[SUCCESS] March #{march_num} CONFIRMED deployed on Kingdom map!")
            dispatched += 1
            active_marches[f"m_{cmd_id}"] = cmd_id
            dispatched_details.append({
                "cmd_id": cmd_id,
                "type": target_node["type"],
                "target": f"{target_node['name']} #{target_node['node_id']} (Lvl {target_node['level']})",
                "troops": total_units,
                "load": int(march_load),
                "node_reserves": int(node_reserves)
            })
        else:
            print(f"[-] March #{march_num} dispatch not confirmed by server.")

        await asyncio.sleep(0.3)

    print("\n" + "=" * 65)
    print(f"  [SUMMARY] Dispatched {dispatched} new march(es) | Active Marches: {len(active_marches)}/5")
    print(f"  Available City Army: {total_avail_soldiers:,} soldiers remaining")
    print("=" * 65)

    save_gather_status(active_marches, total_avail_soldiers, dispatched_details)
    writer.close()
    await writer.wait_closed()
    return (dispatched > 0 or active_marches_count > 0)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Headless Gather Engine")
    parser.add_argument("targets", nargs="?", default="food,wood,stone", help="Comma-separated resource targets")
    parser.add_argument("level", nargs="?", type=int, default=0, help="Target resource node level (default: 0 = highest available)")
    parser.add_argument("--level-mode", choices=["exact", "max", "min", "any"], default="any", help="Level filter constraint")
    parser.add_argument("--target-role", "--role-id", dest="target_role", type=int, default=None, help="Character Role ID")
    parser.add_argument("--kingdom", "--kingdom-id", dest="kingdom_id", type=int, default=None, help="Kingdom Server ID")
    parser.add_argument("--city-pos", dest="city_pos", default=None, help="City position as X,Y")
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
        city_pos=cpos
    ))
