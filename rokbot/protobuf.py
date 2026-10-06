"""
Protobuf codec — lightweight encoder/decoder for RoK's protobuf wire format.

No external protobuf library required. Handles varints, length-delimited,
fixed32, and fixed64 wire types.
"""
from __future__ import annotations

import struct
from typing import Any, Dict, Tuple


def encode_varint(value: int) -> bytes:
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def decode_varint(data: bytes, offset: int = 0) -> Tuple[int, int]:
    result = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        result |= (byte & 0x7F) << shift
        offset += 1
        if (byte & 0x80) == 0:
            return result, offset
        shift += 7
    raise ValueError("Truncated varint")


def encode_field_varint(field_num: int, value: int) -> bytes:
    return encode_varint((field_num << 3) | 0) + encode_varint(value)


def encode_field_bytes(field_num: int, data: bytes) -> bytes:
    return encode_varint((field_num << 3) | 2) + encode_varint(len(data)) + data


def encode_field_fixed32(field_num: int, value: int) -> bytes:
    return encode_varint((field_num << 3) | 5) + struct.pack("<I", value & 0xFFFFFFFF)


def encode_field_fixed64(field_num: int, value: int) -> bytes:
    return encode_varint((field_num << 3) | 1) + struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)


def encode_message(fields: Dict[int, Any]) -> bytes:
    result = bytearray()
    for field_num in sorted(fields.keys()):
        value = fields[field_num]
        if isinstance(value, list):
            for v in value:
                result.extend(_encode_single(field_num, v))
        else:
            result.extend(_encode_single(field_num, value))
    return bytes(result)


def _encode_single(field_num: int, value: Any) -> bytes:
    if isinstance(value, int):
        return encode_field_varint(field_num, value)
    elif isinstance(value, (bytes, bytearray)):
        return encode_field_bytes(field_num, bytes(value))
    elif isinstance(value, str):
        return encode_field_bytes(field_num, value.encode("utf-8"))
    elif isinstance(value, dict):
        nested = encode_message(value)
        return encode_field_bytes(field_num, nested)
    raise TypeError(f"Unsupported type {type(value)} for field {field_num}")


def decode_message(data: bytes) -> Dict[int, Any]:
    fields: Dict[int, Any] = {}
    offset = 0
    while offset < len(data):
        try:
            tag, offset = decode_varint(data, offset)
        except ValueError:
            break
        field_num = tag >> 3
        wire_type = tag & 0x07
        if field_num == 0:
            break

        if wire_type == 0:
            value, offset = decode_varint(data, offset)
        elif wire_type == 1:
            if offset + 8 > len(data):
                break
            value = struct.unpack("<Q", data[offset:offset + 8])[0]
            offset += 8
        elif wire_type == 2:
            length, offset = decode_varint(data, offset)
            if offset + length > len(data):
                break
            value = data[offset:offset + length]
            offset += length
        elif wire_type == 5:
            if offset + 4 > len(data):
                break
            value = struct.unpack("<I", data[offset:offset + 4])[0]
            offset += 4
        else:
            break

        if field_num in fields:
            if not isinstance(fields[field_num], list):
                fields[field_num] = [fields[field_num]]
            fields[field_num].append(value)
        else:
            fields[field_num] = value
    return fields


def decode_deep_proto(data: bytes, depth: int = 0) -> Any:
    """
    Recursively decode protobuf bytes into nested dicts/lists,
    converting ASCII strings and sub-messages.
    """
    if depth > 6 or len(data) < 2:
        return data
    try:
        fields = decode_message(data)
    except Exception:
        return data
    if not fields:
        return data

    result: Dict[str, Any] = {}
    for fn, val in sorted(fields.items()):
        if isinstance(val, (bytes, bytearray)):
            if len(val) >= 2:
                sub = decode_deep_proto(bytes(val), depth + 1)
                if isinstance(sub, dict):
                    result[f"f{fn}"] = sub
                else:
                    try:
                        s = bytes(val).decode("utf-8")
                        if all(32 <= ord(c) < 127 for c in s):
                            result[f"f{fn}"] = s
                        else:
                            result[f"f{fn}"] = val
                    except Exception:
                        result[f"f{fn}"] = val
            else:
                result[f"f{fn}"] = val
        elif isinstance(val, list):
            items = []
            for item in val:
                if isinstance(item, (bytes, bytearray)) and len(item) >= 2:
                    sub = decode_deep_proto(bytes(item), depth + 1)
                    items.append(sub)
                else:
                    items.append(item)
            result[f"f{fn}"] = items
        else:
            result[f"f{fn}"] = val
    return result


def u32_to_f32(bits: int) -> float:
    """Convert a 32-bit unsigned integer to IEEE-754 32-bit float."""
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def f32_to_u32(val: float) -> int:
    """Convert IEEE-754 32-bit float to 32-bit unsigned integer."""
    return struct.unpack("<I", struct.pack("<f", val))[0]

