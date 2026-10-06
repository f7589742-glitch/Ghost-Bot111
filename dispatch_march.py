"""
dispatch_march.py — Single-character headless gather dispatch over TCP 3101.

Replays the live-proven march chain per-character:
  login (role-bound) -> role verify/switch -> map viewports -> node select
  -> 1004 viewport -> 1050 inspect -> (1051 ack) -> 1004 -> 9726
  -> Op8 SendTroopConfirm -> 1012 dispatch -> confirm window.

Acceptance (see rokbot/decoder.py): universal ACK op1 {2:1}, or S2C ops
903/365/1013/1014/1005/1023/1024. Op1 {2:135} = commander not owned,
{2:155} = node unreachable (live-log documented).

Usage:
  python dispatch_march.py --list
  python dispatch_march.py --char char_01 --target wood
  python dispatch_march.py --char char_02 --node 3663106 --x 4468.71 --y 4196.4
  python dispatch_march.py --char char_01 --target food --commander 15 --army "19166:200"
  python dispatch_march.py --char char_02 --target food --hold 120

Only enabled characters from accounts_fleet.json are used. No secrets are
printed; a metric/anomaly-only summary is emitted instead.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import struct
import sys
import time
import zlib
from typing import Dict, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "python"))
sys.path.insert(0, ROOT_DIR)

from crypto_module import RokCrypto  # noqa: E402
from rokbot.protobuf import (  # noqa: E402
    decode_message,
    encode_field_bytes,
    encode_field_varint,
    encode_message,
)
from rokbot.protocol import FrameParser, derive_seeds  # noqa: E402

FLEET_FILE = os.path.join(ROOT_DIR, "accounts_fleet.json")
DEFAULT_UID = "F682A5114F7DD6AD7995F8ED2D6719BA"
DEFAULT_IP = "194.176.99.80"

# March-chain confirm opcodes observed in live decoded logs (see decoder.py + smart_gather_search).
CONFIRM_OPS = {903, 365, 1013, 1014, 1005, 1023, 1024}

RESOURCE_TYPE_MAP = {
    1: ("food", "Cropland"),
    2: ("wood", "Logging Camp"),
    3: ("stone", "Stone Deposit"),
    4: ("gold", "Gold Mine"),
}

# Minimal legal fallback march (50x T1 siege) when no real inventory snapshot
# is available and --army is not given. Template IDs are game-global small
# ints (4 = T1 siege); the old [(1020,1),(500,3)] only worked through an
# inverted builder and is invalid under correct {1:template, 2:count}.
PLACEHOLDER_ARMY = [(4, 50)]


class _FT:
    """Minimal font styling for CLI output."""

    DIM = "\033[2m"
    YEL = "\033[33m"
    RED = "\033[31m"
    GRN = "\033[32m"
    BLD = "\033[1m"
    END = "\033[0m"

    @staticmethod
    def use() -> bool:
        return sys.stdout.isatty() and os.environ.get("NO_COLOR") != "1"


def _dim(s): return f"{_FT.DIM}{s}{_FT.END}" if _FT.use() else s
def _y(s):  return f"{_FT.YEL}{s}{_FT.END}" if _FT.use() else s
def _r(s):  return f"{_FT.RED}{s}{_FT.END}" if _FT.use() else s
def _g(s):  return f"{_FT.GRN}{s}{_FT.END}" if _FT.use() else s
def _b(s):  return f"{_FT.BLD}{s}{_FT.END}" if _FT.use() else s


def load_characters() -> list:
    """Load enabled characters (account-level token/uid merged per character)."""
    if not os.path.exists(FLEET_FILE):
        print(_r(f"[!] Fleet file not found: {FLEET_FILE}"))
        return []
    with open(FLEET_FILE, "r", encoding="utf-8") as f:
        fleet_raw = json.load(f)
    items = [fleet_raw] if isinstance(fleet_raw, dict) else fleet_raw
    out = []
    for item in items:
        chars = item.get("characters", []) if isinstance(item, dict) else []
        acc_fields = {}
        for k in ("access_token", "app_uid", "server_id", "server_id_int", "gate_host", "port", "device_udid"):
            if isinstance(item, dict) and item.get(k) is not None:
                acc_fields[k] = item.get(k)
        for ch in chars:
            if not ch.get("enabled", True):
                continue
            merged = dict(ch)
            for k, v in acc_fields.items():
                merged.setdefault(k, v)
            merged["account_id"] = item.get("account_email") or item.get("account_id") or "acc"
            merged["server_id_int"] = int(merged.get("server_id_int") or 2104267)
            merged["port"] = int(merged.get("port") or 3101)
            merged["gate_host"] = merged.get("gate_host") or "43.159.113.101"
            merged["device_udid"] = merged.get("device_udid") or DEFAULT_UID
            out.append(merged)
    return out


def build_dynamic_login_payload(
    app_uid: str,
    access_token: str,
    role_id: int,
    device_id: str = DEFAULT_UID,
    server_id_int: int = 2104267,
    public_ip: str = "",
) -> bytes:
    """
    Role-bound Android login (Opcode 14). Byte/value-identical to
    fleet_manager.build_dynamic_login_payload: auth.f6 = role_id, no f14
    (f14 was removed 2026-09-13 because it broke role binding).
    """
    pip = (public_ip or "").strip() or DEFAULT_IP
    auth_payload = {
        1: str(app_uid).encode("utf-8"),
        2: str(access_token).encode("utf-8"),
        3: int(server_id_int),
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
        24: b"Qualcomm Technologies, Inc MSM8998",
    }
    inner = {
        1: 1,
        4: str(device_id).encode("utf-8"),
        6: encode_message(device_profile),
        7: encode_message(auth_payload),
        9: 1,
        11: b"1.1.11.25",
        12: b"628788",
        13: pip.encode("utf-8"),
        15: b"7",
        20: b"e5494c1f6aad311adc9b64f1288e9b8d",
        21: 18446744073709551615,
        23: b"rocgate.lilithgame.com:3101",
        24: 2,
        27: b"\x12\x00\n\x03and\"\x00\x1a\x00",
    }
    return encode_message({1: 14, 2: encode_message(inner)})


def frame(opcode: int, payload: bytes) -> bytes:
    return encode_message({1: opcode, 2: payload})


def encode_point(x: float, y: float) -> bytes:
    """Wire point blob: tag 0x15 (f2=fixed32 X) then tag 0x0d (f1=fixed32 Y)."""
    return b"\x15" + struct.pack("<f", float(x)) + b"\x0d" + struct.pack("<f", float(y))


def build_map_request(center_pos: Tuple[float, float]) -> bytes:
    f1 = encode_point(center_pos[0], center_pos[1])
    return frame(1004, encode_message({1: f1, 2: 0, 5: 1}))


def build_inspect(node_id: int, node_pos: Tuple[float, float], city_pos: Tuple[float, float], alliance_id: int) -> bytes:
    """Opcode 1050 auto-gather click — byte layout matches live capture
    (f3 city pos, f5=0, f2 node_id, f4 node pos, f1 alliance id)."""
    body = (
        encode_field_bytes(3, encode_point(city_pos[0], city_pos[1]))
        + encode_field_varint(5, 0)
        + encode_field_varint(2, node_id)
        + encode_field_bytes(4, encode_point(node_pos[0], node_pos[1]))
        + encode_field_varint(1, alliance_id)
    )
    return frame(1050, body)


def build_send_troop_confirm() -> bytes:
    """Opcode 8: zlib-compressed SendTroopConfirm event (official chain)."""
    js = json.dumps({"E": "SendTroopConfirm", "t": str(int(time.time()))}).encode("utf-8")
    comp = zlib.compress(js)
    return encode_field_varint(1, 8) + encode_field_bytes(2, encode_field_bytes(1, comp))


def build_dispatch(node_id: int, army_list: list, commander_id: int, sec_commander: int = 0) -> bytes:
    """Opcode 1012 march dispatch. Army entry = {1: unit_template, 2: count}.
    Proven by the verified headless accept (troops=[(4,35000)] -> wire
    {1:4, 2:35000}, server echoed march in 1024) and consistent with the live
    client bytes `10de9501 08 04` = {1:4, 2:19166} (T1 siege x19166).
    Commander slots repeat field 1: {1:primary, 3:0, 2:1} + {1:deputy, 3:0, 2:2}
    (live + all 5 confirmed task-47 marches use pairs; single also confirmed once).
    NOTE: protobuf wire order is irrelevant; only tag->value matters."""
    f4 = encode_field_varint(4, node_id)
    f3 = encode_field_bytes(3, bytes.fromhex("15000000000d00000000"))
    f2_payload = bytearray()
    for ut, cnt in army_list:
        if cnt <= 0:
            continue
        it = encode_field_varint(1, ut) + encode_field_varint(2, cnt)
        f2_payload.extend(encode_field_bytes(2, it))
    f14 = encode_field_varint(14, 1)
    c1 = (
        encode_field_varint(1, commander_id)
        + encode_field_varint(3, 0)
        + encode_field_varint(2, 1)
    )
    f1_payload = encode_field_bytes(1, c1)
    if sec_commander:
        c2 = (
            encode_field_varint(1, sec_commander)
            + encode_field_varint(3, 0)
            + encode_field_varint(2, 2)
        )
        f1_payload += encode_field_bytes(1, c2)
    body = (
        f4 + f3 + bytes(f2_payload) + f14 + f1_payload
        + encode_field_varint(7, 0)
        + encode_field_varint(6, 0)
        + encode_field_varint(11, 0)
        + encode_field_varint(18, 0)
        + encode_field_bytes(5, b"dispatch_troop_1")
    )
    return frame(1012, body)


def build_init_burst(role_id: int, kingdom_id: int) -> List[bytes]:
    """
    Official session-init burst: the 51 C2S ops a live client emits between
    login and the first 1050 (decoded_20260913_163316.txt, byte-exact inners).
    Task-47 proved this burst precedes 1002/1035/162 on AmmAr; sessions without
    it stay sparse (1003/1005 only) and their 1012s die with err 133.
    Static inners replay verbatim; role/kingdom-templated ones rebuild.
    Skipped: 52 (stale token JSON), 2 (truncated), 7920 (odd bytes),
    170 (truncated), 532 ('close task' semantics), 1283 (chat), 1004s (own viewports).
    Each entry is a complete plaintext message {1:op, 2:inner}.
    """
    role = int(role_id)
    kid = int(kingdom_id)
    role_tag = encode_field_varint(1, 222169514)  # live session's role prefix
    new_tag = encode_field_varint(1, role)

    def tele(inner_hex: str) -> bytes:
        raw = bytes.fromhex(inner_hex)
        if raw.startswith(role_tag):
            raw = new_tag + raw[len(role_tag):]
        return raw

    burst: List[bytes] = []

    def cmd(op: int, inner: bytes):
        burst.append(frame(op, inner))

    def raw_op(op: int, inner_hex: str):
        burst.append(frame(op, bytes.fromhex(inner_hex)))

    # Live order (# = position in capture)
    raw_op(600, "0808")                                            # 1
    raw_op(2039, "0801")                                           # 2
    burst.append(frame(8035, tele("08aa93f86912094654455f5354415445")))   # 3 FEUSTATE
    raw_op(3350, "0802")                                           # 5
    cmd(6404, encode_message({1: kid}))                            # 6
    cmd(1202, encode_message({1: role}))                           # 7
    burst.append(frame(8035, tele("08aa93f869121753756247616d654465657248756e746572537465705632")))  # 8
    burst.append(frame(161, bytes.fromhex(                   # 9 attestation (verbatim)
        "12204636383241353131344637444436414437393935463845443244363731394241"
        "2207616e64726f69640a3918cbb780011220412d46344a30414752486955305956445169"
        "4d396477796178716b5345462d5028010a093235323736373538372203616e64")))  # noqa: E501
    raw_op(5501, "0801")                                           # 11
    burst.append(frame(8035, tele("08aa93f86912114369747946616b65543645766f6c766564")))  # 12 CityFollowed
    cmd(1202, encode_message({1: role}))                           # 13
    cmd(203, encode_message({1: role}))                            # 14 role switch
    burst.append(frame(8050, tele("08aa93f869121243697479456469744c61796f757444617461")))  # 15
    burst.append(frame(8333, bytes.fromhex("080108020803080408050806")))  # 16 caps
    burst.append(frame(9820, bytes.fromhex("0a0c54726f6f7050726f66696c65")))  # 17 TroopProfile
    cmd(110, encode_message({1: role, 2: kid, 3: role}))           # 18
    burst.append(frame(8035, tele("08aa93f86912134865726f53797374656d5f4d61726b4865726f")))  # 19
    burst.append(frame(9750, bytes.fromhex("0a023931")))           # 20 "91"
    burst.append(frame(9820, bytes.fromhex("0a1150726f66696c6547726f757044656c5462")))  # 21
    raw_op(4457, "0805")                                           # 22
    burst.append(frame(8035, bytes.fromhex("08001213676d745f6865726f5f75736167655f72617465")))  # 23
    burst.append(frame(8035, tele("08aa93f8691214547269676765725475746f7269616c5374617465")))  # 25
    burst.append(frame(8035, tele("08aa93f8691223595935426174746c6535763541726368697665325f333035375f323232313639353134")))  # 26
    burst.append(frame(8035, tele("08aa93f8691223595935426174746c6535763541726368697665325f333035375f323232313639353134")))  # 27
    raw_op(3370, "0801")                                           # 28
    cmd(1726, encode_message({1: kid}))                            # 29
    cmd(1202, encode_message({1: role}))                           # 32
    burst.append(frame(8037, tele("08aa93f8691212537570706f727473496e7374616e63696e671a0474727565")))  # 33
    burst.append(frame(8050, tele("08aa93f869121b51756575654d676d745f46696c74657253657474696e67735f7631")))  # 35
    cmd(6404, encode_message({1: kid}))                            # 37
    cmd(110, encode_message({1: role, 2: kid, 3: role}))           # 39
    raw_op(2104, "0801")                                           # 40
    raw_op(2101, "0801")                                           # 41
    burst.append(frame(8035, tele("08aa93f86912136973456e746572466972737449415050616765")))  # 42
    cmd(6404, encode_message({1: kid}))                            # 43
    cmd(1202, encode_message({1: role}))                           # 44
    cmd(110, encode_message({1: role, 2: kid, 3: role}))           # 45
    burst.append(frame(9402, encode_message({1: kid, 2: role})))   # 48 (inner {1:kid,2:role})
    burst.append(frame(123, bytes.fromhex(                   # 49 building query list
        "0a0237390a0236340a0238320a0235390a0238310a0237310a0237320a023833"
        "0a0237370a0236320a0238370a0238360a0236380a0239300a0238380a023734")))
    return burst


def unpack_double_field(data) -> Optional[float]:
    """Decode a double field that may arrive as uint64 bits (int), raw bytes,
    or float. Returns None when absent (vs 0.0 = truly depleted).
    Proven: live 1003 f4/f5 arrive as ints, e.g. 4696364700282126336 = 945000.0."""
    if data is None:
        return None
    try:
        if isinstance(data, bool):
            return None
        if isinstance(data, int):
            return struct.unpack("<d", struct.pack("<Q", data & 0xFFFFFFFFFFFFFFFF))[0]
        if isinstance(data, float):
            return data
        if isinstance(data, (bytes, bytearray)) and len(data) >= 8:
            return struct.unpack("<d", bytes(data[:8]))[0]
    except Exception:
        pass
    return None


def std_capacity(type_id: int, level: int) -> float:
    table = {
        1: {1: 105000, 2: 315000, 3: 472500, 4: 630000, 5: 945000, 6: 1350000},
        2: {1: 105000, 2: 315000, 3: 472500, 4: 630000, 5: 945000, 6: 1350000},
        3: {1: 78750, 2: 236250, 3: 354375, 4: 506250, 5: 750000, 6: 1012500},
        4: {1: 52500, 2: 105000, 3: 157500, 4: 225000, 5: 500000, 6: 450000},
    }
    return float(table.get(type_id, {}).get(level, 472500.0))


class GatherClient:
    """Raw async TCP session with per-frame crypto, mirroring the proven engine."""

    def __init__(self, char: dict):
        self.char = char
        self.role_id = int(char.get("role_id", 0))
        self.kingdom_id = int(char.get("kingdom_id") or 0)
        self.gate_host = str(char.get("gate_host", "43.159.113.101"))
        self.gate_port = int(char.get("port", 3101))
        cp = char.get("city_pos") or [0, 0]
        self.city_pos = (float(cp[0]), float(cp[1])) if isinstance(cp, list) else cp
        self.alliance_id = int(char.get("alliance_id") or 8719112)
        self.inspect_key = 0  # live 1050.f1 from Op 1035 tag 12 when seen
        self.commanders: List[int] = list(char.get("commanders") or [])
        self.public_ip = str(char.get("public_ip") or "")

        self.reader = None
        self.writer = None
        self.crypto_tx: Optional[RokCrypto] = None
        self.crypto_rx: Optional[RokCrypto] = None

        self.troops_in_city: Dict[int, int] = {}
        self.busy_commanders = set()
        self.discovered_nodes: List[dict] = []

    # -------------------------------------------------------------
    # IO helpers
    # -------------------------------------------------------------

    def _send_frame(self, payload: bytes):
        self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(payload)))

    async def _read_packet(self, timeout: float) -> Optional[bytes]:
        try:
            rh = await asyncio.wait_for(self.reader.readexactly(2), timeout=timeout)
            rl = (rh[0] << 8) | rh[1]
            raw_pkt = await asyncio.wait_for(self.reader.readexactly(rl), timeout=timeout)
            dec = self.crypto_rx.decrypt(raw_pkt)
            return dec
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            return None
        except Exception:
            return None

    @staticmethod
    def _decode_frames(dec: bytes) -> List[dict]:
        z_idx = dec.find(b"\x78\x9c")
        if z_idx == -1:
            z_idx = dec.find(b"\x78\x01")
        data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
        msg = decode_message(data)
        chunks = msg.get(1) if isinstance(msg.get(1), list) else [msg]
        frames = []
        for c in chunks:
            frames.append(decode_message(c) if isinstance(c, bytes) else c)
        return frames

    async def _drain_frames(self, seconds: float) -> List[dict]:
        """Read frames for a time window, returning raw op-level dicts."""
        seen = []
        deadline = asyncio.get_event_loop().time() + seconds
        while asyncio.get_event_loop().time() < deadline:
            dec = await self._read_packet(0.3)
            if dec is None:
                continue
            for m in self._decode_frames(dec):
                seen.append(m)
        return seen

    # -------------------------------------------------------------
    # Handshake + login
    # -------------------------------------------------------------

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.gate_host, self.gate_port)

    async def handshake(self) -> bool:
        try:
            hdr = await self.reader.readexactly(2)
            g_len = (hdr[0] << 8) | hdr[1]
            g_payload = await self.reader.readexactly(g_len)
            g_fields = decode_message(g_payload)
            sub = decode_message(g_fields.get(2, b""))
            seed_tx, seed_rx = derive_seeds(sub.get(1, 0), sub.get(2, 0))
            self.crypto_tx = RokCrypto(seed_tx)
            self.crypto_rx = RokCrypto(seed_rx)
            print(f"[SUCCESS] Handshake: TX=0x{seed_tx:08x} RX=0x{seed_rx:08x}")
            return True
        except Exception as e:
            print(_r(f"[FAIL] Handshake: {e}"))
            return False

    async def login(self) -> bool:
        token = str(self.char.get("access_token") or "")
        app_uid = str(self.char.get("app_uid") or "")
        if not token or not app_uid or not self.role_id:
            print(_r(f"[FAIL] Missing token/uid/role for {self.char.get('id','?')}"))
            return False
        payload = build_dynamic_login_payload(
            app_uid=app_uid,
            access_token=token,
            role_id=self.role_id,
            device_id=str(self.char.get("device_udid") or DEFAULT_UID),
            server_id_int=int(self.char.get("server_id_int") or 2104267),
            public_ip=self.public_ip,
        )
        self._send_frame(payload)
        await self.writer.drain()
        print(_dim(f"[LOGIN] Opcode 14 sent for Role {self.role_id} (KD {self.kingdom_id})."))
        # Official session-init burst (live order, byte-exact inners).
        # Live client paces init ops ~0.1-1.5s apart; a tight blast risks
        # server-side drops (9820/161 gate the 1002/162 snapshots).
        import random
        burst = build_init_burst(self.role_id, self.kingdom_id)
        for pkt in burst:
            self._send_frame(pkt)
            await self.writer.drain()
            await asyncio.sleep(0.15 + random.random() * 0.25)
        # Union with the previously proven queries (104/107/1001 still useful).
        self._send_frame(frame(104, b""))
        self._send_frame(frame(107, b""))
        self._send_frame(frame(1001, b""))
        await self.writer.drain()
        print(_dim(f"[LOGIN] init burst sent ({len(burst)} ops) + 104/107/1001."))
        return True

    async def role_verify(self) -> bool:
        """Read initial role; switch via 203/110 if the gateway loaded another role."""
        self._early_nodes: set = set()
        seen_role = None
        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline:
            dec = await self._read_packet(0.3)
            if dec is None:
                continue
            for m in self._decode_frames(dec):
                # Ingest everything early (troops/marches/nodes), like the
                # proven engine's _ingest_early — 1002 often lands here.
                try:
                    self._ingest(m, self._early_nodes)
                except Exception:
                    pass
                if m.get(1) == 15:
                    try:
                        p = decode_message(m.get(2, b""))
                        rid = p.get(1)
                        nm = bytes(p.get(5, b"")).decode("utf-8", errors="replace")
                        if rid:
                            seen_role = int(rid)
                            print(f"[ROLE] Gateway loaded {nm} (Role {rid}) KD {p.get(2)} Power {p.get(6)}")
                    except Exception:
                        pass
        if seen_role and seen_role != self.role_id:
            print(_y(f"[ROLE] Loaded {seen_role} != target {self.role_id} — switching (203/104/110/107)..."))
            self._send_frame(frame(203, encode_message({1: self.role_id})))
            self._send_frame(frame(104, b""))
            self._send_frame(frame(110, encode_message({1: self.role_id, 2: self.kingdom_id, 3: self.role_id})))
            self._send_frame(frame(107, b""))
            await self.writer.drain()
            deadline2 = asyncio.get_event_loop().time() + 2.5
            seen_role = None
            while asyncio.get_event_loop().time() < deadline2:
                dec = await self._read_packet(0.3)
                if dec is None:
                    continue
                for m in self._decode_frames(dec):
                    try:
                        self._ingest(m, self._early_nodes)
                    except Exception:
                        pass
                    if m.get(1) == 15:
                        try:
                            p = decode_message(m.get(2, b""))
                            if p.get(1):
                                seen_role = int(p.get(1))
                        except Exception:
                            pass
        if seen_role and str(seen_role) != str(self.role_id):
            print(_r(f"[HARD ABORT] Gateway on Role {seen_role}, target {self.role_id}. Refusing blind dispatch."))
            return False
        self.troops_in_city.clear()
        self._send_frame(frame(1001, b""))
        self._send_frame(bytes.fromhex("08fe4b1200"))  # 9726 march-list refresh
        await self.writer.drain()
        print(f"[ROLE] Session bound to target Role {self.role_id}.")
        return True

    # -------------------------------------------------------------
    # Sync: viewports, troops, marches, nodes
    # -------------------------------------------------------------

    async def sync_world(self) -> None:
        cx, cy = self.city_pos[0], self.city_pos[1]
        viewports = [
            (cx, cy),
            (cx + 30.0, cy), (cx - 30.0, cy),
            (cx, cy + 30.0), (cx, cy - 30.0),
            (cx + 45.0, cy + 45.0), (cx - 45.0, cy - 45.0),
            (cx + 60.0, cy), (cx - 60.0, cy),
            (cx, cy + 60.0), (cx, cy - 60.0),
            (cx + 90.0, cy), (cx - 90.0, cy),
            (cx, cy + 90.0), (cx, cy - 90.0),
            (cx + 120.0, cy + 120.0), (cx - 120.0, cy - 120.0),
            (cx + 180.0, cy), (cx - 180.0, cy),
        ]
        for vp in viewports:
            self._send_frame(build_map_request(vp))
        await self.writer.drain()

        seen_node_ids = {n["node_id"] for n in self.discovered_nodes}
        census: Dict[int, int] = {}
        deadline = asyncio.get_event_loop().time() + 15.0
        while asyncio.get_event_loop().time() < deadline:
            dec = await self._read_packet(0.3)
            if dec is None:
                continue
            frames = self._decode_frames(dec)
            for m in frames:
                op = m.get(1)
                if isinstance(op, int):
                    census[op] = census.get(op, 0) + 1
                self._ingest(m, seen_node_ids)

        print(f"[MAP] Sync window closed: {len(self.discovered_nodes)} node(s) seen.")
        print(_dim(f"[MAP] full census: {dict(sorted(census.items()))}"))

        if not self.troops_in_city:
            print(_y("[MAP] No Op1002 inventory — re-requesting profile/map sync once..."))
            self._send_frame(frame(107, b""))
            self._send_frame(frame(1001, b""))
            await self.writer.drain()
            deadline2 = asyncio.get_event_loop().time() + 4.0
            while asyncio.get_event_loop().time() < deadline2:
                dec = await self._read_packet(0.3)
                if dec is None:
                    continue
                frames = self._decode_frames(dec)
                for m in frames:
                    op = m.get(1)
                    if isinstance(op, int):
                        census[op] = census.get(op, 0) + 1
                    self._ingest(m, seen_node_ids)
            retry_keys = {k: census.get(k, 0) for k in (1002, 125, 1005)}
            print(_dim(f"[MAP] retry census keys: {retry_keys}"))

        total_troops = sum(self.troops_in_city.values())
        print(f"[MAP] City troops snapshot: {total_troops} units across {len(self.troops_in_city)} templates: "
              f"{dict(sorted(self.troops_in_city.items(), key=lambda kv: -kv[1])[:6])}")
        if self.busy_commanders:
            print(f"[MAP] Busy commanders (active marches): {sorted(self.busy_commanders)}")

    def _ingest(self, m: dict, seen_node_ids: set):
        op = m.get(1)
        p2 = m.get(2, b"")
        if op == 1035 and isinstance(p2, bytes):
            # 1050.f1 inspect key lives in 1035 tag 12 (task-47 session truth).
            try:
                tag12 = decode_message(p2).get(12)
                if isinstance(tag12, int) and tag12 > 0:
                    if not getattr(self, "inspect_key", 0):
                        self.inspect_key = tag12
                        print(f"   [SYNC 1035] live inspect-key f1={tag12}")
            except Exception:
                pass
        if op == 1002 and isinstance(p2, bytes):
            sub = decode_message(p2)
            t19 = sub.get(19)
            if isinstance(t19, bytes):
                inner = decode_message(t19)
                for item_b in inner.get(1, []):
                    if isinstance(item_b, bytes):
                        it = decode_message(item_b)
                        uid = it.get(1)
                        cnt = it.get(3) or it.get(2) or 0
                        if uid and cnt > 0:
                            self.troops_in_city[uid] = self.troops_in_city.get(uid, 0) + cnt
        elif op == 125 and isinstance(p2, bytes) and not self.troops_in_city:
            p = decode_message(p2)
            items = p.get(1, [])
            if not isinstance(items, list):
                items = [items]
            for it in items:
                if isinstance(it, bytes):
                    sub_it = decode_message(it)
                    sub2_raw = sub_it.get(2)
                    if isinstance(sub2_raw, bytes):
                        sub2 = decode_message(sub2_raw)
                        ut = sub2.get(1, 0)
                        cnt = sub2.get(2, 0)
                        if ut > 0 and cnt > 0:
                            self.troops_in_city[ut] = cnt
        elif op in (1005, 1023) and isinstance(p2, bytes):
            pm = decode_message(p2)
            blobs = []
            f1 = pm.get(1)
            if isinstance(f1, bytes):
                blobs.append(f1)
            for v in pm.values():
                if isinstance(v, bytes):
                    blobs.append(v)
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, bytes):
                            blobs.append(x)
            pat = str(self.role_id).encode() + rb"_(\d+)_(\d+)(?:_(\d+))?"
            now = time.time()
            for blob in blobs:
                for mt in __import__("re").finditer(pat, blob):
                    try:
                        ts = int(mt.group(1).decode())
                    except Exception:
                        continue
                    if ts > now + 600 or now - ts > 8 * 3600:
                        continue
                    pri = int(mt.group(2).decode())
                    self.busy_commanders.add(pri)
                    if mt.group(3):
                        try:
                            self.busy_commanders.add(int(mt.group(3).decode()))
                        except Exception:
                            pass
        elif op == 1003 and isinstance(p2, bytes):
            pmsg = decode_message(p2)
            for item_bytes in pmsg.get(5, []):
                if not isinstance(item_bytes, bytes):
                    continue
                obj = decode_message(item_bytes)
                f1_b = obj.get(1, b"")
                f1 = decode_message(f1_b) if isinstance(f1_b, bytes) else {}
                node_id = f1.get(1)
                if not node_id or node_id in seen_node_ids:
                    continue
                pos_b = f1.get(3)
                px = py = 0.0
                if pos_b and len(pos_b) >= 10:
                    v1 = struct.unpack("<f", pos_b[1:5])[0]
                    v2 = struct.unpack("<f", pos_b[6:10])[0]
                    if pos_b[0] == 0x0d:
                        py, px = v1, v2
                    else:
                        px, py = v1, v2
                type_id = obj.get(2, 1)
                level = obj.get(3, 1)
                occupier = obj.get(7, 0)
                march_st = obj.get(8, 0)
                free = (not occupier or occupier == 0 or occupier == b"") and (not march_st or march_st == 0)
                dist = round(math.hypot(px - self.city_pos[0], py - self.city_pos[1]) / 6.0, 1)
                key, disp = RESOURCE_TYPE_MAP.get(type_id, ("food", "Resource Field"))
                rem = unpack_double_field(obj.get(5))
                if rem is None:
                    rem = unpack_double_field(obj.get(4))
                seen_node_ids.add(node_id)
                self.discovered_nodes.append({
                    "node_id": node_id,
                    "pos": (round(px, 2), round(py, 2)),
                    "dist": dist,
                    "type": key,
                    "type_id": type_id,
                    "level": level,
                    "free": free,
                    "remaining": rem,  # None = unknown (assume full, 1051 gate validates)
                })

    # -------------------------------------------------------------
    # March dispatch
    # -------------------------------------------------------------

    # Gatherer-first preference (verified live: Joan 15 / Gaius 34 / Sarka 38
    # / Constance 33 / Cleopatra 32 notch real accepts; City Keeper 1 is a
    # fallback that correlated with silent drops).
    GATHERER_ORDER = [15, 34, 38, 33, 32, 43, 46, 24, 36, 35, 10, 7, 14]

    def _pick_commander(self) -> int:
        idle = [c for c in self.commanders if c not in self.busy_commanders]
        pool = idle or self.commanders
        for g in self.GATHERER_ORDER:
            if g in pool:
                return g
        return pool[0] if pool else 15

    def _build_army(self, node_reserves: float, max_count: int = 200) -> list:
        """Compose a march from real inventory when known, else fallback."""
        if not self.troops_in_city:
            return PLACEHOLDER_ARMY
        templates = sorted(self.troops_in_city.items(), key=lambda kv: -kv[1])
        army = []
        remaining = max_count
        for ut, cnt in templates:
            if remaining <= 0:
                break
            use = min(cnt, remaining)
            army.append((ut, use))
            remaining -= use
        return army if army else PLACEHOLDER_ARMY

    async def inspect_node(self, node: dict) -> bool:
        """Center viewport + 1050 inspect; True when the 1051 ack arrives
        (verified pattern: no 1051 -> dispatch never confirms)."""
        print(f"\n[INSPECT] Node #{node['node_id']} ({node['type']} Lvl {node['level']}) "
              f"at {node['pos']} | {node['dist']}km free={node['free']}")
        self._send_frame(build_map_request(node["pos"]))
        await self.writer.drain()
        await asyncio.sleep(0.05)

        f1 = self.inspect_key or self.alliance_id
        self._send_frame(build_inspect(node["node_id"], node["pos"], city_pos=self.city_pos, alliance_id=f1))
        await self.writer.drain()

        got_1051 = False
        start = time.time()
        while time.time() - start < 2.0:
            dec = await self._read_packet(0.3)
            if dec is None:
                continue
            for m in self._decode_frames(dec):
                if m.get(1) == 1051:
                    got_1051 = True
                    r2 = m.get(2, b"")
                    if isinstance(r2, bytes):
                        print(_dim(f"   [WIRE] 1051 ack ({len(r2)}B): {r2[:48].hex()}"))
                    break
                try:
                    self._ingest(m, self._early_nodes)
                except Exception:
                    pass
            if got_1051:
                break
        print(f"   [WIRE] inspect-1050 ACK 1051: {'received' if got_1051 else _y('MISSING (node likely invalid/occupied)')}")
        return got_1051

    async def dispatch_to(self, node: dict, commander_id: int, army: list, sec_commander: int = 0) -> dict:
        self._sec_commander = sec_commander
        pair = f" + deputy {sec_commander}" if sec_commander else " (solo)"
        print(f"\n[DISPATCH] -> {node['name'] if node.get('name') else 'Node'} #{node['node_id']} "
              f"({node['type']} Lvl {node['level']}) at {node['pos']} | {node['dist']}km")
        print(f"   Commander: {commander_id}{pair} | Units: {sum(c for _, c in army)} | Army: {army}")

        self._send_frame(build_map_request(node["pos"]))
        self._send_frame(bytes.fromhex("08fe4b1200"))  # 9726
        self._send_frame(build_send_troop_confirm())   # Op8
        self._send_frame(build_dispatch(node["node_id"], army, commander_id,
                                         sec_commander=self._sec_commander))
        await self.writer.drain()

        seen_ops: List[int] = []
        result = {"op1": None, "op1_code": None, "confirmed": False, "seen": []}
        start_wait = time.time()
        while time.time() - start_wait < 3.5:
            dec = await self._read_packet(0.6)
            if dec is None:
                continue
            for m in self._decode_frames(dec):
                op = m.get(1)
                if op is None:
                    continue
                r2 = m.get(2, b"")
                if op not in seen_ops:
                    seen_ops.append(op)
                    if isinstance(r2, bytes) and len(r2):
                        print(_dim(f"   [WIRE] opcode {op} ({len(r2)}B): {r2[:96].hex()}"))
                if op == 1:
                    sub = decode_message(r2) if isinstance(r2, bytes) else {}
                    try:
                        fop = int(sub.get(1, -1))
                    except (TypeError, ValueError):
                        fop = -1
                    try:
                        fcode = int(sub.get(2, -1))
                    except (TypeError, ValueError):
                        fcode = -1
                    raw_hex = r2[:32].hex() if isinstance(r2, bytes) else ""
                    print(f"   [ACK] op1 ack op={fop} code={fcode} raw={raw_hex}")
                    if fop == 1012:
                        result["op1"] = fop
                        result["op1_code"] = fcode
                        if fcode == 1:
                            self.busy_commanders.add(commander_id)
                if op in CONFIRM_OPS:
                    result["confirmed"] = True
            if result["confirmed"]:
                break
        result["seen"] = seen_ops
        print(f"   [WIRE] confirm-window ops: {','.join(map(str, seen_ops)) or 'timeout'}")
        return result

    async def keepalive(self, seconds: float):
        """Heartbeat + watch: keeps reading so late confirms (1023/1024/1013)
        are caught and logged instead of missed after close."""
        ka = frame(9, b"")
        end = time.time() + seconds
        while time.time() < end:
            await asyncio.sleep(6)
            try:
                self._send_frame(ka)
                await self.writer.drain()
            except Exception:
                break
            dec = await self._read_packet(0.5)
            if dec is None:
                continue
            for m in self._decode_frames(dec):
                op = m.get(1)
                if op in CONFIRM_OPS or op == 1:
                    r2 = m.get(2, b"")
                    hx = r2[:64].hex() if isinstance(r2, bytes) else ""
                    print(_dim(f"   [HOLD] opcode {op}: {hx}"))

    async def close(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass


def fmt_army(arg: str) -> list:
    army = []
    for part in arg.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            ut, cnt = part.split(":", 1)
        else:
            ut, cnt = part, "1"
        army.append((int(ut), int(cnt)))
    return army


def print_header(char: dict):
    role_id = int(char.get("role_id", 0))
    print("=" * 68)
    print(_b(f"  DISPATCH MARCH — {char.get('name', role_id)} (Role {role_id})"))
    cp = char.get("city_pos") or [0, 0]
    print(f"  City: {tuple(cp)} | KD: {char.get('kingdom_id')} | Alliance: #{char.get('alliance_id', 'default')}")
    print(f"  Commanders: {char.get('commanders') or 'unknown'}")
    print("=" * 68)


def cmd_list(chars: list) -> int:
    print(f"[FLEET] {len(chars)} enabled characters:")
    for c in chars:
        role_id = int(c.get("role_id", 0))
        cp = c.get("city_pos") or [0, 0]
        flag = _g("ok") if c.get("access_token") and cp not in ([0, 0], (0, 0)) else _r("missing city/token")
        print(f"   {c.get('id','?'):>9}  {c.get('name','?'):<28} role={role_id:<10} city={tuple(cp)}  [{flag}]")
    return 0


def pick_target(chars: list, char_id: str) -> Optional[dict]:
    matches = [c for c in chars if str(c.get("id")) == char_id or str(c.get("name")) == char_id]
    if matches:
        return matches[0]
    return next((c for c in chars if c.get("enabled", True)), None)


def main():
    ap = argparse.ArgumentParser(description="Headless gather march dispatcher (RoK, TCP 3101).", add_help=True)
    ap.add_argument("--list", action="store_true", help="List enabled fleet characters and exit.")
    ap.add_argument("--char", default=None, help="Character id (char_01) or name ([QPSS]AmmAr). Defaults to first enabled.")
    ap.add_argument("--commander", type=int, default=0, help="Commander id override (default: first idle owned).")
    ap.add_argument("--commander2", type=int, default=0, help="Deputy commander id (slot 2). Verified sessions pair primary+deputy.")
    ap.add_argument("--army", default=None, help="Comma list of template:count, e.g. '19166:200,1020:50'.")
    ap.add_argument("--node", type=int, default=0, help="Explicit node_id to dispatch to.")
    ap.add_argument("--x", type=float, default=None, help="Node X (required with --node).")
    ap.add_argument("--y", type=float, default=None, help="Node Y (required with --node).")
    ap.add_argument("--target", default="food", choices=["food", "wood", "stone", "gold"])
    ap.add_argument("--alliance", type=int, default=0, help="Override alliance id (default: char value or 8719112).")
    ap.add_argument("--hold", type=int, default=0, help="Keep session alive and heartbeat N seconds after dispatch.")
    ap.add_argument("--timeout", type=int, default=90, help="Overall operation timeout in seconds.")
    args = ap.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    chars = load_characters()
    if args.list or not chars:
        return cmd_list(chars)

    char = pick_target(chars, args.char)
    if not char:
        print(_r("No enabled character found."))
        return 1
    print_header(char)

    role_id = int(char.get("role_id", 0))
    commander_id = int(args.commander or 0)
    if commander_id:
        print(f"  Commander pick: {commander_id} (override)")
    if args.alliance:
        char["alliance_id"] = args.alliance

    army = fmt_army(args.army) if args.army else None

    async def run():
        async with asyncio.timeout(args.timeout):
            client = GatherClient(char)
            try:
                await client.connect()
                print(f"[CONN] {client.gate_host}:{client.gate_port} established.")
                if not await client.handshake():
                    return 2
                if not await client.login():
                    return 2
                if not await client.role_verify():
                    return 2
                await client.sync_world()

                picked_commander = int(args.commander or 0) or client._pick_commander()
                if not args.commander:
                    print(f"  Commander pick: {picked_commander} (gatherer-first, busy-aware)")

                army_final = army
                if args.node:
                    if args.x is None or args.y is None:
                        print(_r("[FAIL] --node requires --x and --y."))
                        return 3
                    node = {
                        "node_id": args.node,
                        "pos": (args.x, args.y),
                        "dist": round(math.hypot(args.x - client.city_pos[0], args.y - client.city_pos[1]) / 6.0, 1),
                        "type": args.target,
                        "level": 1,
                        "free": True,
                        "name": RESOURCE_TYPE_MAP.get(args.target, ("food", "Node"))[1],
                        "remaining": 0.0,
                    }
                else:
                    MIN_RESERVES = 20000.0
                    pool = [n for n in client.discovered_nodes if n["free"] and n["type"] == args.target]
                    if not pool:
                        pool = [n for n in client.discovered_nodes if n["free"]]
                    # Drop provably-depleted nodes (parsed remaining ~0); keep
                    # unknown-remaining ones (1051 gate validates them live).
                    full = [n for n in pool if n.get("remaining") is None or n["remaining"] >= MIN_RESERVES]
                    dropped = len(pool) - len(full)
                    if dropped:
                        print(_dim(f"[NODES] skipped {dropped} depleted node(s) (parsed reserves < {int(MIN_RESERVES)})."))
                    candidates = full or pool
                    if not candidates:
                        print(_r(f"[FAIL] No free node found near city for target '{args.target}'."))
                        print(_y("     Try --node N --x X --y Y with known coordinates."))
                        return 3
                    # Prefer natural resource levels (<=6). Lvl 7+ entities
                    # never answered 1050/1051 in live runs (exotic/special?).
                    natural = [n for n in candidates if n["level"] <= 6]
                    if natural:
                        print(_dim(f"[NODES] preferring {len(natural)} natural-level (<=6) node(s)."))
                        candidates = natural
                    candidates.sort(key=lambda n: (-n["level"], n["dist"]))
                    print(f"[NODES] top candidates for '{args.target}':")
                    for n in candidates[:8]:
                        rem = n.get("remaining")
                        rem_s = f"{int(rem)}" if rem is not None else f"~{int(std_capacity(n.get('type_id', 1), n['level']))}?"
                        print(f"    #{n['node_id']} {n['type']} Lvl {n['level']} at {n['pos']} "
                              f"{n['dist']}km rem={rem_s}")
                    node = None
                    for cand in candidates[:3]:
                        if await client.inspect_node(cand):
                            node = cand
                            break
                        print(_y(f"    [SKIP] node #{cand['node_id']} failed inspect, trying next..."))
                    if node is None:
                        print(_r("[FAIL] No candidate passed the 1050/1051 inspect."))
                        return 3

                node_est = node.get("remaining")
                if node_est is None:
                    node_est = std_capacity(node.get("type_id", 1), node.get("level", 3))
                army_final = army_final or client._build_army(float(node_est))
                if army_final == PLACEHOLDER_ARMY:
                    print(_y("    [WARN] No real troop snapshot — using minimal placeholder (4:50)."))
                sec = int(args.commander2 or 0)
                if sec and sec in client.busy_commanders:
                    print(_y(f"    [WARN] Deputy {sec} looks busy; sending anyway per override."))
                result = await client.dispatch_to(node, picked_commander, army_final, sec_commander=sec)

                if result["confirmed"]:
                    print(_g("[SUCCESS] March CONFIRMED deployed."))
                elif result["op1_code"]:
                    if result["op1_code"] == 135:
                        print(_r("[REJECT] Commander not owned by this role (err 135). Use --commander with an owned id."))
                    elif result["op1_code"] == 155:
                        print(_r("[REJECT] Node unreachable / outside valid range (err 155)."))
                    else:
                        print(_r(f"[REJECT] Dispatch denied (err {result['op1_code']})."))
                else:
                    print(_y("[WARN] No explicit confirm within window; check opcodes above."))

                if args.hold > 0:
                    print(_dim(f"[HOLD] Heartbeating {args.hold}s..."))
                    await client.keepalive(args.hold)
                return 0 if result["confirmed"] else 4
            finally:
                await client.close()

    try:
        return asyncio.run(run())
    except TimeoutError:
        print(_r(f"[FAIL] Overall timeout ({args.timeout}s)."))
        return 5
    except KeyboardInterrupt:
        print("\n[!] Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())