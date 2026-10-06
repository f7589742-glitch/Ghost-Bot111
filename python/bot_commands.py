"""
bot_commands.py — Headless bot: login + execute verified commands.

Anti-ban session design:
- Single long-lived connection (5-7 min) matching real client behavior
- Heartbeat every ~3 seconds (like real client from pcap)
- Randomized delays between operations (human-like timing)
- Multiple operation types during session (not just gather)
- Graceful disconnect after session duration

Usage: python bot_commands.py --profile <name> --loop --cycles 0 --interval 15
"""

import asyncio
import os
import sys
import json
import time
import struct
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ROK_MARK_CONSUMED", "0")

from headless_client import RokProtocol, ProtobufCodec, Frame
from crypto_module import RokCrypto

# ------------------------------------------------------------------
# Packet builders (verified from game_capture.pcap)
# ------------------------------------------------------------------

def cmd_packet(op: int, payload: bytes) -> bytes:
    return ProtobufCodec.encode_message({1: op, 2: payload})

def train_packet(unit_template: str = "73", unit_type: int = 4, count: int = 1600) -> bytes:
    # VERIFIED 2026-08-10 from Frida capture:
    # real = {1:"73", 2:4(unit_type), 3:1600(count), 4:0, 5:0}
    # bot_commands previously sent {1, 2:count, 3:batch} -> fields swapped -> wrong cmd.
    payload = ProtobufCodec.encode_message({
        1: unit_template, 2: unit_type, 3: count, 4: 0, 5: 0,
    })
    return cmd_packet(300, payload)

def gather_packet(node_id: int, army: list, commander_id: int = 34, sec_commander: int = 0, march_name: str = "dispatch_troop_1") -> bytes:
    army_msgs = []
    for unit_int, count in army:
        # VERIFIED WIRE: tag 1 is unit_type, tag 2 is count
        army_msgs.append(ProtobufCodec.encode_field_varint(2, count) + ProtobufCodec.encode_field_varint(1, unit_int))
    f3 = fixed32_tag(2, 0) + fixed32_tag(1, 0)
    
    cmd_payload = bytearray()
    c1 = (ProtobufCodec.encode_field_varint(1, commander_id) +
          ProtobufCodec.encode_field_varint(3, 0) +
          ProtobufCodec.encode_field_varint(2, 1))
    cmd_payload.extend(ProtobufCodec.encode_field_bytes(1, c1))
    if sec_commander and sec_commander > 0:
        c2 = (ProtobufCodec.encode_field_varint(1, sec_commander) +
              ProtobufCodec.encode_field_varint(3, 0) +
              ProtobufCodec.encode_field_varint(2, 2))
        cmd_payload.extend(ProtobufCodec.encode_field_bytes(1, c2))

    payload = (
        ProtobufCodec.encode_field_varint(4, node_id)
        + ProtobufCodec.encode_field_bytes(3, f3)
        + b"".join(ProtobufCodec.encode_field_bytes(2, m) for m in army_msgs)
        + ProtobufCodec.encode_field_varint(14, 1)
        + bytes(cmd_payload)
        + ProtobufCodec.encode_field_varint(6, 0)
        + ProtobufCodec.encode_field_varint(11, 0)
        + ProtobufCodec.encode_field_varint(7, 0)
        + ProtobufCodec.encode_field_bytes(5, march_name.encode("utf-8"))
    )
    return cmd_packet(1012, payload)

def fixed32_tag(field_num: int, bits: int) -> bytes:
    return ProtobufCodec.encode_varint((field_num << 3) | 5) + struct.pack("<I", bits)

def auto_gather_packet(alliance_id: int, node_id: int, city: tuple, node: tuple) -> bytes:
    pos = lambda p: fixed32_tag(1, f32_key(p[0])) + fixed32_tag(2, f32_key(p[1]))
    payload = (
        ProtobufCodec.encode_field_varint(1, alliance_id)
        + ProtobufCodec.encode_field_varint(2, node_id)
        + ProtobufCodec.encode_field_bytes(3, pos(node))
        + ProtobufCodec.encode_field_bytes(4, pos(city))
        + ProtobufCodec.encode_field_varint(5, 0)
    )
    return cmd_packet(1050, payload)

def discover_packet(res_type: int = 1) -> bytes:
    # VERIFIED WIRE: real in-game search sends {1: 2, 2: res_type} (1=food, 2=wood, 3=stone, 4=gold)
    return cmd_packet(1176, ProtobufCodec.encode_message({1: 2, 2: res_type}))

def heartbeat_packet() -> bytes:
    # VERIFIED 2026-08-10: real client heartbeats are op=9 {1:9,2:""} (77x/session),
    # NOT op=925. Sending 925 every 3s is a bot fingerprint -> block.
    return cmd_packet(9, b"")

def keepalive_packet() -> bytes:
    # op=9 keepalive, matches real capture exactly: 08 09 12 00
    return cmd_packet(9, b"")

def f32_key(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]

def u32f(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits))[0]

# ------------------------------------------------------------------
# Response decoding
# ------------------------------------------------------------------

def decode_op(payload: bytes):
    try:
        pf = ProtobufCodec.decode_message(payload)
        return pf.get(1, 0), pf.get(2, b"")
    except Exception:
        return None, None

def brief(data: bytes, limit: int = 160) -> str:
    if isinstance(data, bytes):
        try:
            inner = ProtobufCodec.decode_message(data)
            parts = []
            for k, v in sorted(inner.items()):
                if isinstance(v, bytes):
                    try:
                        s = v.decode("utf-8")
                        if s and all(32 <= ord(c) < 127 for c in s):
                            parts.append("f%d=%r" % (k, s))
                            continue
                    except Exception:
                        pass
                    if len(v) <= 20:
                        parts.append("f%d=%s" % (k, v.hex()))
                    else:
                        parts.append("f%d=(%dB)" % (k, len(v)))
                else:
                    parts.append("f%d=%s" % (k, v))
            return "{" + ", ".join(parts) + "}"
        except Exception:
            return data.hex()[:80]
    return str(data)

def parse_batch_nodes(records: bytes) -> dict:
    import zlib
    nodes = {}
    try:
        rf = ProtobufCodec.decode_message(records)
        f1, f2 = rf.get(1), rf.get(2)
        markers = f1 if isinstance(f1, list) else [f1]
        payloads = f2 if isinstance(f2, list) else [f2]
        for marker, payload in zip(markers, payloads):
            if marker != 1177 or not isinstance(payload, bytes):
                continue
            pl = ProtobufCodec.decode_message(payload)
            ents = pl.get(1, [])
            if not isinstance(ents, list):
                ents = [ents]
            for e in ents:
                if not isinstance(e, bytes):
                    continue
                ef = ProtobufCodec.decode_message(e)
                nid, p = ef.get(2), ef.get(1)
                if isinstance(nid, int) and isinstance(p, bytes):
                    pv = ProtobufCodec.decode_message(p)
                    x, y = pv.get(1), pv.get(2)
                    if isinstance(x, int) and isinstance(y, int):
                        nodes[nid] = (u32f(x), u32f(y))
    except Exception:
        return {}
    return nodes

# ------------------------------------------------------------------
# Human-like timing helpers
# ------------------------------------------------------------------

def human_delay(base: float = 2.0, jitter: float = 1.5) -> float:
    return max(0.5, base + random.uniform(-jitter, jitter))

async def human_sleep(base: float = 2.0, jitter: float = 1.5):
    await asyncio.sleep(human_delay(base, jitter))

# ------------------------------------------------------------------
# Bot
# ------------------------------------------------------------------

class CommandBot:
    def __init__(self, profile: str):
        self.profile = profile
        self.proto: RokProtocol = None
        self.log: list = []
        self.nodes: dict = {}
        self.gather_result: str = None
        self.session_start: float = 0

    async def on_frame(self, frame: Frame):
        op, data = decode_op(frame.payload)
        if op is None:
            return
        ts = time.strftime("%H:%M:%S")
        if op == 8003:
            # VERIFIED: server keepalive-request -> reply op=9 {1:9,2:""} (exact real shape)
            await self.proto.send_data(cmd_packet(9, b""))
            return
        if op == 9999:
            try:
                import zlib
                zl = ProtobufCodec.decode_message(data).get(2)
                if isinstance(zl, bytes):
                    found = parse_batch_nodes(zlib.decompress(zl))
                    if found:
                        self.nodes.update(found)
                        print("[%s] nodes from 9999: %d (total %d)" % (ts, len(found), len(self.nodes)))
            except Exception:
                pass
        if op == 1:
            try:
                inner = ProtobufCodec.decode_message(data)
                if inner.get(1) == 1012 and inner.get(2) == 156:
                    self.gather_result = "busy"
                    print("[%s] GATHER BUSY (march slot occupied)" % ts)
            except Exception:
                pass
        if op == 903 or op == 365:
            self.gather_result = "ok"
        summary = brief(data)
        print("[%s] S op=%-6d %s" % (ts, op, summary))
        self.log.append((time.time(), op, frame.payload.hex()))

    async def _hb_loop(self, stop_event: asyncio.Event):
        while not stop_event.is_set():
            try:
                await self.proto.send_data(heartbeat_packet())
            except Exception:
                break
            await asyncio.sleep(human_delay(3.0, 0.8))

    async def run(self, do_train: bool, do_gather: bool, node_id: int, unit: str,
                  count: int, do_discover: bool, army: list = None,
                  auto_gather: bool = False, alliance: int = 0,
                  city: tuple = (0.0, 0.0), node_pos: tuple = (0.0, 0.0),
                  cycles: int = 1, interval_min: float = 15,
                  session_min: float = 5.0):
        self.army = army or [(1020, 1), (500, 3)]
        self.auto_gather = auto_gather
        self.alliance = alliance
        self.city = city or (7057.0, 5687.0)
        self.node_pos = node_pos
        self.node_target = node_id

        from core.session_manager import SessionManager
        mgr = SessionManager(self.profile)
        profile = mgr.load_profile()
        if not profile or not profile.is_valid:
            print("profile invalid: %s" % self.profile)
            return

        tokens = {
            "access_token": profile.access_token,
            "app_uid": profile.app_uid,
            "player_id": getattr(profile, "role_id", None) or profile.app_uid,
        }
        from headless_client import build_minimal_login
        login_payload = build_minimal_login(tokens)

        cycle = 0
        while True:
            cycle += 1
            if cycles and cycle > cycles:
                break
            self.gather_result = None
            self.nodes = {}
            self.log = []
            self.session_start = time.time()

            print("\n=== cycle %d/%s | session ~%dmin ===" % (
                cycle, cycles if cycles else "inf", int(session_min)))
            self.proto = RokProtocol(login_payload=login_payload, keepalive_interval=0)
            self.proto.register_handler(self.on_frame)

            print("connecting...")
            ok = await self.proto.connect()
            if not ok:
                print("connection failed, retry in 60s")
                await asyncio.sleep(60)
                continue
            print("connected, waiting for data stream...")
            await asyncio.sleep(human_delay(4.0, 1.0))

            stop_hb = asyncio.Event()
            hb_task = asyncio.create_task(self._hb_loop(stop_hb))
            print("heartbeat loop started")

            await human_sleep(2.0, 0.5)

            if do_discover:
                await self.proto.send_data(discover_packet())
                print("sent op=1176 discover")
                await human_sleep(3.0, 1.0)

            if do_train:
                await self.proto.send_data(train_packet(unit_template=unit, count=count))
                print("sent op=300 train: unit=%s count=%d" % (unit, count))
                await human_sleep(5.0, 2.0)

            nid = self.node_target
            npos = self.node_pos
            if self.nodes:
                if nid in self.nodes:
                    npos = npos or self.nodes[nid]
                else:
                    nid, npos = next(iter(self.nodes.items()))
                    print("target %d not in discovery, using %d" % (self.node_target, nid))
            if not npos:
                npos = (self.city[0] - 20.0, self.city[1] + 20.0)

            gathered = False
            if do_gather and nid:
                attempts = 0
                while attempts < 4:
                    attempts += 1
                    if self.auto_gather:
                        await self.proto.send_data(
                            auto_gather_packet(self.alliance, nid, self.city, npos))
                        print("sent op=1050 auto-gather node=%d" % nid)
                        await human_sleep(1.5, 0.5)
                    await self.proto.send_data(gather_packet(nid, self.army))
                    print("sent op=1012 gather: node=%d" % nid)
                    self.gather_result = None
                    for _ in range(8):
                        await asyncio.sleep(human_delay(3.0, 0.5))
                        if self.gather_result:
                            break
                    if self.gather_result == "ok":
                        print("GATHER OK node=%d" % nid)
                        gathered = True
                        break
                    if self.gather_result == "busy":
                        print("march busy, retry in %ds" % int(human_delay(120, 30)))
                        await asyncio.sleep(human_delay(120, 30))
                        continue
                    print("no gather confirmation")
                    break

            elapsed = time.time() - self.session_start
            remaining = max(0, session_min * 60 - elapsed)
            if remaining > 30:
                print("idle in session for %.0f more seconds (human-like)..." % remaining)
                await asyncio.sleep(remaining)

            stop_hb.set()
            try:
                await hb_task
            except Exception:
                pass

            await self.proto.disconnect()
            print("disconnected after %.0fs" % (time.time() - self.session_start))
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "bot_session_log.json"), "w") as f:
                json.dump(self.log, f, indent=1)
            print("session log saved")

            if cycles and cycle >= cycles:
                break
            wait = human_delay(interval_min * 60, interval_min * 30)
            print("sleeping %.0f min until next session..." % (wait / 60))
            await asyncio.sleep(wait)


async def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="new_account")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--unit", default="12")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--gather", action="store_true")
    ap.add_argument("--node", type=int, default=103282106)
    ap.add_argument("--army", default="")
    ap.add_argument("--autogather", action="store_true")
    ap.add_argument("--alliance", type=int, default=0)
    ap.add_argument("--city", default="")
    ap.add_argument("--node-pos", default="")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--cycles", type=int, default=0)
    ap.add_argument("--interval", type=float, default=15)
    ap.add_argument("--session", type=float, default=5.0,
                    help="session duration in minutes (default: 5)")
    args = ap.parse_args()

    army = None
    if args.army:
        army = [(int(u), int(c)) for u, c in (p.split(":") for p in args.army.split(","))]
    city = tuple(float(v) for v in args.city.split(",")) if args.city else (0.0, 0.0)
    node_pos = tuple(float(v) for v in args.node_pos.split(",")) if args.node_pos else (0.0, 0.0)

    bot = CommandBot(args.profile)
    cycles = args.cycles if args.loop else 1
    await bot.run(args.train, args.gather, args.node, args.unit, args.count,
                  args.discover, army, args.autogather, args.alliance, city, node_pos,
                  cycles=cycles, interval_min=args.interval, session_min=args.session)


if __name__ == "__main__":
    asyncio.run(main())
