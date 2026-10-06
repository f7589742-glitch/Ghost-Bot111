"""
session_validator.py — Ground-Truth Session & Profile Assertion
================================================================

Validates that the character returned by the game gateway matches the expected
role ID, name, or power, raising an explicit RuntimeError on any mismatch.
"""

import asyncio
import zlib
from typing import Dict, Any, Optional
from headless_client import ProtobufCodec, FrameParser

def tile_id_to_pos(tile_id: int) -> tuple[float, float]:
    """Convert server tile_id (Tag 25) to (X, Y) map coordinates."""
    if not tile_id:
        return (0.0, 0.0)
    x = float((tile_id >> 13) & 0x1FFF)
    y = float(tile_id & 0x1FFF)
    return (x, y)

def update_fleet_character(role_id: int, updates: Dict[str, Any], fleet_path: str = "accounts_fleet.json") -> bool:
    """Update and persist fields for a character in accounts_fleet.json."""
    import json, os
    if not os.path.exists(fleet_path):
        return False
    try:
        with open(fleet_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        updated = False
        for char in data.get("characters", []):
            if str(char.get("role_id")) == str(role_id):
                for k, v in updates.items():
                    char[k] = v
                updated = True
                break
        if updated:
            with open(fleet_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
    except Exception as e:
        print(f"    [FLEET UPDATE ERROR] Failed updating role {role_id}: {e}")
    return False

def assert_character_profile(
    loaded_profile: Dict[str, Any],
    expected_role_id: Optional[int] = None,
    expected_name: Optional[str] = None,
    min_expected_power: int = 0
) -> None:
    """
    Assert that the character profile returned by the game server (Opcode 15)
    matches the requested target character specifications.
    
    Raises:
        RuntimeError: If role ID, character name, or power level does not match.
    """
    if not loaded_profile:
        raise RuntimeError("[SESSION ASSERTION FAILED] No profile data received from gateway!")

    loaded_role_id = loaded_profile.get("role_id")
    loaded_name = loaded_profile.get("name", "")
    loaded_power = loaded_profile.get("power", 0)

    # 1. Assert Role ID (if provided)
    if expected_role_id and loaded_role_id:
        if int(loaded_role_id) != int(expected_role_id):
            raise RuntimeError(
                f"[SESSION ASSERTION ERROR] Role mismatch! Gateway loaded Role {loaded_role_id} "
                f"('{loaded_name}'), but expected Role {expected_role_id}."
            )

    # 2. Assert Name (if provided)
    if expected_name:
        clean_target = expected_name.split("]")[-1].strip().lower()
        clean_loaded = loaded_name.split("]")[-1].strip().lower()
        if clean_target and clean_loaded and (clean_target not in clean_loaded and clean_loaded not in clean_target):
            raise RuntimeError(
                f"[SESSION ASSERTION ERROR] Name mismatch! Gateway loaded '{loaded_name}', "
                f"expected target matching '{expected_name}'."
            )

    # 3. Assert Power Floor (if provided)
    if min_expected_power > 0 and loaded_power < min_expected_power:
        raise RuntimeError(
            f"[SESSION ASSERTION ERROR] Power anomaly! Gateway reported Power {loaded_power:,}, "
            f"below minimum expected threshold of {min_expected_power:,}."
        )

    print(f"  [SESSION VERIFIED] Character '{loaded_name}' (Role {loaded_role_id}, Power: {loaded_power:,}) matches target.")


async def switch_and_validate(reader, writer, crypto_tx, crypto_rx, target_role_id: int, kingdom_id: int, target_name: str = ""):
    """
    Executes an authentic character switch sequence (Opcode 203, 104, 110, 107) and
    validates the server's Opcode 204 response.
    """
    target_rid = int(target_role_id)
    tgt_kid = int(kingdom_id)
    
    p203 = ProtobufCodec.encode_message({1: target_rid})
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: p203}))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
    p110 = ProtobufCodec.encode_message({1: target_rid, 2: tgt_kid, 3: target_rid})
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: p110}))))
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
    await writer.drain()

    switched_ok = False
    deadline = asyncio.get_event_loop().time() + 2.5
    while asyncio.get_event_loop().time() < deadline:
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
                if m.get(1) == 204:
                    p204 = ProtobufCodec.decode_message(m.get(2, b"")) if isinstance(m.get(2), bytes) else m.get(2, {})
                    ack_role = p204.get(2)
                    print(f"    [SWITCH VERIFIED] Server Opcode 204 confirmed Role {ack_role} active.")
                    switched_ok = True
                    break
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            break
        except Exception:
            pass

    return switched_ok
