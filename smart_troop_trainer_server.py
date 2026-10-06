"""
smart_troop_trainer.py — Headless Rise of Kingdoms Troop Trainer
Commercial-grade auto-discovery of all 4 military barracks for any player account.
"""

import asyncio
from app.services.proxy_transport import open_game_connection
import os
import sys
import time
import zlib
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PYTHON_DIR = os.path.join(BASE_DIR, "python")
for p in (BASE_DIR, PYTHON_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from session_validator import switch_and_validate
from derive_seed_from_nonce import derive_seed

GATE_IP = "43.159.113.101"
GATE_PORT = 3101

# Mapping from game unit_type ID in Opcode 302 to category
UNIT_TYPE_TO_CATEGORY = {
    1: "infantry",   # Swordsman / Spearman / Guard
    2: "cavalry",    # Light Cavalry / Horseman / Knight
    3: "archery",    # Bowman / Archer / Crossbowman
    4: "siege",      # Battering Ram / Ballista / Catapult (Unit ID 4 in live game)
    8: "siege",      # Fallback legacy ID
}

CATEGORY_TO_NAME = {
    "infantry": "Infantry",
    "cavalry": "Cavalry",
    "archery": "Archers",
    "siege": "Siege",
}


# Official Rise of Kingdoms Barracks Capacity per Building Level (Lvl 1 - 25)
BARRACKS_CAPACITY = {
    1: 20,
    2: 50,
    3: 100,
    4: 150,
    5: 200,
    6: 250,
    7: 300,
    8: 350,
    9: 400,
    10: 450,
    11: 500,
    12: 550,
    13: 600,
    14: 700,
    15: 800,
    16: 900,
    17: 1000,
    18: 1100,
    19: 1200,
    20: 1300,
    21: 1400,
    22: 1500,
    23: 1600,
    24: 1700,
    25: 2000,
}

# Backward/Forward compatibility aliases
BARRACKS_CAPACITY_MATRIX = BARRACKS_CAPACITY
BARRACKS_CAPACITY_TABLE = BARRACKS_CAPACITY
BUILDING_CAPACITY_TABLE = BARRACKS_CAPACITY

def get_building_training_capacity(building_level: int) -> int:
    """Returns official game training capacity for a given barracks level (Levels 1 to 25)."""
    try:
        lvl = int(building_level)
    except (ValueError, TypeError):
        lvl = 17
    return BARRACKS_CAPACITY.get(lvl, 1000 if lvl >= 17 else 400)

def _scan_for_302(msg, discovered):
    """Recursively walk any decoded protobuf looking for opcode 302 barracks state."""
    if not isinstance(msg, dict):
        return
    op = msg.get(1, 0)
    payload = msg.get(2)
    if op == 302 and isinstance(payload, bytes):
        try:
            p302 = ProtobufCodec.decode_message(payload)
            entries = p302.get(1, [])
            if not isinstance(entries, list):
                entries = [entries]
            for bentry in entries:
                if isinstance(bentry, bytes):
                    try:
                        binfo = ProtobufCodec.decode_message(bentry)
                        raw_id = binfo.get(1)
                        b_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
                        u_type = binfo.get(2, 0)
                        count = binfo.get(3, 0)
                        remaining_ms = binfo.get(4, 0)
                        remaining_sec = max(0, remaining_ms // 1000)
                        cat = UNIT_TYPE_TO_CATEGORY.get(u_type, f"unknown_{u_type}")
                        discovered[cat] = {
                            "building_id": b_id,
                            "unit_type": u_type,
                            "current_training_count": count,
                            "remaining_seconds": remaining_sec,
                            "is_busy": remaining_sec > 0,
                            "needs_collect": (remaining_sec == 0) and (count > 0),
                        }
                    except Exception:
                        pass
        except Exception:
            pass
    # Recurse into all byte and list values
    for k, v in msg.items():
        if isinstance(v, bytes) and len(v) > 1:
            try:
                _scan_for_302(ProtobufCodec.decode_message(v), discovered)
            except Exception:
                pass
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, bytes) and len(item) > 1:
                    try:
                        _scan_for_302(ProtobufCodec.decode_message(item), discovered)
                    except Exception:
                        pass

def _scan_for_124(msg, discovered, base_barracks=None):
    """Opcode 124 is city building level/layout status. Training timers are exclusively handled by Opcode 302."""
    pass



async def auto_discover_military_buildings(reader, crypto_rx,
                                           crypto_tx=None, writer=None,
                                           trigger_ids=None, base_barracks=None):
    discovered = {}
    deadline = asyncio.get_event_loop().time() + 3.0

    # Query all building states via Opcode 123
    if crypto_tx and writer and trigger_ids:
        b_list = [bid.encode() if isinstance(bid, str) else bid for bid in trigger_ids]
        pkt_123 = ProtobufCodec.encode_message({
            1: 123,
            2: ProtobufCodec.encode_message({1: b_list})
        })
        try:
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_123)))
            await writer.drain()
        except Exception:
            pass

    while asyncio.get_event_loop().time() < deadline:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.8)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=0.8)
            dec = crypto_rx.decrypt(rd)

            candidates = [dec]
            z_idx = dec.find(b"\x78\x9c")
            if z_idx == -1: z_idx = dec.find(b"\x78\x01")
            if z_idx != -1:
                try: candidates.append(zlib.decompress(dec[z_idx:]))
                except Exception: pass

            for data in candidates:
                try:
                    msg = ProtobufCodec.decode_message(data)
                    _scan_for_302(msg, discovered)
                    _scan_for_124(msg, discovered, base_barracks)
                except Exception:
                    pass

            if len(discovered) >= 4:
                break

        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            break

    return discovered


TIER_UNIT_MAP = {
    ("infantry", 1): 1, ("infantry", 2): 5, ("infantry", 3): 9, ("infantry", 4): 13, ("infantry", 5): 17,
    ("cavalry", 1): 2,  ("cavalry", 2): 6,  ("cavalry", 3): 10, ("cavalry", 4): 14, ("cavalry", 5): 18,
    ("archery", 1): 3,  ("archery", 2): 7,  ("archery", 3): 11, ("archery", 4): 15, ("archery", 5): 19,
    ("siege", 1): 4,    ("siege", 2): 8,    ("siege", 3): 12,   ("siege", 4): 16,   ("siege", 5): 20,
}

BUILDING_NAMES = {
    "infantry": "Barracks",
    "cavalry": "Stable",
    "archery": "Archery Range",
    "siege": "Siege Workshop",
}

# Spec-anchored unit names (5 -> Swordsman, 4 -> Iron Battering Ram).
# Unknown IDs fall back to "T{n} {Category}" — cosmetic log labels only.
UNIT_ID_NAMES = {
    5: "Swordsman",
    4: "Iron Battering Ram",
}


def format_train_telemetry(char_name, cat, unit_id, count, b_level):
    """HH:MM:SS [Governor] Trained {Count}x {Unit} ({Tier}) at {Building} (Lv.{n})."""
    import datetime as _dt
    ts = _dt.datetime.now().strftime("%I:%M:%S %p")
    rev = {v: k for k, v in TIER_UNIT_MAP.items()}
    _cat, tier = rev.get(int(unit_id), (cat, 0))
    name = UNIT_ID_NAMES.get(int(unit_id)) or (f"T{tier} {cat.capitalize()}" if tier else cat.capitalize())
    tier_s = f"T{tier}" if tier else "?"
    return (f"{ts} [{char_name}] Trained {int(count):,}x {name} ({tier_s}) "
            f"at {BUILDING_NAMES.get(cat, 'Barracks')} (Lv.{b_level})")


async def train_troops_dynamically(target_type="all", unit_count=200, gate_host=None, gate_port=None,
                                   login_bytes=None, login_hex_path=None, barracks_override=None,
                                   target_role_id=None, kingdom_id=None,
                                   log_callback=None, tiers=None, percentage=100,
                                   app_uid=None, app_token=None, udid=None):
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

    target_rid = int(target_role_id) if target_role_id else 227658377
    tgt_kid = int(kingdom_id or 3057)

    is_train_all = False
    if isinstance(target_type, str):
        is_train_all = target_type.lower() in ("all", "all_barracks", "*")
        title_target = "ALL 4 BARRACKS" if is_train_all else target_type.upper()
    elif isinstance(target_type, (list, tuple, set)):
        title_target = ", ".join(str(x) for x in target_type).upper()
        if len(target_type) == 4:
            is_train_all = True
    else:
        title_target = str(target_type)
    print("=" * 65)
    print(f"  HEADLESS AUTO-DISCOVERY TROOP TRAINER")
    print(f"  Target: {title_target} | Units Per Barracks: {unit_count if unit_count is not None else f'{percentage}% MAX'}")
    if target_role_id:
        print(f"  Character Role: {target_rid} (Kingdom {tgt_kid})")
    print("=" * 65)

    resolved_uid = app_uid
    resolved_token = app_token
    resolved_udid = udid or "2FDD3FAE2F7366EF2096EE307689BF45"

    if not resolved_uid or not resolved_token:
        try:
            from app.models import CharacterDAO, AccountDAO
            db_char = CharacterDAO.get_by_role_id(str(target_rid))
            if db_char:
                if not kingdom_id and db_char.get("kingdom_id"):
                    tgt_kid = int(db_char["kingdom_id"])
                db_acc = AccountDAO.get_by_id(db_char["account_id"])
                if db_acc:
                    resolved_uid = db_acc.get("app_uid")
                    resolved_token = db_acc.get("app_token")
                    resolved_udid = db_acc.get("udid") or resolved_udid
        except Exception:
            pass

    if resolved_uid and resolved_token:
        try:
            from cloud_role_switcher import switch_cloud_active_role
            switch_cloud_active_role(
                role_id=int(target_rid),
                server_id=int(tgt_kid),
                app_uid=str(resolved_uid),
                app_token=str(resolved_token),
                udid=str(resolved_udid)
            )
        except Exception as e_sw:
            print(f"    [WARN] Cloud switch attempt: {e_sw}")

    host = gate_host
    port = gate_port or GATE_PORT
    if not host and resolved_uid and resolved_token:
        try:
            from app.services.lilith_cloud import LilithCloudService
            host, resolved_port = LilithCloudService.resolve_gateway(
                str(resolved_uid), str(resolved_token), str(resolved_udid), str(tgt_kid)
            )
            if resolved_port:
                port = resolved_port
        except Exception:
            pass
    if not host:
        host = GATE_IP

    print(f"[1/5] Connecting to Rise of Kingdoms server ({host}:{port})...")
    reader, writer = await open_game_connection(host, port)

    hdr = await reader.readexactly(2)
    g_len = (hdr[0] << 8) | hdr[1]
    g_payload = await reader.readexactly(g_len)
    g_fields = ProtobufCodec.decode_message(g_payload)
    sub = ProtobufCodec.decode_message(g_fields.get(2, b""))
    seed_tx, seed_rx = derive_seed(sub.get(1, 0), sub.get(2, 0))

    crypto_tx = RokCrypto(seed_tx)
    crypto_rx = RokCrypto(seed_rx)

    # 2. Login
    print("[2/5] Authenticating account session...")
    if login_bytes is None:
        if resolved_uid and resolved_token:
            from fleet_manager import build_dynamic_login_payload
            login_bytes = build_dynamic_login_payload(
                app_uid=str(resolved_uid),
                access_token=str(resolved_token),
                role_id=int(target_rid),
                device_id=str(resolved_udid),
                kingdom_id=int(tgt_kid),
                server_id_int=2104267
            )
        else:
            from fleet_manager import load_fleet, resolve_login_bytes
            fleet = load_fleet()
            if fleet:
                target_char = next((c for c in fleet if str(c.get("role_id")) == str(target_rid)), fleet[0])
                login_bytes = resolve_login_bytes(target_char)
            else:
                raise RuntimeError("No characters configured in database or fleet to authenticate.")

    writer.write(FrameParser.build_frame(crypto_tx.encrypt(login_bytes)))
    await writer.drain()

    # 2b. Request profile & verify target character
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
    await writer.drain()

    discovered_302 = {}
    loaded_name = ""
    switched_ok = False
    target_rid = int(target_rid)
    tgt_kid = int(tgt_kid)

    drain_deadline = asyncio.get_event_loop().time() + 1.5
    while asyncio.get_event_loop().time() < drain_deadline:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
            rl = (rh[0] << 8) | rh[1]
            raw_pkt = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
            dec = crypto_rx.decrypt(raw_pkt)
            z_idx = dec.find(b"\x78\x9c")
            if z_idx == -1: z_idx = dec.find(b"\x78\x01")
            data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
            msg = ProtobufCodec.decode_message(data)
            _scan_for_302(msg, discovered_302)
            chunks = msg.get(1) if isinstance(msg.get(1), list) else [msg]
            for c in chunks:
                m = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                _scan_for_302(m, discovered_302)
                op = m.get(1)
                if op == 904 and isinstance(m.get(2), bytes):
                    from app.services.city_layout import CityLayoutResolver
                    b_904 = CityLayoutResolver.parse_opcode_904(m.get(2))
                    for cat_k, bid_v in b_904.items():
                        if cat_k not in discovered_302:
                            discovered_302[cat_k] = {"building_id": str(bid_v), "category": cat_k}
                        else:
                            discovered_302[cat_k]["building_id"] = str(bid_v)
                elif op == 124 and isinstance(m.get(2), bytes):
                    from app.services.city_layout import CityLayoutResolver
                    res_124 = CityLayoutResolver.parse_opcode_124(m.get(2))
                    if res_124.get("barracks"):
                        for cat_k, bdata_v in res_124["barracks"].items():
                            if cat_k not in discovered_302:
                                discovered_302[cat_k] = bdata_v
                            else:
                                discovered_302[cat_k].update(bdata_v)
                elif op == 15:
                    p15 = ProtobufCodec.decode_message(m.get(2, b"")) if isinstance(m.get(2), bytes) else m.get(2, {})
                    raw_n = p15.get(5, b"")
                    loaded_name = raw_n.decode("utf-8", errors="replace") if isinstance(raw_n, bytes) else str(raw_n)
                    loaded_power = p15.get(6, 0)
                    loaded_kd = p15.get(2)
                    loaded_rid = p15.get(1)

                    if loaded_rid and str(target_rid) == str(loaded_rid):
                        print(f"    [VERIFIED] Direct session on target Character: {loaded_name} | Power: {loaded_power:,} | Kingdom: {loaded_kd}")
                        switched_ok = True
                    else:
                        print(f"    [INITIAL LOAD] Character: {loaded_name} (Role {loaded_rid}) | Kingdom {loaded_kd} | Power {loaded_power:,}")
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            break
        except Exception:
            pass

    # If the gateway loaded another character, switch to target
    if not switched_ok:
        # Send Switch Sequence if active character != target
        print(f"    [ROLE SWITCH] Gateway loaded non-target role. Switching to Target Role {target_rid} (Kingdom {tgt_kid})...")
        p203 = ProtobufCodec.encode_message({1: target_rid})
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: p203}))))
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
        p110 = ProtobufCodec.encode_message({1: target_rid, 2: tgt_kid, 3: target_rid})
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: p110}))))
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
        await writer.drain()

    active_profile = {}
    drain_deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < drain_deadline:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
            rl = (rh[0] << 8) | rh[1]
            raw_pkt = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
            dec = crypto_rx.decrypt(raw_pkt)
            z_idx = dec.find(b"\x78\x9c")
            if z_idx == -1: z_idx = dec.find(b"\x78\x01")
            data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
            msg = ProtobufCodec.decode_message(data)
            _scan_for_302(msg, discovered_302)
            chunks = msg.get(1) if isinstance(msg.get(1), list) else [msg]
            for c in chunks:
                m = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                _scan_for_302(m, discovered_302)
                op = m.get(1)
                if op == 904 and isinstance(m.get(2), bytes):
                    from app.services.city_layout import CityLayoutResolver
                    b_904 = CityLayoutResolver.parse_opcode_904(m.get(2))
                    for cat_k, bid_v in b_904.items():
                        if cat_k not in discovered_302:
                            discovered_302[cat_k] = {"building_id": str(bid_v), "category": cat_k}
                        else:
                            discovered_302[cat_k]["building_id"] = str(bid_v)
                elif op == 124 and isinstance(m.get(2), bytes):
                    from app.services.city_layout import CityLayoutResolver
                    res_124 = CityLayoutResolver.parse_opcode_124(m.get(2))
                    if res_124.get("barracks"):
                        for cat_k, bdata_v in res_124["barracks"].items():
                            if cat_k not in discovered_302:
                                discovered_302[cat_k] = bdata_v
                            else:
                                discovered_302[cat_k].update(bdata_v)
                elif op == 204:
                    p204 = ProtobufCodec.decode_message(m.get(2, b"")) if isinstance(m.get(2), bytes) else m.get(2, {})
                    ack_role = p204.get(2)
                    switched_ok = True
                    print(f"    [SUCCESS] Opcode 204 confirmed Target Role {ack_role} active!")
                elif op in (15, 1002):
                    p_info = ProtobufCodec.decode_message(m.get(2, b"")) if isinstance(m.get(2), bytes) else m.get(2, {})
                    if p_info.get(1): active_profile["role_id"] = p_info.get(1)
                    if p_info.get(5):
                        r_n = p_info.get(5)
                        active_profile["name"] = r_n.decode("utf-8", errors="replace") if isinstance(r_n, bytes) else str(r_n)
                    if p_info.get(6): active_profile["power"] = p_info.get(6)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            break
        except Exception:
            pass

    # Hard Assertion on Active Character Profile
    if active_profile.get("role_id"):
        loaded_rid = int(active_profile["role_id"])
        if loaded_rid != int(target_rid):
            raise RuntimeError(
                f"[HARD ASSERTION ABORT] Gateway loaded Role {loaded_rid} ('{active_profile.get('name')}'), "
                f"but target is Role {target_rid}! Switch did not occur on wire. Halting execution."
            )

    # Request fresh post-switch state (Opcode 1001, 1202)
    pkt_1001 = ProtobufCodec.encode_message({1: 1001, 2: b""})
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_1001)))
    pkt_1202 = ProtobufCodec.encode_message({1: 1202, 2: ProtobufCodec.encode_message({1: target_rid})})
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_1202)))
    await writer.drain()

    from app.services.city_layout import CityLayoutResolver
    print("[3/5] Intercepting server layout & discovering military barracks...")
    city_layout = await CityLayoutResolver.discover_layout(
        reader=reader,
        writer=writer,
        crypto_tx=crypto_tx,
        crypto_rx=crypto_rx,
        role_id=str(target_rid),
        city_hall_level=17,
        log_callback=print,
        known_barracks=discovered_302
    )
    barracks = city_layout.get("barracks", {})
    # Fallback to any 302 intercepted earlier
    for cat, d_info in discovered_302.items():
        if cat not in barracks or not barracks[cat].get("building_id"):
            barracks[cat] = d_info
        else:
            barracks[cat].update(d_info)

    barracks = {cat: data for cat, data in barracks.items() if cat in ("infantry", "cavalry", "archery", "siege")}

    print("[+] Verified Account Military Infrastructure:")
    for cat, data in barracks.items():
        busy_txt = f"Busy ({data['remaining_seconds']}s left)" if data.get('is_busy') else "Idle / Ready"
        print(f"    * {CATEGORY_TO_NAME.get(cat, cat):<15} -> Building ID: {data['building_id']:<4} | Status: {busy_txt}")

    # Pre-Harvest Bubbles for buildings where remaining time is <= 0 (avoiding Building #1 Town Hall)
    print("[+] Executing pre-harvest for finished barracks (remaining <= 0s)...")
    for cat, b_data in barracks.items():
        b_id = str(b_data.get("building_id") or "")
        if not b_id or b_id == "1":
            continue
        rem_sec = int(b_data.get("remaining_seconds", 0))
        if rem_sec <= 0:
            u_tp = b_data.get("unit_type", 1)
            print(f"    [PRE-HARVEST] Harvesting finished soldiers from {CATEGORY_TO_NAME.get(cat, cat)} (Building #{b_id})...")
            pkt_120 = ProtobufCodec.encode_message({
                1: 120,
                2: ProtobufCodec.encode_message({1: b_id.encode()})
            })
            pkt_303 = ProtobufCodec.encode_message({
                1: 303,
                2: ProtobufCodec.encode_message({1: b_id.encode(), 2: u_tp})
            })
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_120)))
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_303)))
            await writer.drain()

            # Drain harvest ACKs (Opcode 304 / 302 / 125)
            deadline_harvest = asyncio.get_event_loop().time() + 0.3
            while asyncio.get_event_loop().time() < deadline_harvest:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.1)
                    rl = (rh[0] << 8) | rh[1]
                    raw_p = await reader.readexactly(rl)
                    crypto_rx.decrypt(raw_p)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

    if is_train_all:
        targets_to_train = list(barracks.keys())
    elif isinstance(target_type, list):
        targets_to_train = [t.lower() for t in target_type if t.lower() in barracks]
    elif "," in str(target_type):
        targets_to_train = [t.strip().lower() for t in str(target_type).split(",") if t.strip().lower() in barracks]
    else:
        targets_to_train = [str(target_type).lower()]
    trained_count = 0

    # 4. Dispatch Training Orders
    # Resolve character config for barracks level & max capacity
    from fleet_manager import load_fleet
    fleet = load_fleet()
    active_char = next((c for c in fleet if str(c.get("role_id")) == str(target_rid)), fleet[0] if fleet else {})
    char_barracks = active_char.get("barracks_ids", {})

    print(f"\n[4/5] Preparing training orders for {len(targets_to_train)} target building(s) with independent per-building capacity...")
    for cat in targets_to_train:
        try:
            # "Off" tier from web config: skip this barracks completely
            if tiers and str(tiers.get(cat, "")).strip().lower() == "off":
                print(f"    [*] {CATEGORY_TO_NAME.get(cat, cat)} tier is Off in web config — skipping barracks.")
                continue
            b_data = barracks.get(cat)
            if not b_data:
                print(f"[-] Warning: Category '{cat}' not found in barracks map, skipping.")
                continue

            bldg_id = str(b_data.get("building_id") or "")
            cat_name = CATEGORY_TO_NAME.get(cat, cat)

            # Never allow Building #1 for infantry or any barracks (Building #1 is Town Hall)
            if not bldg_id or bldg_id == "1":
                print(f"    [*] Warning: {cat_name} building ID is '{bldg_id}' (Town Hall collision / unassigned). Dynamically resolving from wire...")
                from app.services.city_layout import SessionLayoutRegistry
                cached_layout = SessionLayoutRegistry.get(str(target_rid)) or {}
                cached_barracks = cached_layout.get("barracks", {})
                if cached_barracks.get(cat) and str(cached_barracks[cat].get("building_id")) not in ("", "1"):
                    bldg_id = str(cached_barracks[cat]["building_id"])
                    b_data["building_id"] = bldg_id
                else:
                    # Query wire via Opcode 123 for candidate building IDs
                    query_bids = [str(i).encode() for i in range(1, 150)]
                    pkt_123 = ProtobufCodec.encode_message({
                        1: 123,
                        2: ProtobufCodec.encode_message({1: query_bids})
                    })
                    writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_123)))
                    await writer.drain()

                    re_dl = asyncio.get_event_loop().time() + 1.5
                    while asyncio.get_event_loop().time() < re_dl:
                        try:
                            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.2)
                            rl = (rh[0] << 8) | rh[1]
                            raw_p = await reader.readexactly(rl)
                            dec_p = crypto_rx.decrypt(raw_p)
                            z_idx = dec_p.find(b"\x78\x9c")
                            if z_idx == -1: z_idx = dec_p.find(b"\x78\x01")
                            decomp = zlib.decompress(dec_p[z_idx:]) if z_idx != -1 else dec_p
                            m = ProtobufCodec.decode_message(decomp)
                            chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                            for c in chunks:
                                it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                                if not isinstance(it, dict): continue
                                op = it.get(1)
                                pb = it.get(2)
                                if op == 904 and isinstance(pb, bytes):
                                    b904 = CityLayoutResolver.parse_opcode_904(pb)
                                    if b904.get(cat) and str(b904[cat]) != "1":
                                        bldg_id = str(b904[cat])
                                        b_data["building_id"] = bldg_id
                                        break
                                elif op == 124 and isinstance(pb, bytes):
                                    r124 = CityLayoutResolver.parse_opcode_124(pb)
                                    if r124.get("barracks", {}).get(cat):
                                        c_bid = str(r124["barracks"][cat].get("building_id", ""))
                                        if c_bid and c_bid != "1":
                                            bldg_id = c_bid
                                            b_data["building_id"] = bldg_id
                                            break
                            if bldg_id and bldg_id != "1":
                                print(f"    [+] Dynamically resolved {cat_name} -> Building #{bldg_id} from wire!")
                                break
                        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                            break

            if not bldg_id or bldg_id == "1":
                print(f"[-] Error: Could not resolve valid building ID for {cat_name} on wire (cannot use Building #1). Skipping to eliminate Error 139.")
                continue

            u_type = b_data["unit_type"]

            # Custom tier override if specified
            if tiers and cat in tiers and tiers[cat]:
                try:
                    tier_val = int(tiers[cat])
                    mapped_u = TIER_UNIT_MAP.get((cat, tier_val))
                    if mapped_u:
                        u_type = mapped_u
                except Exception:
                    pass

            # Per-building level and capacity resolution
            cat_conf = char_barracks.get(cat, {}) if isinstance(char_barracks, dict) else {}
            b_level = b_data.get("level") or cat_conf.get("level")
            if not b_level:
                ch_lvl = active_char.get("city_level") or active_char.get("town_hall_level") or 17
                b_level = int(ch_lvl)
            else:
                b_level = int(b_level)

            b_capacity = get_building_training_capacity(b_level)

            # Calculate exact dispatch count for this specific building
            if unit_count is None or str(unit_count).lower() in ("max", "auto", "0") or int(unit_count) <= 0:
                pct_val = max(1, min(100, int(percentage or 100)))
                this_dispatch_count = max(1, int(b_capacity * (pct_val / 100.0)))
            else:
                this_dispatch_count = min(int(unit_count), b_capacity)
                if int(unit_count) > b_capacity:
                    print(f"    [*] Clamping {cat_name} count from {unit_count} to Level {b_level} capacity: {b_capacity}")

            if b_data.get("is_busy") or int(b_data.get("remaining_seconds", 0)) > 0:
                rem = b_data.get("remaining_seconds", 0)
                print(f"    [*] {cat_name} (Building #{bldg_id}) is currently busy ({rem}s left). Skipping.")
                continue

            # Mandatory Unit Bubble Harvest before Opcode 300:
            # Clear completed troop bubbles to prevent Error 138 / Error 110
            pkt_120 = ProtobufCodec.encode_message({
                1: 120,
                2: ProtobufCodec.encode_message({1: bldg_id.encode()})
            })
            pkt_303 = ProtobufCodec.encode_message({
                1: 303,
                2: ProtobufCodec.encode_message({1: bldg_id.encode(), 2: u_type})
            })
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_120)))
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_303)))
            await writer.drain()

            # Await 0.3s server ACK to clear harvest bubble before sending Opcode 300
            d_harvest = asyncio.get_event_loop().time() + 0.3
            while asyncio.get_event_loop().time() < d_harvest:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.1)
                    rl = (rh[0] << 8) | rh[1]
                    raw_p = await reader.readexactly(rl)
                    crypto_rx.decrypt(raw_p)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

            print(f"\n    >>> Dispatching Opcode 300 to {cat_name} (Building #{bldg_id}, Level {b_level}, Unit ID {u_type}, Count {this_dispatch_count})...")
            # Opcode 306: Open building/troop selection panel
            pkt_306 = ProtobufCodec.encode_message({
                1: 306,
                2: ProtobufCodec.encode_message({1: bldg_id.encode()})
            })
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_306)))
            await writer.drain()
            await asyncio.sleep(0.15)

            # True Adaptive Capacity Matrix Loop (Levels 1 to 25):
            # If server rejects with Error 145, step down sequentially through BARRACKS_CAPACITY
            # until the server confirms Opcode 301.
            confirmed = False
            collect_attempted = False
            max_capacity_attempts = len(BARRACKS_CAPACITY)

            for cap_attempt in range(max_capacity_attempts):
                train_request = {
                    1: bldg_id.encode(),
                    2: u_type,
                    3: this_dispatch_count,
                    4: 0,
                    5: 0
                }
                pkt_train = ProtobufCodec.encode_message({
                    1: 300,
                    2: ProtobufCodec.encode_message(train_request)
                })
                writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_train)))
                await writer.drain()

                # Await server response for this dispatch attempt
                got_145 = False
                got_138 = False
                got_139 = False
                fatal_error = None

                deadline = asyncio.get_event_loop().time() + 3.0
                while asyncio.get_event_loop().time() < deadline and not confirmed and not got_145 and not got_138 and not got_139 and not fatal_error:
                    try:
                        rh = await asyncio.wait_for(reader.readexactly(2), timeout=1.0)
                        rl = (rh[0] << 8) | rh[1]
                        rd = await asyncio.wait_for(reader.readexactly(rl), timeout=1.0)
                        dec = crypto_rx.decrypt(rd)
                        z_idx = dec.find(b"\x78\x9c")
                        if z_idx == -1: z_idx = dec.find(b"\x78\x01")
                        data = dec
                        if z_idx != -1:
                            try: data = zlib.decompress(dec[z_idx:])
                            except Exception: pass

                        packets_to_check = []
                        try:
                            m = ProtobufCodec.decode_message(data)
                            if isinstance(m.get(1), list):
                                for chunk in m.get(1):
                                    if isinstance(chunk, bytes):
                                        try: packets_to_check.append(ProtobufCodec.decode_message(chunk))
                                        except: pass
                            else:
                                packets_to_check.append(m)
                        except Exception:
                            continue

                        for msg in packets_to_check:
                            op = msg.get(1, 0)
                            if op == 301:
                                print(f"        [***] SUCCESS: Server confirmed Opcode 301 training started for {cat_name} (Count: {this_dispatch_count}, Level {b_level})!")
                                tline = format_train_telemetry(
                                    (active_char.get("name") if isinstance(active_char, dict) else "") or f"Governor #{target_rid}",
                                    cat, u_type, this_dispatch_count, b_level)
                                print(f"[TELEMETRY] {tline}")
                                try:
                                    from app.services.activity_stream import activity_stream as _as
                                    await _as.broadcast(tline)
                                except Exception:
                                    pass
                                confirmed = True
                                trained_count += 1
                                if b_data:
                                    b_data["capacity"] = this_dispatch_count
                                    b_data["level"] = b_level
                                    b_data["is_busy"] = True
                                    b_data["remaining_seconds"] = 3600
                                try:
                                    from app.services.city_layout import SessionLayoutRegistry
                                    s_layout = SessionLayoutRegistry.get(str(target_rid))
                                    if s_layout and "barracks" in s_layout and cat in s_layout["barracks"]:
                                        s_layout["barracks"][cat]["capacity"] = this_dispatch_count
                                        s_layout["barracks"][cat]["level"] = b_level
                                        SessionLayoutRegistry.set(str(target_rid), s_layout)
                                except Exception:
                                    pass
                                break
                            elif op == 1:
                                payload = msg.get(2)
                                err_info = ProtobufCodec.decode_message(payload) if isinstance(payload, bytes) else payload
                                if isinstance(err_info, dict):
                                    failed_op = err_info.get(1)
                                    err_code = err_info.get(2)
                                    if failed_op == 303:
                                        continue
                                    elif failed_op == 300:
                                        if err_code == 139:
                                            got_139 = True
                                            break
                                        elif err_code == 138:
                                            got_138 = True
                                            break
                                        elif err_code in (145, 110):
                                            got_145 = True
                                            break
                                        else:
                                            fatal_error = err_code
                                            break
                    except (asyncio.TimeoutError, TimeoutError):
                        continue
                    except (asyncio.IncompleteReadError, ConnectionResetError):
                        break

                if confirmed:
                    break

                if got_139:
                    if b_data.get("is_busy") and b_data.get("remaining_seconds", 0) > 0:
                        print(f"        [*] Verified on wire: {cat_name} (Building #{bldg_id}) is busy training ({b_data.get('remaining_seconds')}s left).")
                        confirmed = True
                        trained_count += 1
                    else:
                        print(f"        [TRAIN FAIL] Building #{bldg_id} ({cat_name}) rejected with Server Error Code: 139")
                    break

                if got_138:
                    if collect_attempted:
                        print(f"        [TRAIN FAIL] Building #{bldg_id} ({cat_name}) rejected with Server Error Code: 138 after harvest attempt — skipping.")
                        break
                    print(f"        [*] Finished troops waiting at {cat_name}, collecting & retrying train...")
                    collect_attempted = True
                    pkt_120 = ProtobufCodec.encode_message({1: 120, 2: ProtobufCodec.encode_message({1: bldg_id.encode()})})
                    pkt_303 = ProtobufCodec.encode_message({1: 303, 2: ProtobufCodec.encode_message({1: bldg_id.encode(), 2: u_type})})
                    writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_120)))
                    writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_303)))
                    await writer.drain()
                    await asyncio.sleep(0.3)
                    writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_306)))
                    await writer.drain()
                    await asyncio.sleep(0.15)
                    continue

                if got_145:
                    # Step down to next lower capacity tier in BARRACKS_CAPACITY
                    next_capacity = None
                    next_lvl = None
                    for lvl in sorted(BARRACKS_CAPACITY.keys(), reverse=True):
                        if BARRACKS_CAPACITY[lvl] < this_dispatch_count:
                            next_capacity = BARRACKS_CAPACITY[lvl]
                            next_lvl = lvl
                            break

                    if next_capacity and next_capacity >= 20:
                        print(f"        [*] Adaptive Capacity Loop: Server rejected count {this_dispatch_count} (Error 145). Stepping down to Level {next_lvl} ({next_capacity} units) and retrying in 0.25s...")
                        await asyncio.sleep(0.25)
                        this_dispatch_count = next_capacity
                        b_level = next_lvl
                        continue
                    else:
                        print(f"        [TRAIN FAIL] Building #{bldg_id} ({cat_name}) exhausted capacity tiers down to minimum without server acceptance.")
                        break

                if fatal_error:
                    print(f"        [TRAIN FAIL] Building #{bldg_id} ({cat_name}) rejected with Server Error Code: {fatal_error}")
                    break

                # If timeout occurred without any response from server
                print(f"        [-] Timed out awaiting Opcode 301 response for count {this_dispatch_count}.")
                break
            await asyncio.sleep(0.1)
        except Exception as e_cat:
            print(f"    [-] Exception occurred while training {cat}: {e_cat}. Continuing to next barracks...")
            continue

    hb = ProtobufCodec.encode_message({1: 9, 2: b""})
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(hb)))
    await writer.drain()

    writer.close()
    await writer.wait_closed()
    print("\n" + "=" * 65)
    print(f"  TRAINING SESSION COMPLETE - {trained_count}/{len(targets_to_train)} BARRACKS TRAINED")
    print("=" * 65)
    return True

if __name__ == "__main__":
    t_type = sys.argv[1] if len(sys.argv) > 1 else "all"
    arg2 = sys.argv[2] if len(sys.argv) > 2 else "max"
    if str(arg2).isdigit():
        count = int(arg2)
    elif str(arg2).lower() in ("max", "auto", "all"):
        count = None
    else:
        count = 1100
    asyncio.run(train_troops_dynamically(t_type, count))

