"""
headless_client.py — Production-Grade Async Network Protocol Engine
====================================================================

Asynchronous state machine for connecting to Rise of Kingdoms game servers
on port 3101, handling the custom binary framing protocol over raw TCP,
with full integration of the verified RokCrypto stream cipher.

Lifecycle Phases:
  Phase 1: Raw TCP Connection
  Phase 2: Server Greeting Ingestion (19-byte protobuf, extract 8-byte nonce)
  Phase 3: Handshake Response (encrypted via newly initialized RokCrypto)
  Phase 4: Concurrent Keep-Alive + Connection Receiver tasks

Frame Format:
  [type:1][length:varint][payload: encrypted]
  - type 0x00: Control (keepalive, push, greeting)
  - type 0x01: Server data
  - type 0x02: Client game data

Encryption:
  Triple additive LFSR stream cipher (crypto_module.RokCrypto)
  Seed derived from 8-byte server nonce (bytes 6-13 of greeting)

WARNING: This is for educational/research purposes only.
Using custom clients violates Rise of Kingdoms Terms of Service.
"""

import asyncio
import struct
import json
import os
import sys
import time
import logging
from enum import IntEnum
from typing import Optional, Dict, Any, List, Tuple, Callable, Awaitable
from dataclasses import dataclass, field

from crypto_module import RokCrypto

# ──────────────────────────────────────────────────────────────────────
# Project root for relative imports
# ──────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ──────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────

logger = logging.getLogger("rok_client")
logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
))
logger.addHandler(_handler)


# ──────────────────────────────────────────────────────────────────────
# Constants & Enums
# ──────────────────────────────────────────────────────────────────────

class FrameType(IntEnum):
    CONTROL   = 0x00
    SERVER    = 0x01
    CLIENT    = 0x02

class ClientState(IntEnum):
    DISCONNECTED    = 0
    CONNECTING      = 1
    AWAITING_GREETING = 2
    LOGIN_SENT      = 3
    CONNECTED       = 4
    DISCONNECTING   = 5
    ERROR           = 6

DEFAULT_HOST = "43.159.113.101"
DEFAULT_PORT = 3101
KEEPALIVE_INTERVAL = 3.0
RECEIVE_BUFFER_SIZE = 65536

# Captured login protobuf (decrypted) from a real game session
# Top-level: [1]=14, [2]=nested login payload
LOGIN_PAYLOAD = bytes.fromhex(
    "080e12a60462063631333032370801da010a12000a02706322001a00ba011b"
    "726f63676174652e6c696c69746867616d652e636f6d3a3331303122103234"
    "32383035343131303635353932357a0131a201203032636131663132373538"
    "3337306439316430316435326431613431333634625a08312e312e392e3139"
    "c001043a3818cbb780011220442d49754a4368465353534c79646a3939704c"
    "5a44537864326c303463422d5028010a093232303239333835352202706332"
    "dd027a1a44697265637433442031312e30205b6c6576656c2031312e315d2a"
    "006a10323432383035343131303635353932353200620261724a023130121a"
    "636f6d2e6c696c69746867616d65732e726f6b2e70632e696e74c201087769"
    "6e33326370755208312e312e392e31398a01174e5649444941204765466f72"
    "6365205254582033303530920124313274682047656e20496e74656c285229"
    "20436f726528544d292069352d31323630304b5a0377696e9a010431373934"
    "420377696ea201043130303982010531363135300a053130303433ba012464"
    "323235383161652d636331312d346235342d613563382d3964356365313335"
    "32346633b2011433382e3136352e3233302e3139343a363333313122267632"
    "36363938663762322d323464372d343161332d613736662d63643734323630"
    "3739346638720377696e1a0d73656c662d6c696c6974682d313a0e33382e31"
    "36352e3233302e3139346a0e33382e3136352e3233302e3139344801"
)


def resolve_game_token(tokens: dict) -> str:
    """
    Token lock (device-forensics 2026-09-10): the game TCP socket (Opcode 14
    login + Opcode 161 second-auth) must carry the BOUND access token — the
    `b` token in the device's auto_login_users record, which the live client
    puts in TCP auth.f2 (A-7O... got AmmAr+15+302 on the real client).
    Profiles store the bound token in the access_token slot, so prefer it;
    app_token is fallback only (it powers the refresh chain, and the SDK
    platform token it mirrors is NOT valid on the TCP wire).
    """
    return str(tokens.get("access_token") or tokens.get("app_token") or "")


def build_login_payload(tokens: dict) -> bytes:
    """
    Build a login protobuf with fresh tokens injected into the template.

    Replaces:
      - Inner field 4  → player_id (in-game character ID, NOT app_uid)
      - Inner field 7 sub-field 1 → player_id
      - Inner field 7 sub-field 2 → game token (app_token first, see
        resolve_game_token)

    Tokens dict expected keys: player_id, access_token/app_token,
    (app_uid optional)
    """
    top = ProtobufCodec.decode_message(LOGIN_PAYLOAD)
    inner = ProtobufCodec.decode_message(top[2])

    # Use player_id (in-game character ID) — NOT app_uid (account ID).
    # Never overwrite an explicit role id with app_uid (same lock as
    # rokbot/session.py: role clobbering silently plays the wrong char).
    pid = str(tokens.get("player_id") or tokens.get("app_uid", ""))
    if pid:
        inner[4] = pid

    game_token = resolve_game_token(tokens)
    if game_token and 7 in inner:
        f7 = ProtobufCodec.decode_message(inner[7])
        f7[1] = pid.encode() if pid else f7[1]  # player_id in auth sub-field
        f7[2] = game_token.encode("utf-8")
        inner[7] = ProtobufCodec.encode_message(f7)

    top[2] = ProtobufCodec.encode_message(inner)
    return ProtobufCodec.encode_message(top)


def build_minimal_login(tokens: dict) -> bytes:
    """
    Build the minimal login payload (~79 bytes) that the server accepts
    and streams full game data. The 555-byte LOGIN_PAYLOAD is too large;
    the server only sends ACK+success (no game data) with it.

    Discovered empirically: the server needs field 5=1 in the auth sub-message
    to stream game data. Without it, the connection works but gets no data.

    IMPORTANT: For multi-character accounts, player_id MUST be used (not app_uid).
    app_uid is the account identifier, player_id is the character identifier.
    Using app_uid returns data for a random/default character.

    Tokens dict expected keys: access_token/app_token, app_uid,
    player_id (optional, preferred). Game token resolves via
    resolve_game_token (app_token first).
    """
    # Use player_id if available, fallback to app_uid
    pid = str(tokens.get('player_id') or tokens['app_uid'])

    inner = {1: 1, 9: 1}
    inner[4] = ProtobufCodec.encode_message({6: pid.encode()})
    auth = {
        1: pid.encode(),  # player_id (character ID) — NOT app_uid
        2: resolve_game_token(tokens).encode(),
        3: 2104267,
        4: b'android',
        5: 1,
    }
    inner[7] = ProtobufCodec.encode_message(auth)
    top = {1: 14, 2: ProtobufCodec.encode_message(inner)}
    return ProtobufCodec.encode_message(top)


# ──────────────────────────────────────────────────────────────────────
# Protobuf Encoder / Decoder (lightweight, no external deps)
# ──────────────────────────────────────────────────────────────────────

class ProtobufCodec:
    """Minimal protobuf varint / length-delimited codec."""

    @staticmethod
    def encode_varint(value: int) -> bytes:
        result = bytearray()
        while value > 0x7F:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value & 0x7F)
        return bytes(result)

    @staticmethod
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

    @staticmethod
    def encode_field_varint(field_num: int, value: int) -> bytes:
        tag = (field_num << 3) | 0
        return ProtobufCodec.encode_varint(tag) + ProtobufCodec.encode_varint(value)

    @staticmethod
    def encode_field_bytes(field_num: int, data: bytes) -> bytes:
        tag = (field_num << 3) | 2
        return ProtobufCodec.encode_varint(tag) + ProtobufCodec.encode_varint(len(data)) + data

    @staticmethod
    def decode_message(data: bytes) -> Dict[int, Any]:
        fields = {}
        offset = 0
        while offset < len(data):
            tag, offset = ProtobufCodec.decode_varint(data, offset)
            field_number = tag >> 3
            wire_type = tag & 0x07
            if field_number == 0:
                break

            if wire_type == 0:
                value, offset = ProtobufCodec.decode_varint(data, offset)
            elif wire_type == 1:
                value = struct.unpack("<Q", data[offset:offset + 8])[0]
                offset += 8
            elif wire_type == 2:
                length, offset = ProtobufCodec.decode_varint(data, offset)
                value = data[offset:offset + length]
                offset += length
            elif wire_type == 5:
                value = struct.unpack("<I", data[offset:offset + 4])[0]
                offset += 4
            else:
                break

            if field_number in fields:
                if not isinstance(fields[field_number], list):
                    fields[field_number] = [fields[field_number]]
                fields[field_number].append(value)
            else:
                fields[field_number] = value
        return fields

    @staticmethod
    def decode_nested(data: bytes) -> Dict[int, Any]:
        return ProtobufCodec.decode_message(data)

    @staticmethod
    def encode_message(fields: Dict[Any, Any]) -> bytes:
        """Encode a field dict back to protobuf wire format."""
        result = bytearray()
        for field_num in sorted(fields.keys(), key=lambda k: int(k)):
            fn = int(field_num)
            value = fields[field_num]
            if isinstance(value, list):
                for v in value:
                    result.extend(ProtobufCodec._encode_field(fn, v))
            else:
                result.extend(ProtobufCodec._encode_field(fn, value))
        return bytes(result)

    @staticmethod
    def _encode_field(field_num: int, value: Any) -> bytes:
        if isinstance(value, int):
            tag = ProtobufCodec.encode_varint((field_num << 3) | 0)
            return tag + ProtobufCodec.encode_varint(value)
        elif isinstance(value, (bytes, bytearray)):
            tag = ProtobufCodec.encode_varint((field_num << 3) | 2)
            return tag + ProtobufCodec.encode_varint(len(value)) + bytes(value)
        elif isinstance(value, str):
            data = value.encode('utf-8')
            tag = ProtobufCodec.encode_varint((field_num << 3) | 2)
            return tag + ProtobufCodec.encode_varint(len(data)) + data
        elif isinstance(value, dict):
            nested = ProtobufCodec.encode_message(value)
            tag = ProtobufCodec.encode_varint((field_num << 3) | 2)
            return tag + ProtobufCodec.encode_varint(len(nested)) + nested
        else:
            raise TypeError(f"Unsupported field type: {type(value)} for field {field_num}")


# ──────────────────────────────────────────────────────────────────────
# Frame Parser — handles TCP fragmentation / partial reads
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Frame:
    frame_type: int
    length: int
    payload: bytes
    raw: bytes = b""

    def __repr__(self):
        preview = self.payload[:30].hex()
        return (f"Frame(type=0x{self.frame_type:02x}, len={self.length}, "
                f"payload={preview}{'...' if self.length > 30 else ''})")


class FrameParser:
    """
    Defensive frame parser that accumulates TCP stream bytes and yields
    complete frames, handling partial reads and compound frames.

    Wire format: [length:2-big-endian][payload:length]
      The first 2 bytes are the payload length as uint16 big-endian.
      Frame "type" is embedded in the protobuf payload.
    """

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data: bytes) -> List[Frame]:
        """Feed raw TCP bytes, return list of fully parsed frames."""
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
        header_size = 2

        total = header_size + length
        if len(self._buffer) < total:
            return None, 0

        payload = bytes(self._buffer[header_size:total])
        raw = bytes(self._buffer[:total])

        # "type" is embedded in the payload; store 0 as placeholder
        return Frame(
            frame_type=0,
            length=length,
            payload=payload,
            raw=raw,
        ), total

    @staticmethod
    def build_frame(payload: bytes) -> bytes:
        """Build a wire frame with 2-byte big-endian length."""
        length = len(payload)
        return length.to_bytes(2, 'big') + payload

    @property
    def buffered(self) -> int:
        return len(self._buffer)


# ──────────────────────────────────────────────────────────────────────
# Server Greeting Parser
# ──────────────────────────────────────────────────────────────────────

@dataclass
class GreetingInfo:
    raw: bytes
    field1: int
    nonce_12: bytes
    sub1: int
    sub2: int
    nonce_8: bytes

    def __repr__(self):
        return (f"Greeting(field1={self.field1}, sub1=0x{self.sub1:08x}, "
                f"sub2=0x{self.sub2:08x}, nonce8={self.nonce_8.hex()})")


def parse_greeting(raw: bytes) -> GreetingInfo:
    """
    Parse the variable-length server greeting frame.

    Wire: [length:2-big-endian][protobuf_payload]
    The protobuf contains field1 (varint 8562) and field2 (nested protobuf).
    The nested protobuf has two varint sub-fields.
    """
    if len(raw) < 4:
        raise ValueError(f"Greeting too short: {len(raw)} bytes")

    protobuf = raw[2:]  # skip 2-byte length header
    fields = ProtobufCodec.decode_message(protobuf)

    field1 = fields.get(1, 0)
    field2 = fields.get(2, b"")

    sub1, sub2 = 0, 0
    if isinstance(field2, (bytes, bytearray)) and len(field2) >= 2:
        sub_fields = ProtobufCodec.decode_message(field2)
        sub1 = sub_fields.get(1, 0)
        sub2 = sub_fields.get(2, 0)

    nonce_8 = struct.pack("<II", sub1 & 0xFFFFFFFF, sub2 & 0xFFFFFFFF)

    return GreetingInfo(
        raw=raw,
        field1=field1,
        nonce_12=field2 if isinstance(field2, (bytes, bytearray)) else b"",
        sub1=sub1,
        sub2=sub2,
        nonce_8=nonce_8,
    )


# ──────────────────────────────────────────────────────────────────────
# Protobuf Message Placeholders (game-specific decoding)
# ──────────────────────────────────────────────────────────────────────

class GameMessageDecoder:
    """
    Decodes incoming decrypted frame payloads by examining protobuf fields.
    """

    @staticmethod
    def decode(frame: Frame) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "frame_len": frame.length,
            "payload_len": len(frame.payload),
            "handler": "unknown",
            "protobuf": None,
        }

        try:
            fields = ProtobufCodec.decode_message(frame.payload)
            result["protobuf"] = fields
            f1 = fields.get(1, None)
            if isinstance(f1, int) and f1 == 8562:
                result["handler"] = "greeting"
            elif isinstance(f1, int) and f1 == 14:
                # Field [1]=14 in login response (wait, that was request)
                result["handler"] = "login_response"
            else:
                result["handler"] = f"fields_{sorted(fields.keys())[:3]}"
        except Exception:
            result["handler"] = "binary"

        return result


# ──────────────────────────────────────────────────────────────────────
# Async Protocol Engine
# ──────────────────────────────────────────────────────────────────────

class RokProtocol:
    """
    Asynchronous state machine for the ROK port 3101 protocol.

    Lifecycle:
      DISCONNECTED -> CONNECTING -> AWAITING_GREETING -> HANDSHAKING -> CONNECTED

    Crypto:
      seed1 (State1) → decrypt incoming server frames
      seed2 (State2) → encrypt outgoing client frames
      If only seed is provided (legacy), same state used for both directions.

    Concurrent tasks during CONNECTED:
      - _keepalive_loop(): sends periodic keepalive frames
      - _receiver_loop(): reads TCP, feeds FrameParser, dispatches frames
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        keepalive_interval: float = KEEPALIVE_INTERVAL,
        seed1: Optional[int] = None,
        seed2: Optional[int] = None,
        seed: Optional[int] = None,
        login_payload: Optional[bytes] = None,
    ):
        self.host = host
        self.port = port
        self.keepalive_interval = keepalive_interval
        self._seed1 = seed1
        self._seed2 = seed2
        self._manual_seed = seed  # legacy single-seed mode
        self._login_payload = login_payload or LOGIN_PAYLOAD

        self.state = ClientState.DISCONNECTED
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._parser = FrameParser()
        self._crypto_tx: Optional[RokCrypto] = None  # seed2: encrypt outgoing
        self._crypto_rx: Optional[RokCrypto] = None  # seed1: decrypt incoming
        self._crypto: Optional[RokCrypto] = None     # legacy single crypto
        self._greeting: Optional[GreetingInfo] = None

        self._tasks: List[asyncio.Task] = []
        self._frame_handlers: List[Callable[[Frame], Awaitable[None]]] = []
        self._stats = {
            "frames_sent": 0,
            "frames_received": 0,
            "keepalives_sent": 0,
            "bytes_sent": 0,
            "bytes_received": 0,
        }

    # ── Public API ───────────────────────────────────────────────────

    async def connect(self) -> bool:
        """Phase 1 + 2 + 3: TCP connect, receive greeting, handshake."""
        try:
            # Phase 1: Raw TCP Connection
            self._transition(ClientState.CONNECTING)
            logger.info(f"Connecting to {self.host}:{self.port}...")
            self._reader, self._writer = await asyncio.open_connection(
                self.host, self.port
            )
            logger.info("TCP connection established")

            # Phase 2: Ingest Server Greeting (variable-length frame)
            self._transition(ClientState.AWAITING_GREETING)
            greeting_raw = await asyncio.wait_for(
                self._read_greeting(), timeout=10.0
            )
            self._greeting = parse_greeting(greeting_raw)
            logger.info(f"Server greeting: {self._greeting}")

            # Phase 2b: Initialize crypto from provided seeds
            # EMPIRICAL: seed1 = TX crypto (outgoing), seed2 = RX crypto (incoming)
            if self._seed1 is not None and self._seed2 is not None:
                self._crypto_tx = RokCrypto(self._seed1)
                self._crypto_rx = RokCrypto(self._seed2)
                logger.info(
                    f"Dual crypto: tx(seed1=0x{self._seed1:08x}, "
                    f"id=0x{self._crypto_tx.get_identifier():08x}), "
                    f"rx(seed2=0x{self._seed2:08x}, "
                    f"id=0x{self._crypto_rx.get_identifier():08x})"
                )
            elif self._manual_seed is not None:
                self._crypto = RokCrypto(self._manual_seed)
                logger.info(f"Legacy crypto: seed=0x{self._manual_seed:08x}")
            else:
                from derive_seed_from_nonce import parse_greeting as _pg, derive_seed
                _parsed = _pg(self._greeting.raw)
                _s1 = _parsed['sub1']
                _s2 = _parsed['sub2']
                _mapped = None
                try:
                    _mapped = derive_seed(_s1, _s2)
                except Exception:
                    pass
                if _mapped:
                    self._crypto_tx = RokCrypto(_mapped[0])
                    self._crypto_rx = RokCrypto(_mapped[1])
                    seed = _mapped[0]
                    logger.info(f"Mapped pair: seed1=0x{_mapped[0]:08x} seed2=0x{_mapped[1]:08x}")
                else:
                    seed = 0
                    self._crypto = RokCrypto(seed)
                    logger.info(f"Unknown nonce pair 0x{_s1:08x}/0x{_s2:08x}, using fallback seed=0x{seed:08x}")
                logger.info(f"Crypto initialized from greeting nonce")

            # Phase 3: Send login payload (protobuf, encrypted with seed1/TX)
            self._transition(ClientState.LOGIN_SENT)
            await self._send_login_frame()

            # Phase 4: Spin up concurrent tasks
            self._transition(ClientState.CONNECTED)
            await self._start_tasks()

            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._transition(ClientState.ERROR)
            await self._cleanup()
            return False

    async def connect_minimal(self, app_uid: str, access_token: str, custom_payload: Optional[bytes] = None) -> bool:
        """
        Connect with authentic handshake or minimal login.
        If custom_payload is provided, uses that exact frame (e.g. from HandshakeBuilder).
        """
        try:
            self._transition(ClientState.CONNECTING)
            logger.info(f"Connecting to {self.host}:{self.port}...")
            self._reader, self._writer = await asyncio.open_connection(
                self.host, self.port
            )

            self._transition(ClientState.AWAITING_GREETING)
            greeting_raw = await asyncio.wait_for(
                self._read_greeting(), timeout=10.0
            )
            self._greeting = parse_greeting(greeting_raw)

            from derive_seed_from_nonce import derive_seed
            _mapped = derive_seed(self._greeting.sub1, self._greeting.sub2)
            self._crypto_tx = RokCrypto(_mapped[0])
            self._crypto_rx = RokCrypto(_mapped[1])
            logger.info(f"Crypto initialized from greeting nonce: seed1=0x{_mapped[0]:08x} seed2=0x{_mapped[1]:08x}")

            self._transition(ClientState.LOGIN_SENT)
            if custom_payload:
                login_payload = custom_payload
                logger.info(f"Using authentic custom login payload ({len(login_payload)}b)")
            else:
                login_payload = build_minimal_login({
                    'access_token': access_token,
                    'app_uid': app_uid,
                })
                logger.info(f"Using standard minimal login payload ({len(login_payload)}b)")

            tx = self._crypto_tx
            encrypted = tx.encrypt(login_payload)
            frame_wire = FrameParser.build_frame(encrypted)
            await self._raw_send(frame_wire)
            logger.info(f"Login frame dispatched: {len(login_payload)}b payload")

            self._transition(ClientState.CONNECTED)
            await self._start_tasks()
            return True

        except Exception as e:
            logger.error(f"Minimal connection failed: {e}")
            self._transition(ClientState.ERROR)
            await self._cleanup()
            return False

    async def disconnect(self):
        """Graceful shutdown."""
        self._transition(ClientState.DISCONNECTING)
        await self._stop_tasks()
        await self._cleanup()
        self._transition(ClientState.DISCONNECTED)
        logger.info("Disconnected")

    def register_handler(self, handler: Callable[[Frame], Awaitable[None]]):
        """Register a callback for each received frame."""
        self._frame_handlers.append(handler)

    @property
    def stats(self) -> Dict[str, Any]:
        cry = self._crypto_tx or self._crypto
        return {
            **self._stats,
            "state": self.state.name,
            "crypto_id": cry.get_identifier() if cry else None,
            "dual_crypto": (self._crypto_tx is not None and self._crypto_rx is not None),
        }

    # ── Phase 2: Greeting Reading ────────────────────────────────────

    async def _read_greeting(self) -> bytes:
        """
        Read a variable-length greeting frame from the server.

        Frame format: [length:2-big-endian][payload:length]
        Returns the complete raw frame including header.
        """
        header = await self._reader.readexactly(2)
        length = (header[0] << 8) | header[1]

        payload = await self._reader.readexactly(length)
        greeting_raw = header + payload
        logger.info(f"Greeting frame: len={length} raw={greeting_raw.hex()}")
        return greeting_raw

    # ── Phase 3: Login Frame ──────────────────────────────────────────

    async def _send_login_frame(self):
        """
        Transmit the login protobuf as the first client frame.

        Wire format: [length:2-big-endian][encrypted_payload]
        """
        tx = self._crypto_tx or self._crypto
        encrypted = tx.encrypt(self._login_payload)

        frame_wire = FrameParser.build_frame(encrypted)

        await self._raw_send(frame_wire)
        logger.info(f"Login frame sent: {len(frame_wire)} bytes "
                     f"(plain={len(self._login_payload)}b encrypted={len(encrypted)}b)")

    # ── Phase 4: Concurrent Tasks ────────────────────────────────────

    async def _start_tasks(self):
        self._tasks = [asyncio.create_task(self._receiver_loop(), name="receiver")]
        if self.keepalive_interval and self.keepalive_interval > 0:
            self._tasks.insert(0, asyncio.create_task(self._keepalive_loop(), name="keepalive"))
        logger.info(f"Started {len(self._tasks)} concurrent tasks")

    async def _stop_tasks(self):
        curr_task = asyncio.current_task()
        tasks_to_cancel = [t for t in self._tasks if t is not curr_task and not t.done()]
        for task in tasks_to_cancel:
            task.cancel()
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        self._tasks.clear()

    async def _keepalive_loop(self):
        """
        Send periodic keepalive frames to maintain the connection.
        """
        logger.info(f"Keepalive loop started (interval={self.keepalive_interval}s)")
        try:
            while self.state == ClientState.CONNECTED:
                await asyncio.sleep(self.keepalive_interval)
                payload = os.urandom(4)
                frame_wire = FrameParser.build_frame(payload)
                await self._raw_send(frame_wire)
                self._stats["keepalives_sent"] += 1
                logger.debug(f"Keepalive sent: {payload.hex()}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Keepalive error: {e}")
            self._transition(ClientState.ERROR)

    async def _receiver_loop(self):
        """
        Continuous connection receiver. Reads raw TCP bytes, feeds the
        FrameParser (handling fragmentation), decrypts payloads, and
        dispatches frames to registered handlers.
        """
        logger.info("Receiver loop started")
        try:
            while self.state == ClientState.CONNECTED:
                data = await asyncio.wait_for(
                    self._reader.read(RECEIVE_BUFFER_SIZE), timeout=30.0
                )
                if not data:
                    logger.warning("Connection closed by server")
                    self._transition(ClientState.DISCONNECTED)
                    break

                self._stats["bytes_received"] += len(data)
                frames = self._parser.feed(data)

                for frame in frames:
                    self._stats["frames_received"] += 1
                    await self._dispatch_frame(frame)

        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            logger.warning("Receiver timeout (no data for 30s)")
        except Exception as e:
            logger.error(f"Receiver error: {e}")
            self._transition(ClientState.ERROR)

    async def _dispatch_frame(self, frame: Frame):
        """Decrypt, classify, log, and dispatch a frame."""
        decrypted_payload = frame.payload
        rx = self._crypto_rx or self._crypto
        if rx and len(frame.payload) > 0:
            try:
                decrypted_payload = rx.decrypt(frame.payload)
            except Exception as e:
                logger.warning(f"Decryption failed: {e}")

        decrypted_frame = Frame(
            frame_type=0,
            length=frame.length,
            payload=decrypted_payload,
            raw=frame.raw,
        )

        info = GameMessageDecoder.decode(decrypted_frame)
        logger.info(
            f"RX len={frame.length} payload={decrypted_payload[:40].hex()}"
            f"{'...' if len(decrypted_payload) > 40 else ''}"
        )

        for handler in self._frame_handlers:
            try:
                await handler(decrypted_frame)
            except Exception as e:
                logger.error(f"Handler error: {e}")

    # ── Send API ─────────────────────────────────────────────────────

    async def send_data(self, plaintext_payload: bytes):
        """Encrypt and send a data frame."""
        if self.state != ClientState.CONNECTED:
            raise RuntimeError(f"Cannot send in state {self.state.name}")

        tx = self._crypto_tx or self._crypto
        encrypted = tx.encrypt(plaintext_payload)
        frame_wire = FrameParser.build_frame(encrypted)
        await self._raw_send(frame_wire)

        logger.info(
            f"TX len={len(plaintext_payload)} "
            f"payload={plaintext_payload[:40].hex()}"
            f"{'...' if len(plaintext_payload) > 40 else ''}"
        )

    async def send_control(self, payload: bytes):
        """Send a control frame."""
        await self.send_data(payload)

    async def send_game_data(self, payload: bytes):
        """Send a game data frame."""
        await self.send_data(payload)

    # ── Internal ─────────────────────────────────────────────────────

    async def _raw_send(self, data: bytes):
        """Write raw bytes to the TCP stream."""
        if self._writer is None or self._writer.is_closing():
            raise ConnectionError("Not connected")
        self._writer.write(data)
        await self._writer.drain()
        self._stats["bytes_sent"] += len(data)
        self._stats["frames_sent"] += 1

    def _transition(self, new_state: ClientState):
        old = self.state
        self.state = new_state
        logger.debug(f"State: {old.name} -> {new_state.name}")

    async def _cleanup(self):
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        self._crypto_tx = None
        self._crypto_rx = None
        self._crypto = None
        self._parser = FrameParser()

    def __repr__(self):
        return f"<RokProtocol {self.host}:{self.port} state={self.state.name}>"


# ──────────────────────────────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────────────────────────────

async def main():
    """Connect to the game server and run the protocol engine."""
    import argparse
    parser = argparse.ArgumentParser(description="ROK Async Protocol Client")
    parser.add_argument("--host", default=None, help="Game server IP (default: from --load-seeds IPC or hardcoded)")
    parser.add_argument("--port", type=int, default=None, help="Game server port (default: from --load-seeds IPC or 3101)")
    parser.add_argument("--seed", type=lambda x: int(x, 0), default=None, help="Override crypto seed (hex, legacy single-crypto)")
    parser.add_argument("--seed1", type=lambda x: int(x, 0), default=None, help="Decrypt seed (hex, passthrough mode)")
    parser.add_argument("--seed2", type=lambda x: int(x, 0), default=None, help="Encrypt seed (hex, passthrough mode)")
    parser.add_argument("--load-seeds", type=str, default=None, help="Load seeds from IPC JSON file")
    parser.add_argument("--keepalive", type=float, default=KEEPALIVE_INTERVAL, help="Keepalive interval (seconds)")
    parser.add_argument("--profile", type=str, default=None, help="Load token profile (via core/session_manager.py)")
    parser.add_argument("--json-log", default=None, help="Dump frame log to JSON file")
    parser.add_argument("--no-consume", action="store_true",
                        help="Do NOT mark the token profile consumed after connecting (reusable for bots/reconnects)")
    parser.add_argument("--minimal", action="store_true",
                        help="Use minimal login payload (79b) to get full game data stream instead of just ACK")
    args = parser.parse_args()

    seed1 = args.seed1
    seed2 = args.seed2
    login_payload = None
    host = args.host
    port = args.port
    tokens = None
    profile_name = None

    # Optional: load token profile via session_manager
    if args.profile:
        from core.session_manager import SessionManager
        mgr = SessionManager(args.profile)
        profile = mgr.load_profile()
        if not profile or not profile.is_valid:
            logger.error(f"Token profile '{args.profile}' is invalid or expired")
            sys.exit(1)
        tokens = {
            "access_token": profile.access_token,
            "app_token": profile.app_token,
            "app_uid": profile.app_uid,
            "app_token_expire_at": profile.app_token_expire_at,
        }
        profile_name = args.profile
        if args.minimal:
            login_payload = build_minimal_login(tokens)
            logger.info(f"Using MINIMAL login payload")
        else:
            login_payload = build_login_payload(tokens)
            logger.info(f"Using FULL login payload")
        # Auto-load seeds from profile if not explicitly provided
        if seed1 is None and profile.seed1:
            seed1 = profile.seed1
            logger.info(f"  seed1=0x{seed1:08x} (from profile)")
        if seed2 is None and profile.seed2:
            seed2 = profile.seed2
            logger.info(f"  seed2=0x{seed2:08x} (from profile)")
        logger.info(
            f"Loaded profile '{args.profile}': uid={profile.app_uid} "
            f"token={profile.access_token[:20]}... "
            f"expires in {profile.expires_in_days:.1f}d"
        )
        # Load raw profile JSON for server_host/server_port
        try:
            with open(f"D:\\aa\\Headless Bot RoK\\profiles\\{args.profile}.json", "r") as f:
                raw_profile = json.load(f)
                if host is None and raw_profile.get("server_host"):
                    host = raw_profile["server_host"]
                    logger.info(f"  server_host={host} (from profile)")
                if port is None and raw_profile.get("server_port"):
                    port = raw_profile["server_port"]
                    logger.info(f"  server_port={port} (from profile)")
        except:
            pass

    # Optional: load seeds from IPC JSON file
    if args.load_seeds:
        with open(args.load_seeds) as f:
            ipc = json.load(f)
        if seed1 is None and 'seed1' in ipc:
            seed1 = int(ipc['seed1'], 16) if isinstance(ipc['seed1'], str) else ipc['seed1']
        if seed2 is None and 'seed2' in ipc:
            seed2 = int(ipc['seed2'], 16) if isinstance(ipc['seed2'], str) else ipc['seed2']
        if host is None and 'server' in ipc:
            parts = ipc['server'].split(':')
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else (port or DEFAULT_PORT)
        # Decrypt first_tx from IPC to get the login payload
        if seed1 is not None and 'first_tx' in ipc and ipc['first_tx']:
            raw = bytes.fromhex(ipc['first_tx'])
            from crypto_module import RokCrypto
            temp = RokCrypto(seed1)
            login_payload = temp.decrypt(raw[2:])  # skip 2-byte length header
            logger.info(f"Login payload: {len(login_payload)} bytes from first_tx")
        logger.info(f"Loaded seeds from {args.load_seeds}: seed1=0x{seed1:08x} seed2=0x{seed2:08x}")

    if host is None:
        host = DEFAULT_HOST
    if port is None:
        port = DEFAULT_PORT

    proto = RokProtocol(
        host=host,
        port=port,
        keepalive_interval=args.keepalive,
        seed1=seed1,
        seed2=seed2,
        seed=args.seed,
        login_payload=login_payload,
    )

    frame_log: List[Dict] = []

    async def log_handler(frame: Frame):
        frame_log.append({
            "ts": time.time(),
            "type": frame.frame_type,
            "len": frame.length,
            "payload_hex": frame.payload.hex(),
        })

    proto.register_handler(log_handler)

    if not await proto.connect():
        logger.error("Failed to connect")
        return

    # Mark token as consumed on successful connection (unless --no-consume)
    if profile_name and not args.no_consume and os.environ.get("ROK_MARK_CONSUMED", "1") == "1":
        from core.session_manager import SessionManager
        SessionManager(profile_name).mark_consumed()
        logger.info(f"Token profile '{profile_name}' marked consumed")

    logger.info(f"Connected! {proto}")
    logger.info(f"Stats: {proto.stats}")

    try:
        while proto.state == ClientState.CONNECTED:
            await asyncio.sleep(1)
            stats = proto.stats
            sys.stdout.write(
                f"\r[state={stats['state']}] "
                f"TX={stats['frames_sent']} RX={stats['frames_received']} "
                f"KA={stats['keepalives_sent']} "
                f"KB_TX={stats['bytes_sent']//1024} "
                f"KB_RX={stats['bytes_received']//1024}"
            )
            sys.stdout.flush()
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        print()

    await proto.disconnect()

    if args.json_log:
        with open(args.json_log, "w") as f:
            json.dump(frame_log, f, indent=2)
        logger.info(f"Frame log dumped to {args.json_log} ({len(frame_log)} frames)")

    logger.info(f"Final stats: {proto.stats}")


if __name__ == "__main__":
    asyncio.run(main())
