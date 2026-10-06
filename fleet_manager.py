"""
fleet_manager.py - Multi-Character Fleet Manager (Round-Robin)
Sequentially rotates through all enabled characters in accounts_fleet.json,
running a full train+gather cycle on each before moving to the next.
Loops continuously or runs once with --once.
"""

import asyncio
import json
import os
import sys
import time
import traceback

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "python"))
sys.path.insert(0, ROOT_DIR)

from smart_troop_trainer import train_troops_dynamically
from smart_gather_search import execute_smart_gather
from rokbot.protocol import build_login_frame
from headless_client import ProtobufCodec, FrameParser
import zlib

from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from cloud_role_switcher import ensure_character_active

FLEET_FILE = os.path.join(ROOT_DIR, "accounts_fleet.json")
CONFIG_FILE = os.path.join(ROOT_DIR, "bot_config.json")
FLEET_STATUS_FILE = os.path.join(ROOT_DIR, "fleet_status.json")

# -------------------------------------------------------------
# Fleet registry loader
# -------------------------------------------------------------

def load_fleet() -> list:
    """Load and return all enabled characters from accounts_fleet.json (supports flat, dict, or nested list schema)."""
    if not os.path.exists(FLEET_FILE):
        print(f"[!] Fleet file not found: {FLEET_FILE}")
        return []
    with open(FLEET_FILE, "r", encoding="utf-8") as f:
        fleet_raw = json.load(f)
    
    items = [fleet_raw] if isinstance(fleet_raw, dict) else fleet_raw
    char_list = []
    for item in items:
        if "characters" in item and isinstance(item["characters"], list):
            # Nested schema: Account -> Characters
            acc_token = item.get("access_token", "")
            app_uid = item.get("app_uid", "")
            server_id = item.get("server_id", "3105")
            server_id_int = int(item.get("server_id_int", 2104267))
            gate_host = item.get("gate_host", "43.159.113.101")
            port = int(item.get("port", 3101))
            acc_id = item.get("account_email") or item.get("account_id") or item.get("name", "acc")
            dev_udid = item.get("device_udid", "F682A5114F7DD6AD7995F8ED2D6719BA")
            
            for ch in item["characters"]:
                if ch.get("enabled", True):
                    merged = dict(ch)
                    merged["access_token"] = ch.get("access_token") or acc_token
                    merged["app_uid"] = ch.get("app_uid") or app_uid
                    merged["server_id"] = ch.get("kingdom_id", server_id)
                    merged["server_id_int"] = server_id_int
                    merged["gate_host"] = ch.get("gate_host") or gate_host
                    merged["port"] = int(ch.get("port") or port)
                    merged["account_id"] = acc_id
                    merged["device_udid"] = ch.get("device_udid") or dev_udid
                    char_list.append(merged)
        else:
            # Flat schema
            if item.get("enabled", True):
                char_list.append(item)

    print(f"[FLEET] Loaded {len(char_list)} enabled characters from fleet registry.")
    return char_list





# -------------------------------------------------------------
# City position auto-discovery (Opcode 15 field 25 → tile_id → X/Y)
# -------------------------------------------------------------

async def auto_discover_city_pos(char: dict) -> tuple:
    """
    Connect to gate, login + switch to char, read Opcode 15 field 25 (tile_id),
    decode X/Y coordinates, persist back to accounts_fleet.json and return (x, y).
    Returns (0, 0) on any failure.
    """
    role_id = int(char.get("role_id", 0))
    gate_host = char.get("gate_host", "43.159.113.101")
    gate_port = int(char.get("port", 3101))
    kingdom_id = int(char.get("kingdom_id", 11543))
    char_name = char.get("name", str(role_id))
    print(f"    [CITY DISCOVER] Auto-discovering city_pos for {char_name} (Role {role_id})...")
    try:
        reader, writer = await asyncio.open_connection(gate_host, gate_port)
        hdr = await reader.readexactly(2)
        g_len = (hdr[0] << 8) | hdr[1]
        g_payload = await reader.readexactly(g_len)
        g_fields = ProtobufCodec.decode_message(g_payload)
        sub = ProtobufCodec.decode_message(g_fields.get(2, b""))
        seed_tx, seed_rx = derive_seed(sub.get(1, 0), sub.get(2, 0))
        crypto_tx = RokCrypto(seed_tx)
        crypto_rx = RokCrypto(seed_rx)

        # Login
        login_bytes = resolve_login_bytes(char)
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(login_bytes)))
        # Switch character
        p203 = ProtobufCodec.encode_message({1: role_id})
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: p203}))))
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
        p110 = ProtobufCodec.encode_message({1: role_id, 2: kingdom_id, 3: role_id})
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: p110}))))
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
        await writer.drain()

        # Scan for Opcode 15 field 25 (tile_id encodes city X/Y)
        city_x, city_y = 0.0, 0.0
        found = False
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline and not found:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.5)
                rl = (rh[0] << 8) | rh[1]
                raw_p = await asyncio.wait_for(reader.readexactly(rl), timeout=0.5)
                dec = crypto_rx.decrypt(raw_p)
                z_idx = dec.find(b"\x78\x9c")
                if z_idx == -1: z_idx = dec.find(b"\x78\x01")
                data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
                msg = ProtobufCodec.decode_message(data)
                # Handle bundle packets (field 1 = list of sub-messages)
                candidates = []
                if isinstance(msg.get(1), list):
                    for chunk in msg.get(1):
                        if isinstance(chunk, bytes):
                            try: candidates.append(ProtobufCodec.decode_message(chunk))
                            except: pass
                else:
                    candidates.append(msg)
                for m in candidates:
                    if m.get(1) == 15:
                        payload15 = m.get(2)
                        if isinstance(payload15, bytes):
                            p15 = ProtobufCodec.decode_message(payload15)
                        else:
                            p15 = payload15 or {}
                        tile_id = p15.get(25, 0)
                        if tile_id and isinstance(tile_id, int) and tile_id > 0:
                            # Decode formula verified from AmmAr's tile_id=1779726945 → (184,697)
                            city_x = float((tile_id >> 13) & 0x1FFF)
                            city_y = float(tile_id & 0x1FFF)
                            print(f"    [CITY DISCOVER] {char_name}: tile_id={tile_id} → city_pos=({city_x}, {city_y})")
                            found = True
                            break
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                break
            except Exception:
                pass

        writer.close()
        try: await writer.wait_closed()
        except: pass

        if not found or (city_x == 0 and city_y == 0):
            print(f"    [CITY DISCOVER] Could not find Opcode 15 tile_id for {char_name}.")
            return (0.0, 0.0)

        # Persist back to accounts_fleet.json
        _save_city_pos_to_fleet(char.get("role_id"), city_x, city_y)
        return (city_x, city_y)

    except Exception as e:
        print(f"    [CITY DISCOVER] Error discovering city_pos for {char_name}: {e}")
        return (0.0, 0.0)


def _save_city_pos_to_fleet(role_id, x: float, y: float):
    """Persist a discovered city_pos back into accounts_fleet.json."""
    if not os.path.exists(FLEET_FILE):
        return
    try:
        with open(FLEET_FILE, "r", encoding="utf-8") as f:
            fleet_raw = json.load(f)
        changed = False
        target = [fleet_raw] if isinstance(fleet_raw, dict) else fleet_raw
        for item in target:
            for ch in item.get("characters", [item] if "role_id" in item else []):
                if str(ch.get("role_id")) == str(role_id):
                    ch["city_pos"] = [x, y]
                    changed = True
        if changed:
            with open(FLEET_FILE, "w", encoding="utf-8") as f:
                json.dump(fleet_raw, f, indent=2, ensure_ascii=False)
            print(f"    [CITY DISCOVER] Saved city_pos=[{x}, {y}] for role {role_id} to accounts_fleet.json")
    except Exception as e:
        print(f"    [CITY DISCOVER] Failed to save city_pos: {e}")


def load_bot_settings() -> dict:
    """Load training/gathering settings from bot_config.json (shared across all characters)."""
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    import re as _re
    city_cfg = cfg.get("city", {})
    train_cats = []
    if city_cfg.get("train_infantry", "Off") not in ("Off", False, None):
        train_cats.append("infantry")
    if city_cfg.get("train_cavalry", "Off") not in ("Off", False, None):
        train_cats.append("cavalry")
    if city_cfg.get("train_archers", "Off") not in ("Off", False, None):
        train_cats.append("archery")
    if city_cfg.get("train_siege", "Off") not in ("Off", False, None):
        train_cats.append("siege")

    gather_cfg = cfg.get("gathering", {})
    targets = []
    targets.extend(["food"] * int(gather_cfg.get("food_marches", 1)))
    targets.extend(["wood"] * int(gather_cfg.get("wood_marches", 1)))
    targets.extend(["stone"] * int(gather_cfg.get("stone_marches", 1)))
    targets.extend(["gold"] * int(gather_cfg.get("gold_marches", 0)))
    if not targets:
        targets = ["food", "wood", "stone"]

    lvl_raw = str(gather_cfg.get("max_node_level", "0"))
    m = _re.search(r"(\d+)", lvl_raw)
    target_lvl = int(m.group(1)) if m else 0

    gen_cfg = cfg.get("general", {})
    interval_h = float(gen_cfg.get("loop_interval_hours", 3.0))

    return {
        "train_categories": train_cats,
        "gather_targets": targets,
        "target_level": target_lvl,
        "interval_hours": interval_h,
    }

# -------------------------------------------------------------
# Telemetry / status writer
# -------------------------------------------------------------

def write_fleet_status(data: dict):
    try:
        with open(FLEET_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def read_fleet_status() -> dict:
    if os.path.exists(FLEET_STATUS_FILE):
        try:
            with open(FLEET_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# -------------------------------------------------------------
# -------------------------------------------------------------
# Dynamic Login Builder (Opcode 14) - Direct Role Injection
# -------------------------------------------------------------

def build_dynamic_login_payload(app_uid: str, access_token: str, role_id: int, device_id: str = "F682A5114F7DD6AD7995F8ED2D6719BA", kingdom_id: int = 11543, server_id_int: int = 2104267, public_ip: str = "") -> bytes:
    """
    Build authentic Android login frame (Opcode 14 / LoginRequest) with direct role injection.
    public_ip: egress IP from the SDK login response (f13/f22/f7). NEVER hardcode —
    a login claiming another network's IP risk-flags the session (writes 500).
    NOTE: official has NO f14 — removed 2026-09-13 (extra fields break binding).
    """
    server_int = int(server_id_int or 2104267)
    pip = (public_ip or "").strip() or "194.176.99.80"

    auth_payload = {
        1: str(app_uid).encode("utf-8"),
        2: str(access_token).encode("utf-8"),
        3: server_int,
        4: b"and",
        5: 1,
        6: int(role_id)
    }

    device_profile = {
        1: b"10043",
        2: b"com.lilithgame.roc.gp",
        3: b"self-lilith-0.7",
        4: b"",
        5: b"13c26fe3fb9d11b6",
        6: b"ee7df9d3-442c-4ad8-abed-9fc5f89928ba",
        7: pip.encode("utf-8"),
        8: b"android",
        9: b"14",
        10: b"1.1.11.25",
        11: b"2311DRK48C_Simulator",
        12: b"en",
        13: str(app_uid).encode("utf-8"),
        14: b"Redmi",
        15: b"OpenGL ES 3.1 v1",
        16: b"2993",
        17: b"Adreno (TM) 750",
        18: b"x86-64",
        19: b"1280",
        20: b"720",
        22: f"{pip}:50000".encode("utf-8"),
        23: str(device_id).encode("utf-8"),
        24: b"Qualcomm Technologies, Inc MSM8998"
    }

    inner = {
        1: 1,
        4: str(device_id).encode("utf-8"),
        6: ProtobufCodec.encode_message(device_profile),
        7: ProtobufCodec.encode_message(auth_payload),
        9: 1,
        11: b"1.1.11.25",
        12: b"628788",
        13: pip.encode("utf-8"),
        15: b"7",
        20: b"e5494c1f6aad311adc9b64f1288e9b8d",
        21: 18446744073709551615,
        23: b"rocgate.lilithgame.com:3101",
        24: 2,
        27: b"\x12\x00\n\x03and\"\x00\x1a\x00"
    }
    top = {1: 14, 2: ProtobufCodec.encode_message(inner)}
    return ProtobufCodec.encode_message(top)


def resolve_login_bytes(char: dict) -> bytes:
    """
    Build direct role login frame using build_dynamic_login_payload.
    """
    role_id = int(char.get("role_id", 0))
    token = str(char.get("access_token", ""))
    app_uid = str(char.get("app_uid", "256926538"))
    device_udid = char.get("device_udid", "F682A5114F7DD6AD7995F8ED2D6719BA")
    kingdom_id = int(char.get("kingdom_id", 11543))
    server_id_int = int(char.get("server_id_int", 2104267))

    if role_id and token:
        print(f"    [DIRECT LOGIN] Dispatching Opcode 14 for Role {role_id} (Kingdom {kingdom_id}, Cluster: {server_id_int}, Account UID: {app_uid})...")
        return build_dynamic_login_payload(
            app_uid=app_uid,
            access_token=token,
            role_id=role_id,
            device_id=device_udid,
            kingdom_id=kingdom_id,
            server_id_int=server_id_int,
            public_ip=str(char.get("public_ip", "") or ""),
        )

    raise RuntimeError(f"Cannot resolve login for character {char.get('id', '?')}: missing token or role_id")




# -------------------------------------------------------------
# Single character cycle
# -------------------------------------------------------------

async def run_character_cycle(char: dict, settings: dict, train_count: int = 200) -> dict:
    """
    Execute a full train + gather cycle for one character.
    Returns a result dict with timing and error info.
    """
    char_id = char.get("id", "unknown")
    char_name = char.get("name", char_id)
    role_id = int(char.get("role_id", 0))
    gate_host = char.get("gate_host", "43.159.113.101")
    gate_port = int(char.get("port", 3101))
    city_pos_raw = char.get("city_pos", [0, 0])
    city_pos = tuple(city_pos_raw) if isinstance(city_pos_raw, list) else city_pos_raw

    print("\n" + "=" * 70)
    print(f"  [*] CHARACTER: {char_name} (ID: {char_id}, Role: {role_id})")
    print(f"  [*] Server: {gate_host}:{gate_port} | City: {city_pos}")
    print("=" * 70)

    result = {
        "char_id": char_id,
        "char_name": char_name,
        "role_id": str(role_id),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "train_ok": False,
        "gather_ok": False,
        "error": None,
    }
    start_t = time.time()

    # Ensure target character is set as active on Lilith Cloud
    try:
        ensure_character_active(char)
    except Exception as e:
        print(f"  [WARN] Cloud switch attempt failed: {e}")

    try:
        login_bytes = resolve_login_bytes(char)
    except Exception as e:
        result["error"] = f"Login resolution failed: {e}"
        print(f"  [FAIL] {result['error']}")
        return result

    train_cats = settings["train_categories"]
    gather_targets = settings["gather_targets"]
    target_level = settings["target_level"]

    # Per-character barracks override (optional field in accounts_fleet.json)
    barracks_override = char.get("barracks_ids", None)

    kingdom_id = int(char.get("kingdom_id", 11543))

    # -- Phase 1: Train --
    if train_cats:
        print(f"\n  >>> [PHASE 1/2] Training: {', '.join(train_cats).upper()} ({train_count} each)")
        try:
            await train_troops_dynamically(
                target_type=train_cats,
                unit_count=train_count,
                gate_host=gate_host,
                gate_port=gate_port,
                login_bytes=login_bytes,
                barracks_override=barracks_override,
                target_role_id=role_id,
                kingdom_id=kingdom_id,
            )
            result["train_ok"] = True
            print("  [+] Training phase complete.")
        except Exception as e:
            print(f"  [-] Training error: {e}")
            result["error"] = f"Train: {e}"
    else:
        print("\n  >>> [PHASE 1/2] Training disabled in bot_config. Skipping.")
        result["train_ok"] = True  # not an error, just disabled

    await asyncio.sleep(2.0)

    # -- Phase 2: Gather --
    if city_pos == (0, 0) or city_pos == (0.0, 0.0):
        print(f"\n  >>> [PHASE 2/2] City position unknown for {char_name}. Auto-discovering...")
        discovered_pos = await auto_discover_city_pos(char)
        if discovered_pos != (0.0, 0.0):
            city_pos = discovered_pos
            print(f"      [POS DISCOVERED] Active location: {city_pos}")
        else:
            print(f"      Set city_pos in accounts_fleet.json to enable gathering.")
            result["gather_ok"] = True

    if city_pos != (0, 0) and city_pos != (0.0, 0.0) and gather_targets:
        print(f"\n  >>> [PHASE 2/2] Gathering: {', '.join(gather_targets).upper()}")
        try:
            await execute_smart_gather(
                march_targets=gather_targets,
                target_level=target_level,
                role_id=role_id,
                gate_host=gate_host,
                gate_port=gate_port,
                city_pos=city_pos,
                kingdom_id=kingdom_id,
            )
            result["gather_ok"] = True
            print("  [+] Gather phase complete.")
        except Exception as e:
            print(f"  [-] Gather error: {e}")
            if not result["error"]:
                result["error"] = f"Gather: {e}"

    elapsed = time.time() - start_t
    result["elapsed_sec"] = round(elapsed, 1)
    result["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    status_icon = "OK" if (result["train_ok"] and result["gather_ok"]) else "PARTIAL"
    print(f"\n  [{status_icon}] {char_name} finished in {elapsed:.1f}s")
    return result


# -------------------------------------------------------------
# Main fleet loop - round-robin
# -------------------------------------------------------------

def update_governor_status_in_config(role_id: str):
    """Updates last_run in bot_config.json for the given governor."""
    if not os.path.exists(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for acc in cfg.get("accounts", []):
            for gov in acc.get("governors", []):
                if str(gov.get("id")) == str(role_id):
                    gov["last_run"] = "just now"
                    gov["next_run"] = "in 3h"
                    acc["last_run"] = "just now"
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

async def run_fleet(run_once: bool = False, train_count: int = 200, target_char: str = None):
    round_num = 0

    while True:
        round_num += 1
        fleet = load_fleet()
        if target_char:
            tc = str(target_char).strip().lower()
            fleet = [c for c in fleet if (
                tc == str(c.get("id", "")).lower()
                or tc == str(c.get("role_id", ""))
                or tc in str(c.get("name", "")).lower()
                or tc == str(c.get("kingdom_id", ""))
                or tc == str(c.get("display_kingdom", ""))
            )]
            if not fleet:
                print(f"[!] Target character '{target_char}' not found or disabled in fleet.")
                break

        if not fleet:
            print("[!] No enabled characters in fleet. Nothing to do.")
            break

        settings = load_bot_settings()
        interval_hours = settings["interval_hours"]
        interval_seconds = int(interval_hours * 3600)

        print("\n" + "=" * 70)
        print(f"  FLEET ROUND #{round_num} - {len(fleet)} CHARACTERS")
        print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)

        round_start = time.time()
        results = []

        status = {
            "round": round_num,
            "total_chars": len(fleet),
            "current_index": 0,
            "current_char": "",
            "state": "running",
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": [],
        }
        write_fleet_status(status)

        for idx, char in enumerate(fleet):
            char_id = char.get("id", f"char_{idx}")
            char_name = char.get("name", char_id)

            status["current_index"] = idx + 1
            status["current_char"] = f"{char_name} ({char_id})"
            write_fleet_status(status)

            res = await run_character_cycle(char, settings, train_count=train_count)
            results.append(res)
            update_governor_status_in_config(str(char.get("role_id", "")))

            status["results"] = results
            write_fleet_status(status)

            # Small cooldown between characters to avoid server rate-limit
            if idx < len(fleet) - 1:
                print(f"\n  [COOLDOWN] 5s pause before next character...")
                await asyncio.sleep(5.0)

        # -- Round summary --
        round_elapsed = time.time() - round_start
        ok_count = sum(1 for r in results if r["train_ok"] and r["gather_ok"])
        fail_count = len(results) - ok_count

        print("\n" + "=" * 70)
        print(f"  FLEET ROUND #{round_num} COMPLETE")
        print(f"  Characters: {ok_count} OK, {fail_count} with issues")
        print(f"  Total time: {round_elapsed:.1f}s ({round_elapsed/60:.1f} min)")
        print("=" * 70)

        next_run_ts = time.time() + interval_seconds
        status["state"] = "done" if run_once else "sleeping"
        status["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        status["round_elapsed_sec"] = round(round_elapsed, 1)
        status["ok_count"] = ok_count
        status["fail_count"] = fail_count
        if not run_once:
            status["next_run"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(next_run_ts))
        write_fleet_status(status)

        if run_once:
            print(f"\n[FLEET] Single round completed. Exiting.")
            break

        # -- Sleep until next round --
        print(f"\n[FLEET] Next round at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(next_run_ts))}")
        print(f"[FLEET] Sleeping {interval_hours}h...")

        while time.time() < next_run_ts:
            remaining = int(next_run_ts - time.time())
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            seconds = remaining % 60

            if remaining % 300 == 0 or remaining in (1800, 600, 300, 60, 30, 10):
                print(f"    [STANDBY] Next fleet round in: {hours:02d}h {minutes:02d}m {seconds:02d}s...")
                status["state"] = f"sleeping ({hours:02d}h {minutes:02d}m)"
                write_fleet_status(status)

            await asyncio.sleep(1.0)


# -------------------------------------------------------------
# CLI entry
# -------------------------------------------------------------

def main():
    run_once = "--once" in sys.argv or "-1" in sys.argv
    train_count = 200
    target_char = None

    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--char" and i + 1 < len(sys.argv):
            target_char = sys.argv[i + 1]
            i += 2
            continue
        elif a.isdigit() and int(a) <= 10000:
            train_count = int(a)
        i += 1

    if "--list" in sys.argv:
        fleet = load_fleet()
        print("=" * 70)
        print(f"  REGISTERED FLEET CHARACTERS ({len(fleet)} Total)")
        print("=" * 70)
        for idx, ch in enumerate(fleet):
            dk = ch.get("display_kingdom", ch.get("kingdom_id", "?"))
            pwr = ch.get("power", 0)
            status = "ENABLED" if ch.get("enabled", True) else "DISABLED"
            print(f"  [{idx+1}] {ch.get('name', 'Unknown'):<22} | Role: {ch.get('role_id'):<10} | KD: #{dk:<5} | Power: {pwr:>10,} | [{status}]")
        print("=" * 70)
        return

    mode_str = f"Single Character ({target_char})" if target_char else ("Single Round" if run_once else "Continuous Loop")
    print("=" * 70)
    print("  FLEET MANAGER - Multi-Character Round-Robin Engine")
    print(f"  Mode: {mode_str}")
    print(f"  Train count per barracks: {train_count}")
    print("=" * 70)

    try:
        asyncio.run(run_fleet(run_once=run_once or bool(target_char), train_count=train_count, target_char=target_char))
    except KeyboardInterrupt:
        print("\n[!] Fleet Manager halted by user.")
        if os.path.exists(FLEET_STATUS_FILE):
            try:
                s = read_fleet_status()
                s["state"] = "stopped"
                write_fleet_status(s)
            except Exception:
                pass


if __name__ == "__main__":
    main()
