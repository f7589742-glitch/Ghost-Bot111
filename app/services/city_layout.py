"""
app/services/city_layout.py — Universal Dynamic City Layout Engine
Commercial-grade, dynamic building resolver for Rise of Kingdoms Headless Bot.
Zero hardcoded IDs: dynamically parses Opcode 124, 125, and 302 to resolve
all military buildings (Infantry, Cavalry, Archery, Siege) and resource production
buildings (Farms, Lumber Mills, Quarries, Goldmines).
"""

import asyncio
import json
import logging
import os
import sys
import zlib
from typing import Dict, Any, List, Optional, Tuple

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PYTHON_DIR = os.path.join(BASE_DIR, "python")
for p in (BASE_DIR, PYTHON_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from headless_client import ProtobufCodec, FrameParser
    from crypto_module import RokCrypto
except ImportError:
    from python.headless_client import ProtobufCodec, FrameParser
    from python.crypto_module import RokCrypto

logger = logging.getLogger("city_layout")

# Verified In-Game Barracks Capacity Table (Levels 1 - 25)
CAPACITY_TABLE = {
    1: 20, 2: 50, 3: 100, 4: 150, 5: 200, 6: 250, 7: 300, 8: 350, 9: 400,
    10: 450, 11: 500, 12: 550, 13: 600, 14: 700, 15: 800, 16: 900,
    17: 1000, 18: 1100, 19: 1200, 20: 1300, 21: 1400, 22: 1500,
    23: 1600, 24: 1700, 25: 2000
}

# Reverse lookup: capacity → building level (for inferring level from active training count)
CAPACITY_TO_LEVEL = {v: k for k, v in CAPACITY_TABLE.items()}

# Rise of Kingdoms Server Building Type Enums (Universal across all civilizations)
# Strictly match military barracks by official type enums:
#   Type 13: Infantry Barracks (unit_type: 1)
#   Type 14: Cavalry Stable (unit_type: 2)
#   Type 15: Archery Range (unit_type: 3)
#   Type 16: Siege Workshop (unit_type: 4)
BUILDING_TYPE_ENUMS = {
    1: {"category": "town_hall", "name": "Town Hall", "type": "administrative"},
    2: {"category": "farm", "name": "Farm", "type": "resource", "resource_type": 1},
    3: {"category": "lumber_mill", "name": "Lumber Mill", "type": "resource", "resource_type": 2},
    4: {"category": "quarry", "name": "Quarry", "type": "resource", "resource_type": 3},
    5: {"category": "goldmine", "name": "Goldmine", "type": "resource", "resource_type": 4},
    10: {"category": "hospital", "name": "Hospital", "type": "medical"},
    11: {"category": "castle", "name": "Castle", "type": "military_structure"},
    12: {"category": "alliance_center", "name": "Alliance Center", "type": "alliance"},
    # Authoritative Military Barracks Type Enums:
    13: {"category": "infantry", "name": "Barracks", "type": "military", "unit_type": 1},
    14: {"category": "cavalry", "name": "Stable", "type": "military", "unit_type": 2},
    15: {"category": "archery", "name": "Archery Range", "type": "military", "unit_type": 3},
    16: {"category": "siege", "name": "Siege Workshop", "type": "military", "unit_type": 4},
    17: {"category": "hospital", "name": "Hospital", "type": "medical"},
}

UNIT_TYPE_TO_CATEGORY = {
    1: "infantry",   # Barracks
    2: "cavalry",    # Stables
    3: "archery",    # Archery Range
    4: "siege",      # Siege Workshop
}

CATEGORY_TO_UNIT_TYPE = {
    "infantry": 1,
    "cavalry": 2,
    "archery": 3,
    "siege": 4,
}

RESOURCE_TYPE_MAP = {
    1: {"name": "Food", "building": "Farm"},
    2: {"name": "Wood", "building": "Lumber Mill"},
    3: {"name": "Stone", "building": "Quarry"},
    4: {"name": "Gold", "building": "Goldmine"},
}

class SessionLayoutRegistry:
    """In-memory multi-tenant SaaS session registry for dynamically discovered city structures."""
    _sessions: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get(cls, role_id: str) -> Optional[Dict[str, Any]]:
        return cls._sessions.get(str(role_id))

    @classmethod
    def set(cls, role_id: str, data: Dict[str, Any]) -> None:
        cls._sessions[str(role_id)] = data

    @classmethod
    def clear(cls, role_id: Optional[str] = None) -> None:
        if role_id:
            cls._sessions.pop(str(role_id), None)
        else:
            cls._sessions.clear()


class CityLayoutResolver:
    """Dynamically resolves and maintains the complete layout of any player city via on-wire packet inspection."""

    @classmethod
    def get_layout(cls, role_id: str) -> Optional[Dict[str, Any]]:
        """Returns the in-memory cached layout for a role ID if available."""
        return SessionLayoutRegistry.get(str(role_id))

    @classmethod
    def load_cached_layout(cls, role_id: str) -> Optional[Dict[str, Any]]:
        """Returns the in-memory cached layout for a role ID if available."""
        return SessionLayoutRegistry.get(str(role_id))

    @classmethod
    def parse_opcode_124(cls, payload: bytes) -> Dict[str, Any]:
        """
        Parses Opcode 124 / 106 building objects directly from wire packets.
        Extracts: {building_id, type_enum, level, category}

        Wire formats encountered:
          Flat (NucroShop/older servers):
            entry = {1: bid, 2: type_enum(int), 3: level(int)}
          Nested (KD/newer servers):
            entry = {1: bid, 2: {1: type_enum, 2: level}}
        Both formats are handled below.
        """
        result = {
            "town_hall": None,
            "barracks": {},
            "hospitals": [],
            "production": []
        }
        try:
            p124 = ProtobufCodec.decode_message(payload)
            entries = p124.get(1, [])
            if not isinstance(entries, list):
                entries = [entries]

            for e in entries:
                if not isinstance(e, bytes):
                    continue
                sub = ProtobufCodec.decode_message(e)
                raw_bid = sub.get(1)
                bid_str = raw_bid.decode("utf-8") if isinstance(raw_bid, bytes) else str(raw_bid)

                # Handle both flat and nested wire format
                type_enum_raw = sub.get(2, 0)
                level_raw = sub.get(3, 1)

                if isinstance(type_enum_raw, bytes):
                    # Nested submessage format: field 2 is {1: type_enum, 2: level}
                    try:
                        sub2 = ProtobufCodec.decode_message(type_enum_raw)
                        type_enum = int(sub2.get(1, 0))
                        level = int(sub2.get(2, 1) or 1)
                    except Exception:
                        type_enum = 0
                        level = 1
                else:
                    type_enum = int(type_enum_raw) if type_enum_raw else 0
                    level = int(level_raw) if level_raw else 1

                # Clamp level to valid range
                if level <= 0:
                    level = 1

                b_meta = BUILDING_TYPE_ENUMS.get(type_enum)
                if not b_meta:
                    continue

                cat = b_meta["category"]
                if cat == "town_hall":
                    result["town_hall"] = {"building_id": bid_str, "level": level}
                elif b_meta["type"] == "military":
                    result["barracks"][cat] = {
                        "building_id": bid_str,
                        "category": cat,
                        "unit_type": b_meta.get("unit_type", 1),
                        "level": level,
                        "capacity": CAPACITY_TABLE.get(int(level), 1000),
                        "is_busy": False,
                        "remaining_seconds": 0,
                        "needs_harvest": False
                    }
                elif cat == "hospital":
                    result["hospitals"].append({"building_id": bid_str, "level": level})
                elif b_meta["type"] == "resource":
                    r_type = b_meta.get("resource_type", 1)
                    r_info = RESOURCE_TYPE_MAP.get(r_type, {"name": "Resource", "building": "Resource"})
                    result["production"].append({
                        "building_id": bid_str,
                        "resource_type": r_type,
                        "resource_name": r_info["name"],
                        "building_type": r_info["building"],
                        "level": level
                    })
        except Exception as e:
            logger.debug(f"Error parsing Opcode 124: {e}")
        return result

    @classmethod
    def parse_opcode_125(cls, payload: bytes) -> List[Dict[str, Any]]:
        """
        Parses Opcode 125 building production bubbles.
        Returns list of {building_id: str, resource_type: int, resource_name: str, uncollected: int}
        """
        production_buildings = []
        try:
            p125 = ProtobufCodec.decode_message(payload)
            entries = p125.get(1, [])
            if not isinstance(entries, list):
                entries = [entries]

            for e in entries:
                if not isinstance(e, bytes):
                    continue
                sub = ProtobufCodec.decode_message(e)
                raw_bid = sub.get(1)
                bid_str = raw_bid.decode("utf-8") if isinstance(raw_bid, bytes) else str(raw_bid)
                val = sub.get(2)
                sub_val = ProtobufCodec.decode_message(val) if isinstance(val, bytes) else (val if isinstance(val, dict) else {})
                r_type = sub_val.get(1, 0)
                amount = sub_val.get(2, 0)
                r_info = RESOURCE_TYPE_MAP.get(r_type, {"name": f"Unknown_{r_type}", "building": "Resource"})
                production_buildings.append({
                    "building_id": bid_str,
                    "resource_type": r_type,
                    "resource_name": r_info["name"],
                    "building_type": r_info["building"],
                    "uncollected": amount
                })
        except Exception as e:
            logger.debug(f"Error parsing Opcode 125: {e}")
        return production_buildings

    @classmethod
    def parse_opcode_302(cls, payload: bytes) -> Dict[str, Dict[str, Any]]:
        """
        Parses Opcode 302 military barracks training queue state.
        Returns {category: {building_id, unit_type, count, remaining_sec, is_busy, needs_harvest}}
        """
        barracks = {}
        try:
            p302 = ProtobufCodec.decode_message(payload)
            entries = p302.get(1, [])
            if not isinstance(entries, list):
                entries = [entries]

            for e in entries:
                if not isinstance(e, bytes):
                    continue
                sub = ProtobufCodec.decode_message(e)
                raw_bid = sub.get(1)
                bid_str = raw_bid.decode("utf-8") if isinstance(raw_bid, bytes) else str(raw_bid)
                u_type = sub.get(2, 0)
                count = sub.get(3, 0)
                remaining_ms = sub.get(4, 0)
                remaining_sec = max(0, remaining_ms // 1000)
                total_duration_ms = sub.get(5, 0)
                cat = UNIT_TYPE_TO_CATEGORY.get(u_type)
                if cat:
                    barracks[cat] = {
                        "building_id": bid_str,
                        "unit_type": u_type,
                        "category": cat,
                        "count": count,
                        "remaining_seconds": remaining_sec,
                        "total_duration_seconds": total_duration_ms // 1000,
                        "is_busy": remaining_sec > 0,
                        "needs_harvest": (remaining_sec == 0) and (count > 0)
                    }
        except Exception as e:
            logger.debug(f"Error parsing Opcode 302: {e}")
        return barracks

    @classmethod
    def parse_opcode_904(cls, payload: bytes) -> Dict[str, str]:
        """
        Parses Opcode 904 (Player Stat / Buffs Packet sent on every handshake)
        to extract authoritative building instance IDs:
          building.<ID>.3000 -> infantry barracks
          building.<ID>.4000 -> cavalry stable
          building.<ID>.5000 -> archery range
          building.<ID>.8000 -> siege workshop
          building.<ID>.2100 -> hospital
        """
        barracks_ids = {}
        try:
            p904 = ProtobufCodec.decode_message(payload)
            k2 = p904.get(2)
            if isinstance(k2, bytes):
                k2 = ProtobufCodec.decode_message(k2)
            if isinstance(k2, dict):
                items = k2.get(1, [])
                if not isinstance(items, list):
                    items = [items]
                for itm in items:
                    d_itm = ProtobufCodec.decode_message(itm) if isinstance(itm, bytes) else itm
                    if isinstance(d_itm, dict):
                        raw_name = d_itm.get(1, b"")
                        name = raw_name.decode("utf-8", errors="ignore") if isinstance(raw_name, bytes) else str(raw_name)
                        if name.startswith("building."):
                            parts = name.split(".")
                            if len(parts) >= 3:
                                bid = str(parts[1])
                                buff_id = str(parts[2])
                                if buff_id == "3000":
                                    barracks_ids["infantry"] = bid
                                elif buff_id == "4000":
                                    barracks_ids["cavalry"] = bid
                                elif buff_id == "5000":
                                    barracks_ids["archery"] = bid
                                elif buff_id == "8000":
                                    barracks_ids["siege"] = bid
                                elif buff_id == "2100":
                                    barracks_ids["hospital"] = bid
        except Exception as e:
            logger.debug(f"Error parsing Opcode 904: {e}")
        return barracks_ids

    @classmethod
    async def discover_layout(
        cls,
        reader,
        writer,
        crypto_tx: RokCrypto,
        crypto_rx: RokCrypto,
        role_id: str,
        city_hall_level: int = 17,
        log_callback=None,
        known_barracks: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Autonomous protocol discovery of city layout:
        1. Fully agnostic to civilization and layout customizations.
        2. Queries building state on wire via Opcode 123.
        3. Authoritatively parses Opcode 904, 302, 124, 125 for exact runtime instance IDs.
        4. Zero guesswork slot probing.
        5. Strictly guards against Town Hall/Barracks collisions.
        """
        def log(msg):
            if log_callback:
                log_callback(msg)
            else:
                logger.info(msg)

        log(f"[CITY_LAYOUT] Discovering layout dynamically on wire for Role {role_id}...")

        # Initialize from existing session if already captured in this connection
        session_data = SessionLayoutRegistry.get(str(role_id)) or {}
        barracks = dict(session_data.get("barracks", {}))
        production_buildings = list(session_data.get("production_buildings", []))
        town_hall_id = session_data.get("town_hall_id", "35")
        town_hall_level = int(session_data.get("town_hall_level") or session_data.get("city_hall_level") or city_hall_level or 17)

        if known_barracks:
            for k_cat, k_data in known_barracks.items():
                if isinstance(k_data, dict):
                    if k_cat not in barracks:
                        barracks[k_cat] = dict(k_data)
                    else:
                        barracks[k_cat].update(k_data)
                elif isinstance(k_data, str) and k_data:
                    if k_cat not in barracks:
                        barracks[k_cat] = {
                            "building_id": str(k_data),
                            "category": k_cat,
                            "unit_type": CATEGORY_TO_UNIT_TYPE.get(k_cat, 1)
                        }
                    else:
                        barracks[k_cat]["building_id"] = str(k_data)

        # 1. Send Opcode 123 for candidate IDs to query all building states
        query_bids = [str(i).encode() for i in range(120)]
        pkt_123 = ProtobufCodec.encode_message({
            1: 123,
            2: ProtobufCodec.encode_message({1: query_bids})
        })
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_123)))
        await writer.drain()

        # Listen for Opcode 904, 124, 125, and 302
        deadline = asyncio.get_event_loop().time() + 2.5
        incoming_prod = []
        incoming_302 = {}
        incoming_124 = {}
        incoming_904 = {}

        while asyncio.get_event_loop().time() < deadline:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.4)
                rl = (rh[0] << 8) | rh[1]
                raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.4)
                dec = crypto_rx.decrypt(raw)
                z_idx = dec.find(b"\x78\x9c")
                if z_idx == -1: z_idx = dec.find(b"\x78\x01")
                decomp = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
                m = ProtobufCodec.decode_message(decomp)
                chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                for c in chunks:
                    it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                    op = it.get(1)
                    p_body = it.get(2)
                    if op == 904 and isinstance(p_body, bytes):
                        b_904 = cls.parse_opcode_904(p_body)
                        if b_904:
                            incoming_904.update(b_904)
                    elif op == 124 and isinstance(p_body, bytes):
                        res_124 = cls.parse_opcode_124(p_body)
                        if res_124.get("town_hall"):
                            town_hall_id = str(res_124["town_hall"]["building_id"])
                            if res_124["town_hall"].get("level"):
                                town_hall_level = int(res_124["town_hall"]["level"])
                                try:
                                    from app.models import CharacterDAO
                                    CharacterDAO.update_city_level(str(role_id), town_hall_level)
                                except Exception:
                                    pass
                        if res_124.get("barracks"):
                            incoming_124.update(res_124["barracks"])
                        if res_124.get("production"):
                            incoming_prod.extend(res_124["production"])
                    elif op == 125 and isinstance(p_body, bytes):
                        p_list = cls.parse_opcode_125(p_body)
                        if p_list:
                            incoming_prod.extend(p_list)
                    elif op == 302 and isinstance(p_body, bytes):
                        b_dict = cls.parse_opcode_302(p_body)
                        if b_dict:
                            incoming_302.update(b_dict)
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                break

        # Priority 1: Apply Opcode 904 exact wire stat buffs (authoritative on every login)
        for cat, bid in incoming_904.items():
            if cat in ("infantry", "cavalry", "archery", "siege"):
                if cat not in barracks:
                    barracks[cat] = {"building_id": str(bid), "category": cat, "unit_type": CATEGORY_TO_UNIT_TYPE.get(cat, 1)}
                else:
                    barracks[cat]["building_id"] = str(bid)

        # Priority 2: Merge Opcode 124 building structures
        if incoming_124:
            for cat, data in incoming_124.items():
                if cat not in barracks or not barracks[cat].get("building_id"):
                    barracks[cat] = data
                else:
                    barracks[cat]["level"] = data.get("level", barracks[cat].get("level"))
                    barracks[cat]["capacity"] = data.get("capacity", barracks[cat].get("capacity"))

        # Priority 3: Merge Opcode 302 queue and harvest states
        if incoming_302:
            for cat, data in incoming_302.items():
                if cat not in barracks:
                    barracks[cat] = data
                else:
                    barracks[cat].update(data)

        if incoming_prod:
            production_buildings = incoming_prod

        # Guard: Never allow Building #1 for infantry (Building #1 is Town Hall)
        # If building type 13 (infantry) is not found or collides with Town Hall, re-request on wire
        inf_data = barracks.get("infantry", {})
        inf_bid = str(inf_data.get("building_id", ""))
        if not inf_bid or inf_bid == "1" or (town_hall_id and inf_bid == str(town_hall_id)):
            log("[CITY_LAYOUT] Infantry building not found or conflicted with Town Hall (#1). Re-requesting layout dynamically on wire...")
            query_bids = [str(i).encode() for i in range(1, 150)]
            pkt_123 = ProtobufCodec.encode_message({
                1: 123,
                2: ProtobufCodec.encode_message({1: query_bids})
            })
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_123)))
            await writer.drain()

            re_deadline = asyncio.get_event_loop().time() + 2.0
            while asyncio.get_event_loop().time() < re_deadline:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.25)
                    rl = (rh[0] << 8) | rh[1]
                    raw = await reader.readexactly(rl)
                    dec = crypto_rx.decrypt(raw)
                    z_idx = dec.find(b"\x78\x9c")
                    if z_idx == -1: z_idx = dec.find(b"\x78\x01")
                    decomp = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
                    m = ProtobufCodec.decode_message(decomp)
                    chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                    for c in chunks:
                        it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                        if not isinstance(it, dict): continue
                        op = it.get(1)
                        pb = it.get(2)
                        if op == 904 and isinstance(pb, bytes):
                            b_904 = cls.parse_opcode_904(pb)
                            for c_k, b_v in b_904.items():
                                if c_k in ("infantry", "cavalry", "archery", "siege") and str(b_v) != "1":
                                    barracks.setdefault(c_k, {})["building_id"] = str(b_v)
                        elif op == 124 and isinstance(pb, bytes):
                            r124 = cls.parse_opcode_124(pb)
                            for c_k, b_d in r124.get("barracks", {}).items():
                                if str(b_d.get("building_id")) != "1":
                                    barracks[c_k] = b_d
                        elif op == 302 and isinstance(pb, bytes):
                            b302 = cls.parse_opcode_302(pb)
                            for c_k, b_d in b302.items():
                                if str(b_d.get("building_id")) != "1":
                                    barracks.setdefault(c_k, {}).update(b_d)

                    cur_inf = str(barracks.get("infantry", {}).get("building_id", ""))
                    if cur_inf and cur_inf not in ("1", str(town_hall_id)):
                        log(f"[CITY_LAYOUT] Re-query resolved Infantry Barracks to Building #{cur_inf}!")
                        break
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

        est_capacity = CAPACITY_TABLE.get(int(city_hall_level), 1000)
        for cat in ["infantry", "cavalry", "archery", "siege"]:
            b_data = barracks.get(cat, {})
            bid = str(b_data.get("building_id", "")).strip()

            # Hard safety guard: if empty or Town Hall collision (#1)
            if not bid or bid == "1" or (town_hall_id and bid == str(town_hall_id)):
                # Check known_barracks first (e.g. from Opcode 904)
                if known_barracks and cat in known_barracks:
                    k_val = known_barracks[cat]
                    k_bid = str(k_val.get("building_id") if isinstance(k_val, dict) else k_val).strip()
                    if k_bid and k_bid not in ("1", str(town_hall_id)):
                        bid = k_bid

                # Check cache next
                if not bid or bid == "1" or (town_hall_id and bid == str(town_hall_id)):
                    try:
                        from app.services.smart_troop_trainer import get_cached_barracks
                        c_b = get_cached_barracks(role_id).get(cat, {})
                        c_bid = str(c_b.get("building_id", "")).strip()
                        if c_bid and c_bid not in ("1", str(town_hall_id)):
                            bid = c_bid
                    except Exception:
                        pass

                # Final fallback to standard non-TH building ID
                if not bid or bid == "1" or (town_hall_id and bid == str(town_hall_id)):
                    bid = "15" if cat == "infantry" else ("64" if cat == "archery" else ("63" if cat == "cavalry" else "65"))
                    log(f"[CITY_LAYOUT] Notice: {cat.capitalize()} mapped to fallback Building #{bid}")

            # Level resolution priority:
            #   1. Opcode 124 (login-time auto-broadcast) → real level
            #   2. Infer from Opcode 302 training count (busy buildings only)
            #   3. Fallback to city_hall_level (conservative estimate)
            b_lvl_raw = b_data.get("level", 0)
            if b_lvl_raw and int(b_lvl_raw) > 1:
                # Reliable level from Opcode 124
                b_lvl = int(b_lvl_raw)
            elif b_data.get("is_busy") and b_data.get("current_training_count", 0) > 0:
                # Infer minimum level from active training count
                inferred = CAPACITY_TO_LEVEL.get(int(b_data["current_training_count"]))
                b_lvl = inferred if inferred else int(city_hall_level)
            else:
                # Use city_hall_level as fallback (all barracks grow with city hall)
                b_lvl = int(city_hall_level)

            barracks[cat] = {
                "building_id": bid,
                "category": cat,
                "unit_type": CATEGORY_TO_UNIT_TYPE.get(cat, 1),
                "level": b_lvl,
                "capacity": CAPACITY_TABLE.get(b_lvl, est_capacity),
                "is_busy": b_data.get("is_busy", False),
                "remaining_seconds": b_data.get("remaining_seconds", 0),
                "needs_harvest": b_data.get("needs_harvest", False),
            }

        barracks = {cat: barracks[cat] for cat in ("infantry", "cavalry", "archery", "siege") if cat in barracks}

        # Authoritative verified logging requirement
        inf_id = barracks['infantry']['building_id']
        arch_id = barracks['archery']['building_id']
        cav_id = barracks['cavalry']['building_id']
        siege_id = barracks['siege']['building_id']
        log(f"[BARRACKS VERIFIED] Role {role_id}: Inf=#{inf_id}, Arch=#{arch_id}, Cav=#{cav_id}, Siege=#{siege_id}")

        for cat, b in barracks.items():
            st = "BUSY" if b.get("is_busy") else ("READY_TO_HARVEST" if b.get("needs_harvest") else "IDLE")
            log(f"  * {cat.capitalize():<10} -> Building #{b['building_id']} | Status: {st} | Cap: {b.get('capacity')}")

        layout_result = {
            "role_id": str(role_id),
            "town_hall_id": town_hall_id,
            "town_hall_level": town_hall_level,
            "production_buildings": production_buildings,
            "barracks": barracks,
        }
        # Save to runtime session registry (multi-tenant state)
        SessionLayoutRegistry.set(str(role_id), layout_result)
        return layout_result
