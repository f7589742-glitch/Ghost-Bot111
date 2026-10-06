"""Opcode 121 (liquid resources) and Opcode 1002/125 city-state parser.

Decodes:
1) Opcode 121: The definitive, authoritative liquid resource balance in city.
   - Tag 1: repeated resource sub-messages:
       - Tag 1: resource type (1=Food, 2=Wood, 3=Stone, 4=Gold, 5=Gems)
       - Tag 2: current liquid amount (exact units, e.g. 7,661,297)

2) Opcode 1002: Governor profile and city hall data.
   - sub_f1 Tag 2: role_id
   - sub_f1 Tag 4: city_hall_level
   - sub_f1 Tag 14: power
   - sub_f1 Tag 34 or 23: kingdom_id
   - sub_f1 Tag 9 -> Tag 7: governor name
"""
from typing import Any, Dict, List, Optional

try:
    from rok_headless_bot import ProtobufCodec
except Exception:
    try:
        import sys as _sys
        _sys.path.insert(0, "python")
        from headless_client import ProtobufCodec
    except Exception:
        ProtobufCodec = None


def _decode(maybe_bytes) -> Optional[Dict[int, Any]]:
    if ProtobufCodec is None or not isinstance(maybe_bytes, (bytes, bytearray)):
        return None
    try:
        m = ProtobufCodec.decode_message(bytes(maybe_bytes))
        return m if isinstance(m, dict) else None
    except Exception:
        return None


def parse_resources_121(raw_input: Any) -> Optional[Dict[str, int]]:
    """Parse Opcode 121 (liquid resources) into exact integer amounts.

    Returns dict:
    {
        'food': int,
        'wood': int,
        'stone': int,
        'gold': int,
        'gems': int
    }
    """
    if raw_input is None:
        return None

    d = None
    if isinstance(raw_input, (bytes, bytearray)):
        d = _decode(raw_input)
    elif isinstance(raw_input, dict):
        d = raw_input

    if not isinstance(d, dict):
        return None

    # Handle wrapper {1: 121, 2: b'...'}
    if d.get(1) == 121:
        p2 = d.get(2)
        if isinstance(p2, (bytes, bytearray)):
            dec_p = _decode(p2)
            if dec_p:
                d = dec_p
        elif isinstance(p2, dict):
            d = p2

    items = d.get(1, [])
    if isinstance(items, (bytes, bytearray, dict)):
        items = [items]

    rss_map = {1: "food", 2: "wood", 3: "stone", 4: "gold", 5: "gems"}
    result = {"food": 0, "wood": 0, "stone": 0, "gold": 0, "gems": 0}
    found_any = False

    for item in items:
        it_d = None
        if isinstance(item, (bytes, bytearray)):
            it_d = _decode(item)
        elif isinstance(item, dict):
            it_d = item

        if isinstance(it_d, dict):
            rtype = it_d.get(1)
            if rtype in rss_map:
                amt = int(it_d.get(2, 0) or 0)
                result[rss_map[rtype]] = amt
                found_any = True

    return result if found_any else None


def parse_city_state_1002(raw_input: Any) -> Optional[Dict[str, Any]]:
    """Parse Opcode 1002 payload into governor profile metadata.

    Returns dict:
    {
        'role_id': str,
        'name': str,
        'kingdom_id': int,
        'city_hall_level': int,
        'power': int,
        'building_food': int,
        'building_wood': int,
        'building_stone': int,
        'building_gold': int
    }
    """
    if raw_input is None:
        return None

    if isinstance(raw_input, (bytes, bytearray)):
        d = _decode(raw_input)
        if not d:
            return None
    elif isinstance(raw_input, dict):
        d = raw_input
    else:
        return None

    if 1 in d and isinstance(d[1], int) and d[1] in (125, 1002, 121):
        p2 = d.get(2)
        if isinstance(p2, (bytes, bytearray)):
            dec_p2 = _decode(p2)
            if dec_p2:
                d = dec_p2

    snap: Dict[str, Any] = {
        "food": 0,
        "wood": 0,
        "stone": 0,
        "gold": 0,
        "gems": 0,
        "power": 0,
        "city_hall_level": 0,
        "kingdom_id": 0,
        "name": "",
        "role_id": ""
    }

    try:
        f1 = d.get(1)
        sub_f1 = None
        if isinstance(f1, (bytes, bytearray)):
            sub_f1 = _decode(f1)
        elif isinstance(f1, dict):
            sub_f1 = f1

        target_dict = sub_f1 if sub_f1 else d

        # Role ID
        if target_dict.get(2) and isinstance(target_dict.get(2), int):
            snap["role_id"] = str(target_dict[2])

        # City Hall Level (Tag 4)
        if target_dict.get(4) and isinstance(target_dict.get(4), int):
            snap["city_hall_level"] = int(target_dict[4])

        # Power (Tag 14)
        if target_dict.get(14) and isinstance(target_dict.get(14), int) and target_dict[14] > 1000:
            snap["power"] = int(target_dict[14])

        # Kingdom ID
        kd = target_dict.get(34) or target_dict.get(23) or d.get(23) or 0
        if isinstance(kd, int):
            snap["kingdom_id"] = int(kd)

        # Tag 9 -> Name & Building Reserves
        tag9_raw = target_dict.get(9)
        tag9 = None
        if isinstance(tag9_raw, (bytes, bytearray)):
            tag9 = _decode(tag9_raw)
        elif isinstance(tag9_raw, dict):
            tag9 = tag9_raw

        if tag9:
            name_val = tag9.get(7)
            if isinstance(name_val, (bytes, bytearray)):
                try:
                    snap["name"] = bytes(name_val).decode("utf-8", "ignore")
                except Exception:
                    pass
            elif isinstance(name_val, str):
                snap["name"] = name_val

        # If name wasn't in Tag 9, check Tag 12
        if not snap.get("name"):
            tag12_raw = target_dict.get(12)
            tag12 = _decode(tag12_raw) if isinstance(tag12_raw, (bytes, bytearray)) else (tag12_raw if isinstance(tag12_raw, dict) else None)
            if tag12 and tag12.get(2):
                n2 = tag12.get(2)
                if isinstance(n2, (bytes, bytearray)):
                    try:
                        snap["name"] = bytes(n2).decode("utf-8", "ignore")
                    except Exception:
                        pass
                elif isinstance(n2, str):
                    snap["name"] = n2

        has_data = bool(snap.get("role_id") or snap.get("power") or snap.get("city_hall_level"))
        return snap if has_data else None

    except Exception:
        return None
