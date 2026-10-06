from __future__ import annotations

import struct


MASK30 = 0x3FFFFFFF


class ProtobufCodec:
    @staticmethod
    def encode_varint(value: int) -> bytes:
        result = bytearray()
        while value > 0x7F:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value & 0x7F)
        return bytes(result)

    @staticmethod
    def encode_field_varint(field_num: int, value: int) -> bytes:
        tag = (field_num << 3) | 0
        return ProtobufCodec.encode_varint(tag) + ProtobufCodec.encode_varint(value)

    @staticmethod
    def encode_field_bytes(field_num: int, data: bytes) -> bytes:
        tag = (field_num << 3) | 2
        return ProtobufCodec.encode_varint(tag) + ProtobufCodec.encode_varint(len(data)) + data

    @staticmethod
    def encode_field_string(field_num: int, s: str) -> bytes:
        data = s.encode('utf-8')
        tag = (field_num << 3) | 2
        return ProtobufCodec.encode_varint(tag) + ProtobufCodec.encode_varint(len(data)) + data

    @staticmethod
    def encode_message(fields: dict) -> bytes:
        result = bytearray()
        for fn in sorted(fields.keys()):
            v = fields[fn]
            if isinstance(v, int):
                result.extend(ProtobufCodec.encode_field_varint(fn, v))
            elif isinstance(v, str):
                result.extend(ProtobufCodec.encode_field_string(fn, v))
            elif isinstance(v, bytes):
                result.extend(ProtobufCodec.encode_field_bytes(fn, v))
            elif isinstance(v, dict):
                inner = ProtobufCodec.encode_message(v)
                tag = (fn << 3) | 2
                result.extend(ProtobufCodec.encode_varint(tag) + ProtobufCodec.encode_varint(len(inner)))
                result.extend(inner)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        inner = ProtobufCodec.encode_message(item)
                        tag = (fn << 3) | 2
                        result.extend(ProtobufCodec.encode_varint(tag) + ProtobufCodec.encode_varint(len(inner)))
                        result.extend(inner)
                    elif isinstance(item, int):
                        result.extend(ProtobufCodec.encode_field_varint(fn, item))
        return bytes(result)


def _build_auth_sub(access_token: str, player_id: str, app_id: int = 2104267) -> bytes:
    auth = {
        1: player_id.encode('utf-8'),
        2: access_token.encode('utf-8'),
        3: app_id,
        4: b'pc',
        5: 1,
    }
    return ProtobufCodec.encode_message(auth)


def _build_device_fingerprint() -> bytes:
    fp = {
        1: 3,
        2: b'win',
        3: 'DESKTOP-U0L0GKB',
        4: b'x86-64',
        5: b'ASUSTeK-B660M-DS3H DDR4',
        6: b'\x00' * 16,
        7: 1054,
        8: b'1.1.9.19',
        9: 1,
    }
    return ProtobufCodec.encode_message(fp)


def build_full_login(
    player_id: str,
    access_token: str,
    app_id: int = 2104267,
    server: str = "",
) -> bytes:
    inner = {
        1: 14,
        9: 1,
        4: player_id.encode('utf-8'),
    }

    auth_data = _build_auth_sub(access_token, player_id, app_id)
    inner[7] = auth_data

    inner[5] = _build_device_fingerprint()

    top = {
        1: 14,
        2: ProtobufCodec.encode_message(inner),
    }
    return ProtobufCodec.encode_message(top)