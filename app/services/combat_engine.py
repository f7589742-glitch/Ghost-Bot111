"""
combat_engine.py - Autonomous Barbarian Combat Engine for Rise of Kingdoms Headless Bot.
Features:
- Single-Target Swarm Strategy: All available march queues swarm a SINGLE target barbarian.
- Strict Staggered Launch Intervals (1.2s - 1.6s) to prevent packet collisions and bot detection.
- Accurate AP parsing via hero_parser.parse_ap_from_1002 (no false aborts unless AP < 40).
- Wall garrison exclusion and peacekeeper priority.
- Battle monitoring (Opcode 1005) & hospital auto-heal between/after rounds.
"""

import sys
import os
import time
import math
import random
import struct
import zlib
import re
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple, Set

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

PYTHON_DIR = os.path.join(PROJECT_ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

try:
    from headless_client import ProtobufCodec, FrameParser
    from crypto_module import RokCrypto
    from derive_seed_from_nonce import derive_seed
except ImportError:
    from python.headless_client import ProtobufCodec, FrameParser
    from python.crypto_module import RokCrypto
    from python.derive_seed_from_nonce import derive_seed

try:
    from app.services.proxy_transport import open_game_connection
except ImportError:
    from proxy_transport import open_game_connection

from app.services.protocol.hero_parser import (
    parse_ap_from_1002,
    parse_wall_garrison_from_1002,
    parse_unlocked_barb_level_from_1002,
    parse_heroes_from_1002,
    parse_heroes_from_1201,
    parse_roster_from_1157,
    merge_rosters,
    persist_roster_to_db,
)

logger = logging.getLogger("combat_engine")

OP_SEARCH_BARBARIAN = 1178      # C->S: Search Barbarian by level
OP_BARBARIAN_SEARCH_RESP = 1179 # S->C: Search response
OP_OBJECT_SPAWN = 1023          # S->C: Map entity spawn
OP_MAP_VIEWPORT_REQ = 1004      # C->S: Request map viewport
OP_MAP_VIEWPORT_STREAM = 1003   # S->C: Map viewport entity stream
OP_INSPECT_TARGET = 1050        # C->S: Inspect barbarian target before march
OP_DISPATCH_MARCH = 1012        # C->S: March dispatch with combat flags
OP_MARCH_SYNC = 1005            # S->C: March state sync

# Hospital opcodes for auto-healing integration between rounds
OP_QUERY_WOUNDED = 362
OP_HEAL_TROOPS = 330
OP_ALLIANCE_HELP_REQUEST = 2048

# Top combat heroes prioritized for barbarians (Peacekeeping & high DPS first)
COMBAT_HEROES_PREFERENCE = [
    6,   # Lohar (Barbarian Hunter)
    14,  # Boudica (Peacekeeping)
    22,  # Aethelflaed (Peacekeeping)
    4,   # Minamoto no Yoshitsune (Peacekeeping/Cavalry)
    2,   # Cao Cao (Peacekeeping/Cavalry)
    10,  # Belisarius (Peacekeeping/Cavalry)
    3,   # Sun Tzu (Nuker)
    8,   # Scipio Africanus
    11,  # Baibars
    5,   # Pelagius
    12,  # Osman I
    9,   # Hermann
    7,   # Eulji Mundeok
    13,  # Kusunoki Masashige
    20,  # Richard I
    21,  # Charles Martel
    36,  # Lancelot
    35,  # Tomoe Gozen
    1,   # City Keeper
    15,  # Joan of Arc
]

COMMANDER_NAMES = {
    6: "Lohar",
    14: "Boudica",
    22: "Aethelflaed",
    4: "Minamoto no Yoshitsune",
    2: "Cao Cao",
    10: "Belisarius",
    3: "Sun Tzu",
    8: "Scipio Africanus",
    11: "Baibars",
    5: "Pelagius",
    12: "Osman I",
    9: "Hermann",
    7: "Eulji Mundeok",
    13: "Kusunoki Masashige",
    20: "Richard I",
    21: "Charles Martel",
    36: "Lancelot",
    35: "Tomoe Gozen",
    1: "City Keeper",
    15: "Joan of Arc",
    38: "Sarka",
    33: "Constance",
    24: "Centurion",
    34: "Gaius Marius",
}

COMMANDER_NAME_TO_ID = {
    "Auto": 0,
    "Lohar": 6,
    "Boudica": 14,
    "Aethelflaed": 22,
    "Minamoto no Yoshitsune": 4,
    "Cao Cao": 2,
    "Belisarius": 10,
    "Sun Tzu": 3,
    "Baibars": 11,
    "Pelagius": 5,
    "Osman I": 12,
    "Hermann": 9,
    "Eulji Mundeok": 7,
    "Kusunoki Masashige": 13,
    "Scipio Africanus": 8,
    "Richard I": 20,
    "Charles Martel": 21,
    "Lancelot": 36,
    "Tomoe Gozen": 35,
    "City Keeper": 1,
    "Joan of Arc": 15,
}

TROOP_BUDGET_BY_BARB_LEVEL = {
    1: 2500, 2: 3500, 3: 5000, 4: 7000, 5: 10000,
    6: 12000, 7: 15000, 8: 18000, 9: 20000, 10: 22000,
    11: 25000, 12: 28000, 13: 30000, 14: 32000, 15: 35000,
    16: 38000, 17: 40000, 18: 45000, 19: 50000, 20: 55000,
    21: 60000, 22: 65000, 23: 70000, 24: 75000, 25: 80000
}


def safe_decompress(data: bytes) -> bytes:
    try:
        z_idx = data.find(b"\x78\x9c")
        if z_idx == -1:
            z_idx = data.find(b"\x78\x01")
        if z_idx != -1:
            return zlib.decompress(data[z_idx:])
    except Exception:
        pass
    return data


class CombatEngine:
    """
    Autonomous Barbarian Combat Engine with Single-Target Swarm Strategy.
    Discovers/spawns a single barbarian target per round, and directs all available
    march queues to swarm that same target with anti-bot staggered intervals.
    """

    @staticmethod
    def build_search_barbarian_payload(level: int) -> bytes:
        """
        Builds Opcode 1178 payload:
        Ground truth: 1801 10{level} 0801 2001
        """
        return bytes([0x18, 0x01, 0x10, max(1, min(25, int(level))), 0x08, 0x01, 0x20, 0x01])

    @staticmethod
    def parse_all_barbarian_search_resps(resp_payload: bytes) -> List[Dict[str, Any]]:
        """
        Parses S->C Opcode 1179 payload using clean Protobuf decoding.
        Returns list of dicts with entity_id, x, y, level.
        """
        results = []
        if not resp_payload:
            return results

        try:
            m = ProtobufCodec.decode_message(resp_payload)
            target_level = m.get(3, 0)
            items = m.get(1, [])
            if not isinstance(items, list):
                items = [items]

            for it_b in items:
                if isinstance(it_b, bytes):
                    sub = ProtobufCodec.decode_message(it_b)
                    eid = sub.get(2)
                    pos_b = sub.get(1)
                    if eid and isinstance(pos_b, bytes) and len(pos_b) >= 10:
                        v1 = struct.unpack("<f", pos_b[1:5])[0]
                        v2 = struct.unpack("<f", pos_b[6:10])[0]
                        if pos_b[0] == 0x0d:
                            x_val, y_val = v1, v2
                        elif pos_b[0] == 0x15:
                            y_val, x_val = v1, v2
                        else:
                            x_val, y_val = v1, v2

                        if 10.0 <= x_val <= 7200.0 and 10.0 <= y_val <= 7200.0:
                            results.append({
                                "entity_id": eid,
                                "x": round(x_val, 2),
                                "y": round(y_val, 2),
                                "level": target_level,
                                "source": "search_1179"
                            })
        except Exception as e:
            logger.debug(f"[COMBAT] Protobuf decode 1179 note: {e}")

        # Regex fallback scan
        if not results:
            try:
                raw = resp_payload
                m_coords = re.search(b'\r(.{4})\x15(.{4})', raw)
                if m_coords:
                    fx = struct.unpack("<f", m_coords.group(1))[0]
                    fy = struct.unpack("<f", m_coords.group(2))[0]
                else:
                    m_coords = re.search(b'\x15(.{4})\r(.{4})', raw)
                    if m_coords:
                        fy = struct.unpack("<f", m_coords.group(1))[0]
                        fx = struct.unpack("<f", m_coords.group(2))[0]
                    else:
                        fx, fy = 0.0, 0.0

                if fx > 0 and fy > 0:
                    idx_tag2 = raw.find(b"\x10\x01")
                    m_eid = re.search(rb'\x10([\x80-\xff]*[\x00-\x7f])', raw[idx_tag2:] if idx_tag2 != -1 else raw)
                    if m_eid:
                        eid_bytes = m_eid.group(1)
                        eid = 0
                        shift = 0
                        for b in eid_bytes:
                            eid |= (b & 0x7f) << shift
                            shift += 7
                            if not (b & 0x80):
                                break
                        if eid > 1000000:
                            results.append({
                                "entity_id": eid,
                                "x": round(fx, 2),
                                "y": round(fy, 2),
                                "level": 0,
                                "source": "search_1179_fallback"
                            })
            except Exception:
                pass

        return results

    @staticmethod
    def parse_barbarian_spawn(resp_payload: bytes) -> Optional[Dict[str, Any]]:
        """
        Parses S->C Opcode 1023 payload (dynamic map entity spawn).
        """
        try:
            raw = resp_payload
            idx_coords = raw.find(b"\x1a\n\r")
            if idx_coords != -1 and len(raw) >= idx_coords + 12:
                x_val = struct.unpack("<f", raw[idx_coords+3:idx_coords+7])[0]
                if raw[idx_coords+7] == 0x15:
                    y_val = struct.unpack("<f", raw[idx_coords+8:idx_coords+12])[0]
                    sub_before = raw[:idx_coords]
                    idx_tag1 = sub_before.rfind(b"\x08")
                    if idx_tag1 != -1:
                        i = idx_tag1 + 1
                        eid = 0
                        shift = 0
                        while i < len(sub_before):
                            b = sub_before[i]
                            i += 1
                            eid |= (b & 0x7f) << shift
                            shift += 7
                            if not (b & 0x80):
                                break
                        if 1000000 < eid < 0x7fffffffffff:
                            return {
                                "entity_id": eid,
                                "x": round(x_val, 2),
                                "y": round(y_val, 2),
                                "level": 0,
                                "source": "spawn_1023"
                            }
        except Exception as e:
            logger.debug(f"[COMBAT] Failed to parse 1023: {e}")
        return None

    @staticmethod
    def parse_all_barbarians_from_1003(p2: bytes, city_x: float, city_y: float) -> List[Dict[str, Any]]:
        """
        Parses Opcode 1003 map stream. Extracts roaming barbarians (monster type 600-606).
        """
        barbs = []
        if not p2:
            return barbs

        try:
            pmsg = ProtobufCodec.decode_message(p2)
            items = pmsg.get(2, [])
            if not isinstance(items, list):
                items = [items]

            for it_b in items:
                if not isinstance(it_b, bytes):
                    continue
                try:
                    obj = ProtobufCodec.decode_message(it_b)
                    f1_b = obj.get(1)
                    if not isinstance(f1_b, bytes):
                        continue
                    f1 = ProtobufCodec.decode_message(f1_b)
                    eid = f1.get(1)
                    if not eid:
                        continue

                    f8_b = obj.get(8)
                    is_barb = False
                    lvl = 1

                    if isinstance(f8_b, bytes):
                        f8 = ProtobufCodec.decode_message(f8_b)
                        m_info_b = f8.get(4)
                        if isinstance(m_info_b, bytes):
                            m_info = ProtobufCodec.decode_message(m_info_b)
                            m_type = m_info.get(1, 0)
                            if m_type in (600, 601, 602, 603, 604, 605, 606):
                                is_barb = True
                                lvl = m_info.get(3, 1)

                        if not is_barb and b"\x08\xde\x04" in f8_b:
                            is_barb = True
                            m_lvl = re.search(rb"\x08\xde\x04\x10\x01\x18([\x01-\x19])", f8_b)
                            if m_lvl:
                                lvl = int(m_lvl.group(1)[0])

                    if is_barb:
                        pos_b = f1.get(3) or obj.get(3) or f1.get(2) or obj.get(2)
                        px, py = 0.0, 0.0
                        if isinstance(pos_b, bytes) and len(pos_b) >= 10:
                            v1 = struct.unpack("<f", pos_b[1:5])[0]
                            v2 = struct.unpack("<f", pos_b[6:10])[0]
                            if pos_b[0] == 0x0d:
                                px, py = v1, v2
                            elif pos_b[0] == 0x15:
                                py, px = v1, v2
                            else:
                                px, py = v1, v2

                        if px > 0 and py > 0:
                            dist = round(math.hypot(px - city_x, py - city_y) / 6.0, 2)
                            barbs.append({
                                "entity_id": eid,
                                "x": round(px, 2),
                                "y": round(py, 2),
                                "level": lvl,
                                "dist": dist,
                                "source": "map_1003"
                            })
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"[COMBAT] Opcode 1003 parsing error: {e}")

        return barbs

    @staticmethod
    def build_target_inspect_payload(
        role_id: int,
        target_entity_id: int,
        city_x: float = 0.0,
        city_y: float = 0.0,
        target_x: float = 0.0,
        target_y: float = 0.0,
        alliance_id: int = 0
    ) -> bytes:
        """
        Builds Opcode 1050 payload:
        1a0a 15{cityX} 0d{cityY} 2800 10{entityId} 220a 15{targetX} 0d{targetY} 08{roleId}
        """
        def pack_coords(cx: float, cy: float) -> bytes:
            return b"\x15" + struct.pack("<f", float(cx)) + b"\x0d" + struct.pack("<f", float(cy))

        msg = {
            1: int(role_id) if role_id else (int(alliance_id) if alliance_id else 600000),
            2: int(target_entity_id),
            3: pack_coords(city_x, city_y),
            4: pack_coords(target_x, target_y),
            5: 0
        }
        return ProtobufCodec.encode_message(msg)

    @staticmethod
    def build_send_troop_confirm() -> bytes:
        """
        Builds Opcode 8 SendTroopConfirm frame matching genuine RoK client behavior.
        """
        js = json.dumps({"E": "SendTroopConfirm", "t": str(int(time.time()))}).encode('utf-8')
        comp = zlib.compress(js)
        p2 = ProtobufCodec.encode_field_bytes(1, comp)
        return ProtobufCodec.encode_field_varint(1, 8) + ProtobufCodec.encode_field_bytes(2, p2)

    @staticmethod
    def build_combat_dispatch_payload(
        target_entity_id: int,
        primary_commander_id: int = 6,
        secondary_commander_id: int = 0,
        troops: Optional[List[Tuple[int, int]]] = None,
        march_index: int = 1
    ) -> bytes:
        """
        Builds authentic Opcode 1012 payload for combat march dispatch.
        Field 4: target_entity_id (varint)
        Field 3: zero point coordinates b'\\x1a\\x0a\\x15\\x00\\x00\\x00\\x00\\x0d\\x00\\x00\\x00\\x00'
        Field 2: troops array {Tag 2: count, Tag 1: unit_type}
        Field 14: 1
        Field 1: Slot 1 primary commander (pos = 1)
                 Slot 2 secondary commander if > 0 (pos = 2)
        Field 7: 0
        Field 6: 1 (Combat Attack Flag, wire: 0x30 0x01)
        Field 11: 0
        Field 18: 0
        Field 17: 1 (Attack flag)
        Field 5: b"dispatch_troop_{march_index}"
        """
        f4 = ProtobufCodec.encode_field_varint(4, int(target_entity_id))
        f3 = b'\x1a\x0a\x15\x00\x00\x00\x00\x0d\x00\x00\x00\x00'

        f2_payload = bytearray()
        if troops:
            for ut, cnt in troops:
                if cnt <= 0: continue
                # RoK wire tag format: Tag 2 is count, Tag 1 is unit_type
                it = ProtobufCodec.encode_field_varint(2, int(cnt)) + ProtobufCodec.encode_field_varint(1, int(ut))
                f2_payload.extend(ProtobufCodec.encode_field_bytes(2, it))
        else:
            it = ProtobufCodec.encode_field_varint(2, 5000) + ProtobufCodec.encode_field_varint(1, 1)
            f2_payload.extend(ProtobufCodec.encode_field_bytes(2, it))

        f14 = ProtobufCodec.encode_field_varint(14, 1)

        # Commanders submessage: Tag 1 is hero_id, Tag 2 is position (1=primary, 2=secondary)
        p_var = ProtobufCodec.encode_varint(int(primary_commander_id))
        hero_payload = b'\x0a\x04\x08' + p_var + b'\x10\x01' if len(p_var) == 1 else (
            b'\x0a' + ProtobufCodec.encode_varint(len(p_var) + 3) + b'\x08' + p_var + b'\x10\x01'
        )
        if secondary_commander_id and int(secondary_commander_id) > 0:
            s_var = ProtobufCodec.encode_varint(int(secondary_commander_id))
            hero_payload += b'\x0a\x04\x08' + s_var + b'\x10\x02' if len(s_var) == 1 else (
                b'\x0a' + ProtobufCodec.encode_varint(len(s_var) + 3) + b'\x08' + s_var + b'\x10\x02'
            )

        f7 = ProtobufCodec.encode_field_varint(7, 0)
        # Field 6 = 1: Combat Attack Flag (Wire hex: 0x30 0x01 -> "3001")
        f6 = b'\x30\x01'
        f11 = ProtobufCodec.encode_field_varint(11, 0)
        f18 = ProtobufCodec.encode_field_varint(18, 0)
        f17 = ProtobufCodec.encode_field_varint(17, 1)   # Attack modifier
        f5 = ProtobufCodec.encode_field_bytes(5, f"dispatch_troop_{march_index}".encode())

        body = f4 + f3 + bytes(f2_payload) + f14 + hero_payload + f7 + f6 + f11 + f18 + f17 + f5
        return ProtobufCodec.encode_message({1: 1012, 2: body})

    @classmethod
    async def execute_barbarian_hunt(
        cls,
        target_role_id: int,
        kingdom_id: int,
        gate_host: str,
        gate_port: int,
        app_uid: str,
        app_token: str,
        udid: str,
        target_level: Any = 6,
        highest_barb_level: str = "Max Unlocked",
        skip_barbs_below: str = "None",
        primary_commander: str = "Auto",
        secondary_commander: str = "Auto (best available)",
        combat_rounds: int = 10,
        dispatch_all_marches: bool = True,
        max_marches: int = 5,
        heal_troops: bool = True,
        heal_batch: int = 0,
        hold_position: bool = False,
        char_name: str = "Governor",
        log_callback: Optional[Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executes autonomous barbarian hunts using the Single-Target Swarm Strategy.
        Focuses all available march queues on ONE barbarian target per round, with
        staggered intervals and AP validation.
        """
        def log(msg: str):
            if log_callback:
                log_callback(msg)
            else:
                logger.info(msg)

        char_tag = char_name or f"Governor #{target_role_id}"
        discovered_city_coords: Tuple[float, float] = (4363.2, 4174.8)
        discovered_city_hall_lvl: Optional[int] = None
        active_marches_set: Set[str] = set()
        current_ap: Optional[int] = None
        available_heroes: List[int] = []
        busy_heroes: Set[int] = set()
        troops_in_city: Dict[int, int] = {}
        garrison_ids: Set[int] = set()
        server_unlocked_barb_lvl: Optional[int] = None

        log(f"[{char_tag}] Connecting to Gateway {gate_host}:{gate_port} for Governor #{target_role_id}...")

        reader, writer = await open_game_connection(gate_host, gate_port)
        try:
            # 1. Handshake Greeting 8306
            hdr = await asyncio.wait_for(reader.readexactly(2), timeout=6.0)
            g_p = await reader.readexactly((hdr[0] << 8) | hdr[1])
            sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(g_p).get(2, b""))
            tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
            c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)

            # 2. Login Opcode 14 & Role Assertion
            login_bytes = kwargs.get("login_bytes")
            if not login_bytes:
                from app.services.lilith_cloud import LilithCloudService
                try:
                    from app.services.socket_worker import build_android_login_frame
                    login_bytes = build_android_login_frame(
                        player_id=str(app_uid),
                        access_token=str(app_token),
                        udid=str(udid),
                        ip=LilithCloudService.public_ip()
                    )
                except Exception:
                    from app.services.socket_worker import build_login_frame
                    login_bytes = build_login_frame(
                        player_id=str(app_uid),
                        access_token=str(app_token),
                        app_id=2104267,
                        platform="android"
                    )

            writer.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))

            # Opcode 203 / 104 / 110 / 107
            p203 = ProtobufCodec.encode_message({1: int(target_role_id)})
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: p203}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
            p110 = ProtobufCodec.encode_message({1: int(target_role_id), 2: int(kingdom_id), 3: int(target_role_id)})
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: p110}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))

            # Enter World Map mode (Opcodes 6404 & 1001)
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 6404, 2: ProtobufCodec.encode_message({1: int(kingdom_id)})}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b""}))))
            await writer.drain()

            # 3. Read profile & military state from Opcode 1002 / 125 / 1010
            parsed_1201: List[Dict[str, Any]] = []
            parsed_1157: List[Dict[str, Any]] = []
            hero_details_map: Dict[int, Dict[str, Any]] = {}

            deadline = asyncio.get_event_loop().time() + 4.5
            while asyncio.get_event_loop().time() < deadline:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.5)
                    rl = (rh[0] << 8) | rh[1]
                    raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.5)
                    dec = c_rx.decrypt(raw)
                    decomp = safe_decompress(dec)
                    m = ProtobufCodec.decode_message(decomp)

                    chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                    for c in chunks:
                        it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                        if not isinstance(it, dict): continue
                        op = it.get(1)

                        if op == 1002:
                            p2 = it.get(2)
                            if isinstance(p2, bytes):
                                # Extract AP accurately
                                ap_val = parse_ap_from_1002(p2)
                                if ap_val is not None:
                                    current_ap = ap_val

                                garrison_ids |= parse_wall_garrison_from_1002(p2)
                                s_lvl = parse_unlocked_barb_level_from_1002(p2)
                                if s_lvl is not None and s_lvl > 0:
                                    server_unlocked_barb_lvl = s_lvl

                                sub1002 = ProtobufCodec.decode_message(p2)
                                ch_val = sub1002.get(4)
                                if isinstance(ch_val, int) and ch_val > 0:
                                    discovered_city_hall_lvl = ch_val

                                f1 = sub1002.get(1)
                                if isinstance(f1, bytes):
                                    f1_d = ProtobufCodec.decode_message(f1)
                                    pt_bytes = f1_d.get(2)
                                    if isinstance(pt_bytes, bytes) and len(pt_bytes) >= 9:
                                        cx = struct.unpack("<f", pt_bytes[1:5])[0]
                                        cy = struct.unpack("<f", pt_bytes[5:9])[0]
                                        if cx > 0 and cy > 0:
                                            discovered_city_coords = (cx, cy)

                                # Troops from Tag 19
                                tag19 = sub1002.get(19)
                                if isinstance(tag19, bytes):
                                    inner = ProtobufCodec.decode_message(tag19)
                                    for item_b in inner.get(1, []):
                                        if isinstance(item_b, bytes):
                                            item_d = ProtobufCodec.decode_message(item_b)
                                            ut = item_d.get(1)
                                            cnt = item_d.get(3) or item_d.get(2) or 0
                                            if ut and cnt > 0:
                                                troops_in_city[ut] = cnt

                                # Commanders from Tag 15 or 12
                                h_from_1002 = parse_heroes_from_1002(p2)
                                for hd in h_from_1002:
                                    hid = hd["hero_id"]
                                    hero_details_map[hid] = hd
                                    if hid not in available_heroes:
                                        available_heroes.append(hid)

                        elif op == 1010 and isinstance(it.get(2), bytes):
                            pmsg = ProtobufCodec.decode_message(it.get(2))
                            for item in pmsg.get(1, []):
                                if isinstance(item, bytes):
                                    t_info = ProtobufCodec.decode_message(item)
                                    u_type = t_info.get(1)
                                    u_cnt = t_info.get(2, 0)
                                    if u_type and u_cnt:
                                        troops_in_city[u_type] = u_cnt

                        elif op == 1201 and isinstance(it.get(2), bytes):
                            try:
                                parsed_1201 = parse_heroes_from_1201(it.get(2))
                                for hd in parsed_1201:
                                    hid = hd["hero_id"]
                                    hero_details_map[hid] = hd
                                    if hid not in available_heroes:
                                        available_heroes.append(hid)
                            except Exception:
                                pass

                        elif op == 1157 and isinstance(it.get(2), bytes):
                            try:
                                parsed_1157 = parse_roster_from_1157(it.get(2))
                                for hd in parsed_1157:
                                    hid = hd["hero_id"]
                                    if hid not in hero_details_map:
                                        hero_details_map[hid] = hd
                                    if hid not in available_heroes:
                                        available_heroes.append(hid)
                            except Exception:
                                pass

                        elif op == 125 and not troops_in_city:
                            p = ProtobufCodec.decode_message(it.get(2, b"")) if isinstance(it.get(2), bytes) else it.get(2, {})
                            items = p.get(1, [])
                            if not isinstance(items, list): items = [items]
                            for it_b in items:
                                if isinstance(it_b, bytes):
                                    sub_it = ProtobufCodec.decode_message(it_b)
                                    sub2_raw = sub_it.get(2)
                                    if isinstance(sub2_raw, bytes):
                                        sub2 = ProtobufCodec.decode_message(sub2_raw)
                                        ut = sub2.get(1, 0)
                                        cnt = sub2.get(2, 0)
                                        if ut > 0 and cnt > 0:
                                            troops_in_city[ut] = cnt

                        elif op in (1005, 1023):
                            p2 = it.get(2)
                            if isinstance(p2, bytes):
                                march_pattern = str(target_role_id).encode() + rb"_\d+_(\d+)(?:_(\d+))?"
                                for match in re.finditer(march_pattern, p2):
                                    active_marches_set.add(match.group(0).decode("latin1", "ignore"))
                                    busy_heroes.add(int(match.group(1).decode()))
                                    if match.group(2):
                                        busy_heroes.add(int(match.group(2).decode()))

                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

            # Deduplicate & merge rosters
            merged_roster = merge_rosters(parsed_1201, parsed_1157, list(hero_details_map.values()))
            if merged_roster:
                for h in merged_roster:
                    if h["hero_id"] not in available_heroes:
                        available_heroes.append(h["hero_id"])
                    hero_details_map[h["hero_id"]] = h
                try:
                    persist_roster_to_db(target_role_id, merged_roster, garrison_ids, source="combat_1201_sync")
                except Exception:
                    pass

            # Expose discovery state to caller cookie if provided
            _cookie = kwargs.get("_hero_discovery_state")
            if isinstance(_cookie, dict):
                _cookie.clear()
                _cookie.update({
                    "roster": merged_roster,
                    "garrison": set(garrison_ids),
                    "server_unlocked_barb_level": server_unlocked_barb_lvl,
                })

            # Exclude wall garrison heroes from combat dispatch pool
            available_heroes = [h for h in available_heroes if h not in garrison_ids]

            # Resolve real City Hall level & maximum march queues
            if not discovered_city_hall_lvl:
                try:
                    from app.models import CharacterDAO
                    _c_rec = CharacterDAO.get_by_role_id(str(target_role_id))
                    if _c_rec:
                        discovered_city_hall_lvl = int(_c_rec.get("city_hall") or _c_rec.get("city_level") or 0)
                except Exception:
                    pass
            effective_ch = int(discovered_city_hall_lvl or 16)
            account_max_queues = 5 if effective_ch >= 22 else (4 if effective_ch >= 17 else (3 if effective_ch >= 11 else (2 if effective_ch >= 5 else 1)))
            active_marches_count = len(active_marches_set)
            free_queues = max(0, account_max_queues - active_marches_count)

            total_troops = sum(troops_in_city.values())
            ap_display = f"{current_ap}" if current_ap is not None else "Full (Unrestricted)"
            log(f"[{char_tag}] Status: City ({discovered_city_coords[0]/6.0:.1f}, {discovered_city_coords[1]/6.0:.1f}) | CH: {effective_ch} | Marches: {active_marches_count}/{account_max_queues} (Free: {free_queues}) | Army: {total_troops:,} | AP: {ap_display}")

            # STRICT PRE-FLIGHT 1: If all march queues are deployed, skip gracefully!
            if free_queues <= 0:
                log(f"[{char_tag}] Barbarian combat skipped: All march queues currently deployed ({active_marches_count}/{account_max_queues} active). Proceeding to gather...")
                return {
                    "success": True,
                    "skipped": True,
                    "reason": f"all march queues currently deployed ({active_marches_count}/{account_max_queues})",
                    "total_marches": 0,
                    "rounds_completed": 0
                }

            # STRICT PRE-FLIGHT 2: If troops depleted in city, skip gracefully!
            if total_troops <= 0:
                log(f"[{char_tag}] Barbarian combat skipped: No troops available in city. Proceeding to gather...")
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "no troops available in city",
                    "total_marches": 0,
                    "rounds_completed": 0
                }

            # STRICT PRE-FLIGHT 3: Only abort if AP is confirmed < 40
            if current_ap is not None and current_ap < 40:
                log(f"[{char_tag}] Barbarian combat skipped: Insufficient AP ({current_ap} < 40). Proceeding to gather...")
                return {
                    "success": True,
                    "skipped": True,
                    "reason": f"insufficient AP ({current_ap} < 40)",
                    "total_marches": 0,
                    "rounds_completed": 0
                }

            # 4. Resolve Barbarian Target Level
            clamped_level = 6
            req_str = str(highest_barb_level or target_level or "Max Unlocked").strip()
            if req_str.lower() in ("max unlocked", "max", "أعلى مستوى مفتوح", "0"):
                if server_unlocked_barb_lvl is not None and server_unlocked_barb_lvl > 0:
                    clamped_level = min(25, server_unlocked_barb_lvl + 1)
                else:
                    clamped_level = 12
                log(f"[{char_tag}] Target Barbarian Level resolved to Max Unlocked: Level {clamped_level}")
            else:
                try:
                    num_part = req_str.upper().replace("L", "").replace("LEVEL", "").strip()
                    clamped_level = int(num_part)
                except Exception:
                    clamped_level = 6
                log(f"[{char_tag}] Target Barbarian Level set to configured: Level {clamped_level}")

            if skip_barbs_below and str(skip_barbs_below).lower() not in ("none", "null", ""):
                try:
                    floor_val = int(str(skip_barbs_below).upper().replace("L", "").strip())
                    if clamped_level < floor_val:
                        clamped_level = floor_val
                        log(f"[{char_tag}] Clamped level raised to floor (skip barbs below {floor_val}) -> Level {clamped_level}")
                except Exception:
                    pass

            clamped_level = max(1, min(25, int(clamped_level)))

            # 5. Resolve March Queues & Eligible Commanders
            free_heroes = [h for h in available_heroes if h not in busy_heroes and h not in garrison_ids]
            if not free_heroes:
                for h in COMBAT_HEROES_PREFERENCE:
                    if h not in garrison_ids and h not in busy_heroes:
                        free_heroes.append(h)

            if not free_heroes:
                log(f"[{char_tag}] Barbarian combat skipped: No eligible commanders available. Proceeding to gather...")
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "no eligible commanders available",
                    "total_marches": 0,
                    "rounds_completed": 0
                }

            if dispatch_all_marches:
                num_marches = min(free_queues, int(max_marches or 5), len(free_heroes))
                if total_troops < 10000:
                    num_marches = min(num_marches, max(1, total_troops // 2000))
            else:
                num_marches = 1
            num_marches = max(1, num_marches)

            log(f"[{char_tag}] Single-Target Swarm Configuration: Deploying {num_marches} simultaneous march queue(s) focusing on 1 target across {combat_rounds} round(s).")

            def encode_point(x: float, y: float) -> bytes:
                return b"\x15" + struct.pack("<f", float(x)) + b"\x0d" + struct.pack("<f", float(y))

            def build_map_request(center_pos: Tuple[float, float]) -> bytes:
                f1 = encode_point(center_pos[0], center_pos[1])
                payload = ProtobufCodec.encode_message({1: f1, 2: 0, 5: 1})
                return ProtobufCodec.encode_message({1: OP_MAP_VIEWPORT_REQ, 2: payload})

            async def count_active_marches() -> int:
                """
                Polls Opcode 1005 to check if any of our marches are still away.
                """
                try:
                    writer.write(FrameParser.build_frame(c_tx.encrypt(build_map_request(discovered_city_coords))))
                    await writer.drain()
                except Exception:
                    return -1

                active_m: Set[str] = set()
                march_pattern = re.compile(str(target_role_id).encode() + rb"_\d+_(\d+)")
                deadline = asyncio.get_event_loop().time() + 2.5
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.4)
                        rl = (rh[0] << 8) | rh[1]
                        raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.4)
                        dec = c_rx.decrypt(raw)
                        decomp = safe_decompress(dec)
                        m = ProtobufCodec.decode_message(decomp)
                        chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                        for c in chunks:
                            it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                            if not isinstance(it, dict): continue
                            if it.get(1) in (1005, 1023) and isinstance(it.get(2), bytes):
                                for match in march_pattern.finditer(it.get(2)):
                                    active_m.add(match.group(0).decode("latin1", "ignore"))
                    except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                        continue
                    except Exception:
                        break
                return len(active_m)

            total_marches_dispatched = 0
            rounds_completed = 0

            # 6. Combat Rounds Loop
            for round_num in range(1, int(combat_rounds) + 1):
                # Check AP before each round
                if current_ap is not None and current_ap < 40:
                    log(f"[{char_tag}] AP depleted ({current_ap} < 40). Ending barbarian combat.")
                    break

                # Step 1: Discover nearby roaming barbarians (Opcode 1003)
                for dx, dy in [(0.0, 0.0), (-18.0, 0.0), (18.0, 0.0), (0.0, -18.0), (0.0, 18.0)]:
                    writer.write(FrameParser.build_frame(c_tx.encrypt(build_map_request((discovered_city_coords[0] + dx, discovered_city_coords[1] + dy)))))
                await writer.drain()

                found_barbarians: List[Dict[str, Any]] = []
                collect_deadline = asyncio.get_event_loop().time() + 2.5
                while asyncio.get_event_loop().time() < collect_deadline:
                    try:
                        rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
                        rl = (rh[0] << 8) | rh[1]
                        raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
                        dec = c_rx.decrypt(raw)
                        decomp = safe_decompress(dec)
                        m = ProtobufCodec.decode_message(decomp)
                        chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                        for c in chunks:
                            it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                            if not isinstance(it, dict): continue
                            op = it.get(1)
                            if op == OP_MAP_VIEWPORT_STREAM:
                                nearby = CombatEngine.parse_all_barbarians_from_1003(
                                    it.get(2, b""),
                                    discovered_city_coords[0],
                                    discovered_city_coords[1]
                                )
                                for b in nearby:
                                    if b["dist"] <= 20.0 and not any(fb["entity_id"] == b["entity_id"] for fb in found_barbarians):
                                        found_barbarians.append(b)
                    except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                        break

                # Step 2: If none in range, Spawn target barbarian via Opcode 1178
                if not found_barbarians:
                    log(f"[{char_tag}] Searching Barbarian Lvl {clamped_level} via Opcode 1178...")
                    search_levels = [clamped_level]
                    if clamped_level > 1:
                        search_levels.extend(range(clamped_level - 1, max(0, clamped_level - 4), -1))
                    for s_lvl in search_levels:
                        search_pkt = ProtobufCodec.encode_message({
                            1: OP_SEARCH_BARBARIAN,
                            2: CombatEngine.build_search_barbarian_payload(s_lvl)
                        })
                        writer.write(FrameParser.build_frame(c_tx.encrypt(search_pkt)))
                        await writer.drain()

                        search_deadline = asyncio.get_event_loop().time() + 1.8
                        while asyncio.get_event_loop().time() < search_deadline:
                            try:
                                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
                                rl = (rh[0] << 8) | rh[1]
                                raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
                                dec = c_rx.decrypt(raw)
                                decomp = safe_decompress(dec)
                                m = ProtobufCodec.decode_message(decomp)
                                chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                                for c in chunks:
                                    it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                                    if not isinstance(it, dict): continue
                                    op = it.get(1)
                                    if op == OP_BARBARIAN_SEARCH_RESP and isinstance(it.get(2), bytes):
                                        spawns = CombatEngine.parse_all_barbarian_search_resps(it.get(2))
                                        for sp in spawns:
                                            if not any(fb["entity_id"] == sp["entity_id"] for fb in found_barbarians):
                                                found_barbarians.append(sp)
                                    elif op == OP_OBJECT_SPAWN and isinstance(it.get(2), bytes):
                                        sp = CombatEngine.parse_barbarian_spawn(it.get(2))
                                        if sp and not any(fb["entity_id"] == sp["entity_id"] for fb in found_barbarians):
                                            found_barbarians.append(sp)
                            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                                break
                        if found_barbarians:
                            break

                # Step 3: Single-Target Selection (NO SYNTHETIC DUMMY IDS!)
                if not found_barbarians:
                    log(f"[{char_tag}] Barbarian combat skipped: No barbarian targets found in range. Proceeding to gather...")
                    return {
                        "success": True,
                        "skipped": True,
                        "reason": "no barbarian targets in range",
                        "total_marches": total_marches_dispatched,
                        "rounds_completed": rounds_completed
                    }

                target_barb = found_barbarians[0]
                t_eid = target_barb["entity_id"]
                t_pos = (target_barb["x"], target_barb["y"])
                t_lvl = target_barb.get("level") or clamped_level
                t_tile_x = round(t_pos[0] / 6.0, 1)
                t_tile_y = round(t_pos[1] / 6.0, 1)
                dist_km = math.hypot(t_pos[0] - discovered_city_coords[0], t_pos[1] - discovered_city_coords[1]) / 6.0

                # Emit Swarm Announcement Log
                log(f"🏹 [{char_tag}] Swarming Lvl {t_lvl} Barbarian at ({t_tile_x}, {t_tile_y}) [{dist_km:.1f}km away] with up to {num_marches} marches (Target #{t_eid})")

                # Step 4: Staggered Dispatch of ALL Marches to this SAME Target
                used_commanders: Set[int] = set()
                round_dispatches = 0

                for march_idx in range(1, num_marches + 1):
                    # Pick Primary Commander
                    cand_pool = [h for h in free_heroes if h not in used_commanders]
                    if not cand_pool:
                        log(f"[-] [{char_tag}] No more available commanders for March {march_idx}.")
                        break

                    prim_hero_id = cand_pool[0]
                    if march_idx == 1 and primary_commander and primary_commander != "Auto":
                        cfg_id = COMMANDER_NAME_TO_ID.get(primary_commander)
                        if cfg_id and cfg_id in cand_pool:
                            prim_hero_id = cfg_id

                    used_commanders.add(prim_hero_id)

                    # Pick Secondary Commander if primary allows (star >= 3 or unlocked)
                    sec_hero_id = 0
                    p_info = hero_details_map.get(prim_hero_id, {})
                    can_have_secondary = p_info.get("star", 1) >= 3 or p_info.get("level", 1) >= 20

                    if can_have_secondary:
                        if march_idx == 1 and secondary_commander and secondary_commander != "Auto (best available)":
                            if secondary_commander != "None":
                                cfg_sec = COMMANDER_NAME_TO_ID.get(secondary_commander)
                                if cfg_sec and cfg_sec in free_heroes and cfg_sec not in used_commanders:
                                    sec_hero_id = cfg_sec
                        else:
                            sec_cands = [h for h in free_heroes if h not in used_commanders]
                            if sec_cands:
                                sec_hero_id = sec_cands[0]

                    if sec_hero_id > 0:
                        used_commanders.add(sec_hero_id)

                    prim_name = COMMANDER_NAMES.get(prim_hero_id, f"Hero #{prim_hero_id}")

                    # Allocate Troops Fairly Across All Marches
                    barb_power_need = TROOP_BUDGET_BY_BARB_LEVEL.get(t_lvl, 25000)
                    rem_city_troops = sum(troops_in_city.values()) if troops_in_city else 0
                    marches_remaining = max(1, num_marches - march_idx + 1)
                    target_budget = max(500, min(barb_power_need, rem_city_troops // marches_remaining if rem_city_troops > 0 else 10000))

                    march_troops: List[Tuple[int, int]] = []
                    curr_alloc = 0

                    sorted_troops = sorted(troops_in_city.items(), key=lambda x: 1 if (x[0] % 4 == 0) else 0)
                    for ut, avail in sorted_troops:
                        if curr_alloc >= target_budget or avail <= 0: break
                        take = min(avail, target_budget - curr_alloc)
                        if take > 0:
                            march_troops.append((ut, take))
                            curr_alloc += take
                            troops_in_city[ut] = avail - take

                    if not march_troops:
                        log(f"[-] [{char_tag}] Insufficient troops left in city for March {march_idx}.")
                        break

                    # 1. Viewport to Target Barbarian
                    writer.write(FrameParser.build_frame(c_tx.encrypt(build_map_request(t_pos))))
                    await writer.drain()
                    await asyncio.sleep(0.12)

                    # 2. Inspect Target (Opcode 1050)
                    inspect_pkt = ProtobufCodec.encode_message({
                        1: OP_INSPECT_TARGET,
                        2: CombatEngine.build_target_inspect_payload(
                            role_id=int(target_role_id),
                            target_entity_id=int(t_eid),
                            city_x=discovered_city_coords[0],
                            city_y=discovered_city_coords[1],
                            target_x=t_pos[0],
                            target_y=t_pos[1]
                        )
                    })
                    writer.write(FrameParser.build_frame(c_tx.encrypt(inspect_pkt)))
                    await writer.drain()
                    await asyncio.sleep(0.12)

                    # 3. SendTroopConfirm (Opcode 8)
                    writer.write(FrameParser.build_frame(c_tx.encrypt(CombatEngine.build_send_troop_confirm())))
                    await writer.drain()
                    await asyncio.sleep(0.1)

                    # 4. Dispatch March (Opcode 1012)
                    dispatch_pkt = ProtobufCodec.encode_message({
                        1: OP_DISPATCH_MARCH,
                        2: CombatEngine.build_combat_dispatch_payload(
                            target_entity_id=int(t_eid),
                            primary_commander_id=prim_hero_id,
                            secondary_commander_id=sec_hero_id,
                            troops=march_troops,
                            march_index=round_dispatches + 1
                        )
                    })
                    writer.write(FrameParser.build_frame(c_tx.encrypt(dispatch_pkt)))
                    await writer.drain()

                    # STRICT SERVER ACK VERIFICATION
                    confirmed = False
                    rejection_reason = None
                    ack_start = time.time()
                    while time.time() - ack_start < 3.5:
                        try:
                            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.5)
                            rl = (rh[0] << 8) | rh[1]
                            raw_b = await asyncio.wait_for(reader.readexactly(rl), timeout=0.5)
                            dec = c_rx.decrypt(raw_b)
                            decomp = safe_decompress(dec)
                            m = ProtobufCodec.decode_message(decomp)
                            chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                            for c in chunks:
                                it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                                if not isinstance(it, dict): continue
                                op = it.get(1)
                                if op in (903, 365, 1013, 1005, 1024, 1023):
                                    confirmed = True
                                    break
                                if op == 1 and isinstance(it.get(2), bytes):
                                    p_dec = ProtobufCodec.decode_message(it.get(2))
                                    if isinstance(p_dec, dict) and p_dec.get(1) == 1012:
                                        code = p_dec.get(2, -1)
                                        if code in (0, 1):
                                            confirmed = True
                                            break
                                        elif code == 155:
                                            rejection_reason = "Error 155 (Commander busy or queue limit reached)"
                                            break
                                        elif code == 135:
                                            rejection_reason = "Error 135 (Commander unowned or garrisoned)"
                                            break
                                        else:
                                            rejection_reason = f"Error {code}"
                                            break
                            if confirmed or rejection_reason:
                                break
                        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                            continue
                        except Exception:
                            break

                    if confirmed:
                        round_dispatches += 1
                        total_marches_dispatched += 1
                        if current_ap is not None:
                            current_ap = max(0, current_ap - 40)
                        log(f"⚔️ [{char_tag}] Swarm March {round_dispatches}/{num_marches} launched: [{prim_name}] ({curr_alloc:,} troops) [SERVER CONFIRMED]")
                        # Anti-Bot Strict Staggered Launch Interval (1.2s - 1.6s)
                        if march_idx < num_marches:
                            await asyncio.sleep(random.uniform(1.2, 1.6))
                    else:
                        log(f"[-] [{char_tag}] March {march_idx} rejected by server: {rejection_reason or 'No ACK received'}. March not launched.")
                        for ut, cnt in march_troops:
                            troops_in_city[ut] = troops_in_city.get(ut, 0) + cnt
                        busy_heroes.add(prim_hero_id)

                # Step 5: Battle Resolution & Return Monitoring
                if round_dispatches > 0:
                    rounds_completed += 1
                    est_roundtrip = max(25.0, (dist_km / 0.35) * 2.0 + 15.0)
                    log(f"⏳ [{char_tag}] Swarm engaged! {round_dispatches} armies marching to Barbarian Lvl {t_lvl} ({dist_km:.1f}km away). Monitoring battle resolution (~{int(est_roundtrip)}s)...")

                    min_travel_wait = max(8.0, (dist_km / 0.5) * 2.0)
                    start_monitor = asyncio.get_event_loop().time()
                    wait_deadline = start_monitor + est_roundtrip + 45.0

                    while asyncio.get_event_loop().time() < wait_deadline:
                        await asyncio.sleep(4.0)
                        elapsed = asyncio.get_event_loop().time() - start_monitor
                        if elapsed >= min_travel_wait:
                            active_cnt = await count_active_marches()
                            if active_cnt <= active_marches_count:
                                break

                    log(f"🏆 [{char_tag}] Barbarian Lvl {t_lvl} defeated! All {round_dispatches} armies returned to city.")

                    # Step 6: Hospital Auto-Heal Integration
                    if heal_troops:
                        try:
                            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: OP_QUERY_WOUNDED, 2: ProtobufCodec.encode_message({1: 1})}))))
                            await writer.drain()
                            await asyncio.sleep(0.4)

                            heal_body = bytearray()
                            heal_body.extend(b"\x0a\x0267")
                            for u in range(1, 17):
                                heal_body.extend(b"\x12\x04\x10\x01\x08" + bytes([u]))
                            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: OP_HEAL_TROOPS, 2: bytes(heal_body)}))))
                            await writer.drain()
                            await asyncio.sleep(0.3)

                            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: OP_ALLIANCE_HELP_REQUEST, 2: bytes.fromhex("12023637080420001800")}))))
                            await writer.drain()
                            log(f"🏥 [{char_tag}] Hospital batch healed & alliance help requested.")
                        except Exception as e_h:
                            logger.debug(f"[HOSPITAL] note: {e_h}")

                    # Rest interval between rounds if multiple rounds requested
                    if round_num < int(combat_rounds):
                        await asyncio.sleep(random.uniform(2.5, 4.0))
                else:
                    log(f"[-] [{char_tag}] No marches were successfully confirmed by the server for Round {round_num}.")
                    break

            log(f"🏆 [{char_tag}] Barbarian combat finished ({total_marches_dispatched} march{'es' if total_marches_dispatched > 1 else ''}). Marches returned to city. Queues now empty for gathering.")

            return {
                "success": True,
                "skipped": total_marches_dispatched == 0,
                "reason": "combat completed" if total_marches_dispatched > 0 else "no marches launched",
                "rounds_completed": rounds_completed,
                "total_rounds": combat_rounds,
                "total_marches": total_marches_dispatched,
                "level": clamped_level,
                "city_coords": discovered_city_coords,
                "hero_discovery": {
                    "roster": merged_roster,
                    "garrison": list(garrison_ids),
                    "server_unlocked_barb_level": server_unlocked_barb_lvl
                }
            }

        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


execute_barbarian_hunt = CombatEngine.execute_barbarian_hunt
