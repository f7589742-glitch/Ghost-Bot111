"""
smart_troop_trainer.py — Headless Rise of Kingdoms Troop Trainer
Commercial-grade auto-discovery of all 4 military barracks for any player account.
"""

import asyncio
import os
import sys
import time
import zlib
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "python"))

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

# Real building IDs verified from AmmAr live capture and accounts_fleet.json
DEFAULT_BARRACKS = {
    "infantry": {"building_id": "15", "unit_type": 1, "level": 16, "capacity": 900,  "is_busy": False, "remaining_seconds": 0},
    "cavalry":  {"building_id": "65", "unit_type": 2, "level": 18, "capacity": 1100, "is_busy": False, "remaining_seconds": 0},
    "archery":  {"building_id": "64", "unit_type": 3, "level": 15, "capacity": 800,  "is_busy": False, "remaining_seconds": 0},
    "siege":    {"building_id": "66", "unit_type": 4, "level": 14, "capacity": 700,  "is_busy": False, "remaining_seconds": 0},
}

# Official Rise of Kingdoms Barracks Capacity per Building Level (Lvl 1 - 25)
BUILDING_CAPACITY_TABLE = {
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

async def train_troops_dynamically(target_type="all", unit_count=200, gate_host=None, gate_port=None,
                                   login_bytes=None, login_hex_path=None, barracks_override=None,
                                   target_role_id=None, kingdom_id=None,
                                   log_callback=None, tiers=None, percentage=100):
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
        print(f"  Character Role: {target_role_id} (Kingdom {kingdom_id})")
    print("=" * 65)

    host = gate_host or GATE_IP
    port = gate_port or GATE_PORT
    print(f"[1/5] Connecting to Rise of Kingdoms server ({host}:{port})...")
    reader, writer = await asyncio.open_connection(host, port)

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
        from fleet_manager import load_fleet, resolve_login_bytes
        fleet = load_fleet()
        if fleet:
            target_char = next((c for c in fleet if str(c.get("role_id")) == str(target_role_id)), fleet[0])
            login_bytes = resolve_login_bytes(target_char)
        else:
            raise RuntimeError("No characters configured in accounts_fleet.json to authenticate.")

    writer.write(FrameParser.build_frame(crypto_tx.encrypt(login_bytes)))
    await writer.drain()

    # 2b. Request profile & verify target character
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
    await writer.drain()

    discovered_302 = {}
    loaded_name = ""
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
                if m.get(1) == 15:
                    p15 = ProtobufCodec.decode_message(m.get(2, b"")) if isinstance(m.get(2), bytes) else m.get(2, {})
                    raw_n = p15.get(5, b"")
                    loaded_name = raw_n.decode("utf-8", errors="replace") if isinstance(raw_n, bytes) else str(raw_n)
                    loaded_power = p15.get(6, 0)
                    loaded_kd = p15.get(2)
                    loaded_rid = p15.get(1)

                    if target_role_id and str(target_role_id) == str(loaded_rid):
                        print(f"    [VERIFIED] Direct session on target Character: {loaded_name} | Power: {loaded_power:,} | Kingdom: {loaded_kd}")
                    else:
                        print(f"    [INITIAL LOAD] Character: {loaded_name} (Role {loaded_rid}) | Kingdom {loaded_kd} | Power {loaded_power:,}")
                    break
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            break
        except Exception:
            pass

    # If the gateway loaded another character (e.g. ssar3 instead of AmmAr), switch to target
    target_rid = int(target_role_id or 227658377)
    tgt_kid = int(kingdom_id or 11543)
    switched_ok = False
    
    # Send Switch Sequence if active character != target
    print(f"    [DIRECT DISPATCH] Ensuring active session matches Target Role {target_rid} (Kingdom {tgt_kid})...")
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
                if op == 204:
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

    # Build trigger IDs: Only use DEFAULT_BARRACKS if target is AmmAr (227658377)
    base_barracks = {}
    if target_rid == 227658377:
        for cat, def_info in DEFAULT_BARRACKS.items():
            base_barracks[cat] = dict(def_info)
    if barracks_override:
        for cat, info in barracks_override.items():
            if cat in base_barracks:
                base_barracks[cat].update(info)
            else:
                base_barracks[cat] = dict(info)

    trigger_ids = list({v["building_id"] for v in base_barracks.values() if "building_id" in v})

    print("[3/5] Intercepting server layout & discovering military barracks...")
    discovered = await auto_discover_military_buildings(
        reader, crypto_rx,
        crypto_tx=crypto_tx, writer=writer,
        trigger_ids=trigger_ids,
        base_barracks=base_barracks
    )
    # Merge any 302 intercepted during login/switch
    for cat, d_info in discovered_302.items():
        if cat not in discovered:
            discovered[cat] = d_info
        else:
            discovered[cat].update(d_info)

    # Merge: base -> override -> live-discovered (live wins)
    barracks = {}
    for cat, def_info in base_barracks.items():
        barracks[cat] = dict(def_info)
        if cat in discovered:
            barracks[cat].update(discovered[cat])

    print("[+] Verified Account Military Infrastructure:")
    for cat, data in barracks.items():
        busy_txt = f"Busy ({data['remaining_seconds']}s left)" if data.get('is_busy') else "Idle / Ready"
        print(f"    * {CATEGORY_TO_NAME.get(cat, cat):<15} -> Building ID: {data['building_id']:<4} | Status: {busy_txt}")

    # Auto-Collect finished troops (clears Recruit bubbles across all barracks)
    print("[+] Checking and auto-collecting completed troops across barracks...")
    for cat, b_data in barracks.items():
        b_id = b_data["building_id"]
        u_tp = b_data.get("unit_type", 1)
        pkt_303 = ProtobufCodec.encode_message({
            1: 303,
            2: ProtobufCodec.encode_message({1: b_id.encode(), 2: u_tp})
        })
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_303)))
        await writer.drain()
        
        # Drain harvest ACKs (Opcode 304 / 302 / 125)
        deadline_harvest = asyncio.get_event_loop().time() + 0.6
        while asyncio.get_event_loop().time() < deadline_harvest:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.15)
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
        b_data = barracks.get(cat)
        if not b_data:
            print(f"[-] Warning: Category '{cat}' not found in barracks map, skipping.")
            continue

        bldg_id = b_data["building_id"]
        u_type = b_data["unit_type"]
        cat_name = CATEGORY_TO_NAME.get(cat, cat)

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
        cat_conf = char_barracks.get(cat, {})
        b_level = b_data.get("level") or cat_conf.get("level")
        if b_level:
            b_capacity = BUILDING_CAPACITY_TABLE.get(int(b_level), 1100)
        else:
            b_capacity = cat_conf.get("capacity") or b_data.get("capacity", 1100)

        # Calculate exact dispatch count for this specific building
        if unit_count is None or str(unit_count).lower() in ("max", "auto", "0") or int(unit_count) <= 0:
            pct_val = max(1, min(100, int(percentage or 100)))
            this_dispatch_count = max(1, int(b_capacity * (pct_val / 100.0)))
        else:
            this_dispatch_count = min(int(unit_count), b_capacity)
            if int(unit_count) > b_capacity:
                print(f"    [*] Clamping {cat_name} count from {unit_count} to Level {b_level} capacity: {b_capacity}")

        if b_data.get("is_busy"):
            rem = b_data.get("remaining_seconds", 0)
            print(f"    [*] {cat_name} (Building #{bldg_id}) is currently busy ({rem}s left). Skipping.")
            continue

        print(f"\n    >>> Dispatching Opcode 300 to {cat_name} (Building #{bldg_id}, Level {b_level}, Unit ID {u_type}, Count {this_dispatch_count})...")
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

        # Await ACK
        confirmed = False
        collect_attempted = False   # cap 303-harvest retries: if 138 fires again after harvest, skip barracks
        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.8)
                rl = (rh[0] << 8) | rh[1]
                rd = await asyncio.wait_for(reader.readexactly(rl), timeout=0.8)
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
                        print(f"        [***] SUCCESS: Server confirmed Opcode 301 training started for {cat_name}!")
                        confirmed = True
                        trained_count += 1
                        break
                    elif op == 1:
                        payload = msg.get(2)
                        err_info = ProtobufCodec.decode_message(payload) if isinstance(payload, bytes) else payload
                        if isinstance(err_info, dict):
                            failed_op = err_info.get(1)
                            err_code = err_info.get(2)
                            print(f"        [DEBUG SERVER RAW] failed_op={failed_op}, err_code={err_code}, full={err_info}")
                            if failed_op == 303:
                                # Opcode 303 error 147 just means "nothing to harvest right now", safe to ignore
                                continue
                            elif failed_op == 300:
                                if err_code == 139:
                                    print(f"        [*] Note: {cat_name} returned error 139 (Queue busy or invalid building).")
                                    confirmed = True
                                    trained_count += 1
                                    break
                                elif err_code == 138:
                                    if collect_attempted:
                                        # 303 harvest already tried but 300 still returns 138 (Siege bubble bug).
                                        # Skip this barracks silently so we don't loop forever.
                                        print(f"        [*] {cat_name} still blocking after collect attempt — queue stuck, skipping.")
                                        confirmed = True
                                        break
                                    print(f"        [*] Finished troops waiting at {cat_name}, collecting & retrying train...")
                                    collect_attempted = True
                                    pkt_303 = ProtobufCodec.encode_message({
                                        1: 303,
                                        2: ProtobufCodec.encode_message({1: bldg_id.encode(), 2: u_type})
                                    })
                                    writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_303)))
                                    await writer.drain()
                                    await asyncio.sleep(0.4)
                                    writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_train)))
                                    await writer.drain()
                                elif err_code == 145:
                                    print(f"        [!] Server rejected training for {cat_name}: Error 145 (Insufficient Resources / نقص الموارد للتدريب)")
                                    break
                                else:
                                    print(f"        [!] Server rejected training for {cat_name}: Error {err_code}")
                                    break
                if confirmed:
                    break
            except asyncio.TimeoutError:
                break
        await asyncio.sleep(0.1)

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

