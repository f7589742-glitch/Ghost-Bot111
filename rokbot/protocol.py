"""
Protocol layer — frame parsing, greeting handling, and wire format.

Wire format (TCP port 3101):
    [2-byte BE length][encrypted payload]

Greeting (first server → client frame):
    Unencrypted protobuf: {1: greeting_id, 2: {1: n1, 2: n2}}
    Seeds: seed1_TX = ((n2 // 3) + 0x2766) & 0x3FFFFFFF
           seed2_RX = ((n1 >> 1) + 0x400) & 0x3FFFFFFF
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .protobuf import (
    decode_message,
    encode_field_bytes,
    encode_field_varint,
    encode_message,
)


MASK30 = 0x3FFFFFFF


@dataclass
class GreetingNonce:
    """Parsed server greeting with nonce and derived seeds."""
    raw: bytes
    field1: int
    sub1: int
    sub2: int
    seed1: int
    seed2: int

    def __repr__(self) -> str:
        return (
            f"GreetingNonce(n1=0x{self.sub1:08x}, n2=0x{self.sub2:08x}, "
            f"seed1_TX=0x{self.seed1:08x}, seed2_RX=0x{self.seed2:08x})"
        )


def derive_seeds(n1: int, n2: int) -> Tuple[int, int]:
    seed1 = ((n2 // 3) + 0x2766) & MASK30
    seed2 = ((n1 >> 1) + 0x400) & MASK30
    return seed1, seed2


def parse_greeting(raw: bytes) -> GreetingNonce:
    if len(raw) < 4:
        raise ValueError(f"Greeting too short: {len(raw)} bytes")
    protobuf = raw[2:]
    fields = decode_message(protobuf)
    field1 = fields.get(1, 0)
    field2 = fields.get(2, b"")
    sub1, sub2 = 0, 0
    if isinstance(field2, (bytes, bytearray)) and len(field2) >= 2:
        sub_fields = decode_message(field2)
        sub1 = sub_fields.get(1, 0)
        sub2 = sub_fields.get(2, 0)
    seed1, seed2 = derive_seeds(sub1, sub2)
    return GreetingNonce(raw=raw, field1=field1, sub1=sub1, sub2=sub2, seed1=seed1, seed2=seed2)


@dataclass
class Frame:
    """A single decrypted protocol frame."""
    length: int
    payload: bytes
    raw: bytes = b""

    def __repr__(self) -> str:
        preview = self.payload[:30].hex()
        suffix = "..." if len(self.payload) > 30 else ""
        return f"Frame(len={self.length}, payload={preview}{suffix})"


class FrameParser:
    """
    Accumulates TCP stream bytes and yields complete frames.

    Handles fragmentation and compound frames (multiple RoK frames
    concatenated in a single TCP read).
    """

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data: bytes) -> List[Frame]:
        self._buffer.extend(data)
        return self._extract_frames()

    def _extract_frames(self) -> List[Frame]:
        frames = []
        while True:
            frame, consumed = self._try_parse()
            if frame is None:
                break
            frames.append(frame)
            del self._buffer[:consumed]
        return frames

    def _try_parse(self) -> Tuple[Optional[Frame], int]:
        if len(self._buffer) < 2:
            return None, 0
        length = (self._buffer[0] << 8) | self._buffer[1]
        total = 2 + length
        if len(self._buffer) < total:
            return None, 0
        payload = bytes(self._buffer[2:total])
        raw = bytes(self._buffer[:total])
        return Frame(length=length, payload=payload, raw=raw), total

    @staticmethod
    def build_frame(payload: bytes) -> bytes:
        return len(payload).to_bytes(2, "big") + payload

    @property
    def buffered(self) -> int:
        return len(self._buffer)

    def reset(self):
        self._buffer.clear()


import os

# Official capture template (556 bytes) from real game client
_TEMPLATE_HEX = (
    "080e12a70462063632303535390801da010a12000a02706322001a00ba011b726f63676174652e"
    "6c696c69746867616d652e636f6d3a333130312210323432383035343131303635353932357a01"
    "31a2012037313234613134376366373664643733373863393662666462336262343864345a0931"
    "2e312e31302e3231c0010470013a3818cbb780011220442d6e7a4e47466861777349455a335830"
    "577a4d7a43564b753676666a5a2d5028010a093236303736383035342202706332dc027a1a4469"
    "7265637433442031312e30205b6c6576656c2031312e315d2a006a103234323830353431313036"
    "35353932353200620261724a023131121a636f6d2e6c696c69746867616d65732e726f6b2e7063"
    "2e696e74c2010877696e33326370755209312e312e31302e32318a01174e564944494120476546"
    "6f726365205254582033303530920124313274682047656e20496e74656c28522920436f726528"
    "544d292069352d31323630304b5a0377696e9a010431373830420377696ea20104313030318201"
    "0531363135300a053130303433ba012437356137643065312d343238662d346462322d62316463"
    "2d376437313131613434616332b201133135382e3134302e32302e34323a353834363922267632"
    "62303565623435352d306631332d346639622d383263352d343338386134353732366664720377"
    "696e1a0d73656c662d6c696c6974682d313a0d3135382e3134302e32302e34326a0d3135382e31"
    "34302e32302e34324801"
)
_OLD_TOKEN = b"D-nzNGFhawsIEZ3X0WzMzCVKu6vfjZ-P"
_OLD_UID = b"260768054"

def build_login_frame(
    player_id: str = "234122368",
    access_token: str = "D-jBUVRjsc73tV0BsA7K3O261l02Ob-P",
    app_id: int = 2104267,
    platform: str = "pc",
    server: str = "",
    use_full_capture: bool = True,
) -> bytes:

    """
    Build the official client login frame for Rise of Kingdoms.
    When use_full_capture=True, it patches the 556-byte official capture
    template by decoding it and re-encoding with our identity fields, so
    protobuf lengths stay correct for any id/token length:
      inner.f4 = player_id, inner.f6(device).f13 = player_id,
      inner.f7(auth) = {1: player_id, 2: token, 3: app_id, 4: platform, 5: 1}.
    (The old bytes.replace hack only swapped two fields and silently left a
    second stale uid "2428054110655925" in f4/f6.f13, binding the session to
    a limbo identity: login ACKs 241 but role queries go unanswered.)
    """
    if use_full_capture:
        try:
            return _patch_login_template(player_id, access_token, app_id, platform)
        except Exception:
            pass  # fall through to minimal login

    inner: dict = {1: 1, 9: 1}
    inner[4] = encode_message({6: str(player_id).encode("utf-8")})
    auth: dict = {
        1: str(player_id).encode("utf-8"),
        2: access_token.encode("utf-8"),
        3: app_id,
        4: platform.encode("utf-8"),
        5: 1,
    }
    inner[7] = encode_message(auth)
    top = {1: 14, 2: encode_message(inner)}
    return encode_message(top)


def build_android_login_frame(
    app_uid: str,
    access_token: str,
    device_udid: str = "F682A5114F7DD6AD7995F8ED2D6719BA",
    app_id: int = 2104267,
    src_port: int = 50000,
) -> bytes:
    """
    Live-style Android login WITHOUT f14 role binding.
    Byte-matched against live_ammar_switch.pcap conn 48734 (real client):
      inner keys [1,4,6,7,9,11,12,13,15,20,21,23,24,27], auth f7 without f6.
    Two fields MUST be live values (proven 2026-09-10):
      - f6.f13 = device UDID (NOT app_uid — fleet_manager's old choice;
        the mismatch withheld S2C Op 15 role-attach);
      - f6.f22 = "<ip>:<tcp-source-port>" with our REAL local source port
        (live sends its actual conn port, e.g. :48734; the IP part is a
        stale constant even in live captures).
    """
    auth = {
        1: str(app_uid).encode("utf-8"),
        2: access_token.encode("utf-8"),
        3: int(app_id),
        4: b"and",
        5: 1,
    }
    device_profile = {
        1: b"10043",
        2: b"com.lilithgame.roc.gp",
        3: b"self-lilith-0.7",
        4: b"",
        5: b"13c26fe3fb9d11b6",
        6: b"ee7df9d3-442c-4ad8-abed-9fc5f89928ba",
        7: b"194.176.99.80",
        8: b"android",
        9: b"14",
        10: b"1.1.11.25",
        11: b"2311DRK48C_Simulator",
        12: b"en",
        13: str(device_udid).encode("utf-8"),
        14: b"Redmi",
        15: b"OpenGL ES 3.1 v1",
        16: b"2993",
        17: b"Adreno (TM) 750",
        18: b"x86-64",
        19: b"1280",
        20: b"720",
        22: f"194.176.99.80:{int(src_port)}".encode("ascii"),
        23: str(device_udid).encode("utf-8"),
        24: b"Qualcomm Technologies, Inc MSM8998",
    }
    inner = {
        1: 1,
        4: str(device_udid).encode("utf-8"),
        6: encode_message(device_profile),
        7: encode_message(auth),
        9: 1,
        11: b"1.1.11.25",
        12: b"628788",
        13: b"194.176.99.80",
        15: b"7",
        20: b"e5494c1f6aad311adc9b64f1288e9b8d",
        21: 18446744073709551615,
        23: b"rocgate.lilithgame.com:3101",
        24: 2,
        27: b"\x12\x00\n\x03and\"\x00\x1a\x00",
    }
    top = {1: 14, 2: encode_message(inner)}
    return encode_message(top)


def _order_fields(pairs) -> bytes:
    """Concatenate pre-encoded field bytes in the given (live) order."""
    return b"".join(p for _, p in pairs)


def build_ordered_login_frame(
    app_uid: str,
    access_token: str,
    device_udid: str = "F682A5114F7DD6AD7995F8ED2D6719BA",
    app_id: int = 2104267,
    src_port: int = 50000,
) -> bytes:
    """
    Byte-order-exact Android login (Opcode 14).
    Same values as build_android_login_frame, but fields are emitted in the
    live client's declaration order (live_ammar_switch.pcap conn 48734):
      inner: [12, 1, 27, 23, 4, 15, 20, 21, 11, 24, 7, 6, 13, 9]
      auth:  [3, 2, 5, 1, 4]
      device:[15, 5, 13, 6, 12, 9, 2, 24, 10, 17, 18, 11, 19, 8, 20,
              16, 1, 23, 22, 4, 14, 3, 7]
    Rationale: if the gate's login parser is positional/hand-rolled rather
    than tag-driven, sorted order feeds values into the wrong slots (login
    ACKs but role-attach never happens). Verified byte-identical to live
    (modulo src port) — see verify_login_bytes.py.
    """
    uid = str(app_uid).encode("ascii")
    tok = access_token.encode("ascii")
    dev = str(device_udid).encode("ascii")

    auth = (
        encode_field_varint(3, int(app_id))
        + encode_field_bytes(2, tok)
        + encode_field_varint(5, 1)
        + encode_field_bytes(1, uid)
        + encode_field_bytes(4, b"and")
    )
    device = (
        encode_field_bytes(15, b"OpenGL ES 3.1 v1")
        + encode_field_bytes(5, b"13c26fe3fb9d11b6")
        + encode_field_bytes(13, dev)
        + encode_field_bytes(6, b"ee7df9d3-442c-4ad8-abed-9fc5f89928ba")
        + encode_field_bytes(12, b"en")
        + encode_field_bytes(9, b"14")
        + encode_field_bytes(2, b"com.lilithgame.roc.gp")
        + encode_field_bytes(24, b"Qualcomm Technologies, Inc MSM8998")
        + encode_field_bytes(10, b"1.1.11.25")
        + encode_field_bytes(17, b"Adreno (TM) 750")
        + encode_field_bytes(18, b"x86-64")
        + encode_field_bytes(11, b"2311DRK48C_Simulator")
        + encode_field_bytes(19, b"1280")
        + encode_field_bytes(8, b"android")
        + encode_field_bytes(20, b"720")
        + encode_field_bytes(16, b"2993")
        + encode_field_bytes(1, b"10043")
        + encode_field_bytes(23, dev)
        + encode_field_bytes(22, f"194.176.99.80:{int(src_port)}".encode("ascii"))
        + encode_field_bytes(4, b"")
        + encode_field_bytes(14, b"Redmi")
        + encode_field_bytes(3, b"self-lilith-0.7")
        + encode_field_bytes(7, b"194.176.99.80")
    )
    inner = (
        encode_field_bytes(12, b"628788")
        + encode_field_varint(1, 1)
        + encode_field_bytes(27, b"\x12\x00\n\x03and\"\x00\x1a\x00")
        + encode_field_bytes(23, b"rocgate.lilithgame.com:3101")
        + encode_field_bytes(4, dev)
        + encode_field_bytes(15, b"7")
        + encode_field_bytes(20, b"e5494c1f6aad311adc9b64f1288e9b8d")
        + encode_field_varint(21, 18446744073709551615)
        + encode_field_bytes(11, b"1.1.11.25")
        + encode_field_varint(24, 2)
        + encode_field_bytes(7, auth)
        + encode_field_bytes(6, device)
        + encode_field_bytes(13, b"194.176.99.80")
        + encode_field_varint(9, 1)
    )
    return encode_message({1: 14, 2: inner})


def build_role_login_frame(
    app_uid: str,
    access_token: str,
    role_id: int,
    device_udid: str = "F682A5114F7DD6AD7995F8ED2D6719BA",
    app_id: int = 2104267,
) -> bytes:
    """
    Role-bound Android login (Opcode 14), ported from the live-proven
    fleet_manager.build_dynamic_login_payload (smart_troop_trainer flow).
    Binds app_uid + role DIRECTLY in the login:
      inner.f4 = device_udid, inner.f14 = role_id (int),
      inner.f7(auth) = {1: app_uid, 2: token, 3: app_id, 4: "and", 5: 1, 6: role_id}.
    Role/world data (S2C Op 15/302/9999) only flows for role-bound logins;
    plain template/minimal logins ACK 241 but stay in limbo.
    Device profile/IP strings are informational template values.
    """
    auth_payload = {
        1: str(app_uid).encode("utf-8"),
        2: str(access_token).encode("utf-8"),
        3: int(app_id),
        4: b"and",
        5: 1,
        6: int(role_id),
    }
    device_profile = {
        1: b"10043",
        2: b"com.lilithgame.roc.gp",
        3: b"self-lilith-0.7",
        4: b"",
        5: b"13c26fe3fb9d11b6",
        6: b"ee7df9d3-442c-4ad8-abed-9fc5f89928ba",
        7: b"194.176.99.80",
        8: b"android",
        9: b"14",
        10: b"1.1.11.25",
        11: b"2311DRK48C_Simulator",
        12: b"en",
        13: str(device_udid).encode("utf-8"),
        14: b"Redmi",
        15: b"OpenGL ES 3.1 v1",
        16: b"2993",
        17: b"Adreno (TM) 750",
        18: b"x86-64",
        19: b"1280",
        20: b"720",
        22: b"194.176.99.80:50000",
        23: str(device_udid).encode("utf-8"),
        24: b"Qualcomm Technologies, Inc MSM8998",
    }
    inner = {
        1: 1,
        4: str(device_udid).encode("utf-8"),
        6: encode_message(device_profile),
        7: encode_message(auth_payload),
        9: 1,
        11: b"1.1.11.25",
        12: b"628788",
        13: b"194.176.99.80",
        14: int(role_id),
        15: b"7",
        20: b"e5494c1f6aad311adc9b64f1288e9b8d",
        21: 18446744073709551615,
        23: b"rocgate.lilithgame.com:3101",
        24: 2,
        27: b"\x12\x00\n\x03and\"\x00\x1a\x00",
    }
    top = {1: 14, 2: encode_message(inner)}
    return encode_message(top)


def _patch_login_template(
    player_id: str, access_token: str, app_id: int, platform: str
) -> bytes:
    """Decode the capture template, patch identity fields, re-encode."""
    pid = str(player_id).encode("ascii")
    template_bytes = bytes.fromhex(_TEMPLATE_HEX)
    top = decode_message(template_bytes)
    inner = decode_message(bytes(top[2]))

    inner[4] = pid

    device = decode_message(bytes(inner[6]))
    device[13] = pid
    inner[6] = encode_message(device)

    auth = decode_message(bytes(inner[7]))
    auth[1] = pid
    auth[2] = access_token.encode("ascii")
    auth[3] = int(app_id)
    auth[4] = platform.encode("ascii")
    auth[5] = 1
    inner[7] = encode_message(auth)

    top[2] = encode_message(inner)
    return encode_message(top)


def build_keepalive() -> bytes:
    # Live-verified client heartbeat: op 9 with empty field 2.
    # (An earlier revision sent op 6 here; the server tolerates it but the
    # real client sends 9 — match it to avoid fingerprinting.)
    return encode_message({1: 9, 2: b""})


def build_empty_frame() -> bytes:
    return b""
