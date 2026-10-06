"""
command_builder.py — Build game commands dynamically for farming operations.

This module constructs protobuf payloads for all known farming operations:
- Training (infantry, cavalry, archer, siege)
- Gathering (food, wood, stone, gold)
- Building/Research speedups
- Alliance help
- Resource collection

Protobuf structures derived from live Frida captures of the real game client.
"""
import struct
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────
# Protobuf Encoder
# ──────────────────────────────────────────────────────────────────────

def encode_varint(value: int) -> bytes:
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def encode_field(field_num: int, value: Any) -> bytes:
    if isinstance(value, int):
        tag = encode_varint((field_num << 3) | 0)
        return tag + encode_varint(value)
    elif isinstance(value, (bytes, bytearray)):
        tag = encode_varint((field_num << 3) | 2)
        return tag + encode_varint(len(value)) + bytes(value)
    elif isinstance(value, str):
        return encode_field(field_num, value.encode('utf-8'))
    elif isinstance(value, dict):
        nested = encode_message(value)
        tag = encode_varint((field_num << 3) | 2)
        return tag + encode_varint(len(nested)) + nested
    elif isinstance(value, list):
        result = b""
        for item in value:
            result += encode_field(field_num, item)
        return result
    raise TypeError(f"Unsupported type {type(value)} for field {field_num}")


def encode_message(fields: Dict[int, Any]) -> bytes:
    result = bytearray()
    for field_num in sorted(fields.keys()):
        result.extend(encode_field(field_num, fields[field_num]))
    return bytes(result)


# ──────────────────────────────────────────────────────────────────────
# Command Builders — each returns (opcode, protobuf_payload)
# ──────────────────────────────────────────────────────────────────────

# Troop type IDs (from PROTO_REF.md)
TROOP_INFANTRY_T4 = 267
TROOP_CAVALRY_T4 = 250
TROOP_ARCHER_T4 = 282
TROOP_SIEGE_T4 = 283

TROOP_INFANTRY_T5 = 284
TROOP_CAVALRY_T5 = 285
TROOP_ARCHER_T5 = 372
TROOP_SIEGE_T5 = 373

# Building slot types
BUILDING_BARRACKS = 1
BUILDING_STABLE = 2
BUILDING_ARCHERY_RANGE = 3
BUILDING_WORKSHOP = 4

# Resource types
RESOURCE_FOOD = 1
RESOURCE_WOOD = 2
RESOURCE_STONE = 3
RESOURCE_GOLD = 5


def build_train_troops(troop_type_id: int, count: int) -> tuple:
    """
    Build a training command.
    
    NOTE: The exact opcode for training has NOT been captured yet.
    This is a placeholder structure based on protocol analysis.
    When we capture a live training session, we'll know the exact opcode.
    
    Returns: (msg_id, payload_bytes)
    """
    inner = {
        1: troop_type_id,
        2: count,
    }
    payload = encode_message({
        1: 0,
        2: encode_message(inner),
    })
    return (102, payload)


def build_train_infantry(count: int = 5) -> tuple:
    """Train infantry troops. Returns (msg_id, payload_bytes)."""
    return build_train_troops(TROOP_INFANTRY_T4, count)


def build_train_cavalry(count: int = 5) -> tuple:
    """Train cavalry troops. Returns (msg_id, payload_bytes)."""
    return build_train_troops(TROOP_CAVALRY_T4, count)


def build_train_archer(count: int = 5) -> tuple:
    """Train archer troops. Returns (msg_id, payload_bytes)."""
    return build_train_troops(TROOP_ARCHER_T4, count)


def build_train_siege(count: int = 5) -> tuple:
    """Train siege troops. Returns (msg_id, payload_bytes)."""
    return build_train_troops(TROOP_SIEGE_T4, count)


def build_gather_resource(resource_node_id: int, troop_comps: List[Dict] = None) -> tuple:
    """
    Build a gather command (send troops to resource node).
    
    Captured from live Frida session. Opcode 1012.
    
    Args:
        resource_node_id: Entity ID of the resource node on the map
        troop_comps: List of {type_id, count, tier} dicts. 
                     Default: send mixed T4 infantry+cavalry
    
    Returns: (msg_id, payload_bytes)
    """
    if troop_comps is None:
        troop_comps = [
            {"type_id": TROOP_INFANTRY_T4, "count": 1, "flag": 1},
            {"type_id": TROOP_CAVALRY_T4, "count": 1, "flag": 2},
        ]
    
    troop_entries = []
    for comp in troop_comps:
        entry = encode_message({
            1: comp["type_id"],
            3: comp.get("count", 1),
            2: comp.get("flag", 1),
        })
        troop_entries.append(entry)
    
    inner = {
        1: troop_entries,
        4: resource_node_id,
        14: 1,
    }
    
    payload = encode_message({
        1: 1012,
        2: encode_message(inner),
    })
    return (1012, payload)


def build_march_move(target_x: float, target_y: float, 
                     march_type: int = 0) -> tuple:
    """
    Build a march/move command (move troops to coordinates).
    
    Captured from live Frida session. Opcode 1004.
    
    Args:
        target_x: Target X coordinate
        target_y: Target Y coordinate
        march_type: 0=normal, 1=attack
    
    Returns: (msg_id, payload_bytes)
    """
    x_bytes = struct.pack('<f', target_x)
    y_bytes = struct.pack('<f', target_y)
    
    inner = {
        1: {1: x_bytes, 2: y_bytes},
        5: 1,
    }
    
    payload = encode_message({
        1: 1004,
        2: encode_message(inner),
    })
    return (1004, payload)


def build_troop_management(action: int = 0, sub_action: int = 1) -> tuple:
    """
    Build a troop management command.
    
    Captured from live Frida session. Opcode 1161.
    
    Returns: (msg_id, payload_bytes)
    """
    inner = {
        1: encode_message({1: 0, 2: 0}),
        2: sub_action,
    }
    payload = encode_message({
        1: 1161,
        2: encode_message(inner),
    })
    return (1161, payload)


def build_alliance_help() -> tuple:
    """Request alliance help. Returns (msg_id, payload_bytes)."""
    return (1205, b"")


def build_keepalive() -> tuple:
    """Send keepalive. Returns (msg_id, payload_bytes)."""
    return (9, encode_message({1: 1}))


def build_use_speedup(item_id: int = 60001, count: int = 1) -> tuple:
    """
    Use a speedup item from inventory.
    
    Returns: (msg_id, payload_bytes)
    """
    inner = {
        1: item_id,
        2: count,
    }
    payload = encode_message({
        1: 0,
        2: encode_message(inner),
    })
    return (120, payload)


def build_camera_position(entity_id: int, x: float, y: float, 
                          zoom: float = 1.0) -> tuple:
    """
    Update camera/view position. Opcode 1050.
    
    Returns: (msg_id, payload_bytes)
    """
    inner = {
        1: entity_id,
        2: int(x * 1000),
        3: encode_message({1: int(x * 1000), 2: int(y * 1000)}),
        4: encode_message({1: 0, 2: 0}),
    }
    payload = encode_message({
        1: 1050,
        2: encode_message(inner),
    })
    return (1050, payload)


def build_player_state(state_flag: int = 1) -> tuple:
    """
    Set player online/away state. Opcode 925.
    
    Args:
        state_flag: 1=online, 0=away
    
    Returns: (msg_id, payload_bytes)
    """
    payload = encode_message({
        1: 925,
        2: encode_message({1: state_flag}),
    })
    return (925, payload)


# ──────────────────────────────────────────────────────────────────────
# Command Registry (used by JSON loader and bot)
# ──────────────────────────────────────────────────────────────────────

COMMAND_REGISTRY = {
    "train_infantry": {
        "builder": build_train_infantry,
        "category": "training",
        "description": "Train T4 infantry troops at barracks",
        "repeatable": True,
        "cooldown_s": 30.0,
    },
    "train_cavalry": {
        "builder": build_train_cavalry,
        "category": "training",
        "description": "Train T4 cavalry troops at stable",
        "repeatable": True,
        "cooldown_s": 30.0,
    },
    "train_archer": {
        "builder": build_train_archer,
        "category": "training",
        "description": "Train T4 archer troops at archery range",
        "repeatable": True,
        "cooldown_s": 30.0,
    },
    "train_siege": {
        "builder": build_train_siege,
        "category": "training",
        "description": "Train T4 siege troops at workshop",
        "repeatable": True,
        "cooldown_s": 30.0,
    },
    "gather_food": {
        "builder": lambda: build_gather_resource(0, [{"type_id": TROOP_INFANTRY_T4, "count": 1, "flag": 1}]),
        "category": "gathering",
        "description": "Send troops to gather food",
        "repeatable": True,
        "cooldown_s": 10.0,
    },
    "gather_wood": {
        "builder": lambda: build_gather_resource(0, [{"type_id": TROOP_CAVALRY_T4, "count": 1, "flag": 1}]),
        "category": "gathering",
        "description": "Send troops to gather wood",
        "repeatable": True,
        "cooldown_s": 10.0,
    },
    "gather_stone": {
        "builder": lambda: build_gather_resource(0, [{"type_id": TROOP_ARCHER_T4, "count": 1, "flag": 1}]),
        "category": "gathering",
        "description": "Send troops to gather stone",
        "repeatable": True,
        "cooldown_s": 10.0,
    },
    "gather_gold": {
        "builder": lambda: build_gather_resource(0, [{"type_id": TROOP_SIEGE_T4, "count": 1, "flag": 1}]),
        "category": "gathering",
        "description": "Send troops to gather gold",
        "repeatable": True,
        "cooldown_s": 10.0,
    },
    "alliance_help": {
        "builder": build_alliance_help,
        "category": "social",
        "description": "Request alliance help for all buildings/research",
        "repeatable": True,
        "cooldown_s": 60.0,
    },
    "keepalive": {
        "builder": build_keepalive,
        "category": "system",
        "description": "Keep connection alive",
        "repeatable": True,
        "cooldown_s": 5.0,
    },
    "player_online": {
        "builder": lambda: build_player_state(1),
        "category": "social",
        "description": "Set player online status",
        "repeatable": False,
        "cooldown_s": 0,
    },
    "use_speedup": {
        "builder": build_use_speedup,
        "category": "items",
        "description": "Use 1h speedup item",
        "repeatable": True,
        "cooldown_s": 0,
    },
}
