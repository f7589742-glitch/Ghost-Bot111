"""
Network layer — async TCP connection with optional SOCKS5/HTTP proxy.

Handles raw TCP socket creation, proxy tunneling, and the complete
login-to-play lifecycle sequence over port 3101.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, List, Optional

from .behavior import PacketJitter
from .config import (
    GREETING_TIMEOUT,
    RECEIVE_BUFFER_SIZE,
    RECEIVE_TIMEOUT,
)
from .crypto import CryptoPair
from .protocol import (
    Frame,
    FrameParser,
    GreetingNonce,
    build_keepalive,
    build_login_frame,
    parse_greeting,
)

logger = logging.getLogger("rokbot.network")

try:
    import python_socks  # noqa: F401 — availability check
    HAS_SOCKS = True
except ImportError:
    HAS_SOCKS = False


class ConnectionError(Exception):
    pass


class GameConnection:
    """
    Async TCP connection to a RoK game server on port 3101.

    Lifecycle:
      DISCONNECTED → CONNECTING → AWAITING_GREETING → LOGIN_SENT → CONNECTED → DISCONNECTING
    """

    def __init__(
        self,
        host: str,
        port: int = 3101,
        proxy_url: Optional[str] = None,
        account_id: str = "",
    ):
        self.host = host
        self.port = port
        self.proxy_url = proxy_url
        self.account_id = account_id

        self.state = "disconnected"
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._parser = FrameParser()
        self._crypto: Optional[CryptoPair] = None
        self._greeting: Optional[GreetingNonce] = None

        self._tasks: List[asyncio.Task] = []
        self._frame_handlers: List[Callable] = []
        self._running = False

        self.connected_at: float = 0.0
        self.frames_rx: int = 0
        self.frames_tx: int = 0
        self.bytes_rx: int = 0
        self.bytes_tx: int = 0

    @property
    def crypto(self) -> Optional[CryptoPair]:
        return self._crypto

    @property
    def greeting(self) -> Optional[GreetingNonce]:
        return self._greeting

    @property
    def is_connected(self) -> bool:
        return self.state == "connected"

    def register_handler(self, handler: Callable):
        self._frame_handlers.append(handler)

    async def connect(self) -> bool:
        try:
            self.state = "connecting"
            logger.info(f"[{self.account_id}] TCP connecting to {self.host}:{self.port} ...")

            if self.proxy_url and HAS_SOCKS:
                from python_socks.async_.asyncio import Proxy
                proxy = Proxy.from_url(self.proxy_url)
                self._reader, self._writer = await proxy.open_connection(
                    dest_host=self.host, dest_port=self.port
                )
            else:
                self._reader, self._writer = await asyncio.open_connection(
                    self.host, self.port
                )

            logger.info(f"[{self.account_id}] TCP established")
            return True

        except Exception as e:
            logger.error(f"[{self.account_id}] TCP connect failed: {e}")
            self.state = "error"
            return False

    async def receive_greeting(self) -> Optional[GreetingNonce]:
        try:
            self.state = "awaiting_greeting"
            logger.info(f"[{self.account_id}] Waiting for greeting ...")

            header = await asyncio.wait_for(
                self._reader.readexactly(2), timeout=GREETING_TIMEOUT
            )
            length = (header[0] << 8) | header[1]
            payload = await asyncio.wait_for(
                self._reader.readexactly(length), timeout=GREETING_TIMEOUT
            )
            raw = header + payload

            self._greeting = parse_greeting(raw)
            logger.info(f"[{self.account_id}] Greeting: {self._greeting}")

            seed1 = self._greeting.seed1
            seed2 = self._greeting.seed2
            self._crypto = CryptoPair(seed1, seed2)
            logger.info(f"[{self.account_id}] Crypto: {self._crypto}")

            return self._greeting

        except asyncio.TimeoutError:
            logger.error(f"[{self.account_id}] Greeting timeout")
            self.state = "error"
            return None
        except Exception as e:
            logger.error(f"[{self.account_id}] Greeting failed: {e}")
            self.state = "error"
            return None

    async def send_login(
        self,
        player_id: str,
        access_token: str,
        server: str = "",
        app_uid: str = "",
        device_udid: str = "",
    ) -> bool:
        try:
            self.state = "login_sent"
            # Live-style Android login when we know app_uid + device (proven
            # 2026-09-10: full world stream; f14 role logins get a thinner
            # stream and role selection happens post-login via 203+110).
            if app_uid and device_udid:
                from .protocol import build_ordered_login_frame
                try:
                    local_port = self._writer.get_extra_info("sockname")[1]
                except Exception:
                    local_port = 50000
                payload = build_ordered_login_frame(
                    app_uid=app_uid,
                    access_token=access_token,
                    device_udid=device_udid,
                    src_port=local_port,
                )
                kind = "android-ordered"
            else:
                payload = build_login_frame(player_id, access_token, server=server)
                kind = "template"
            encrypted = self._crypto.tx.encrypt(payload)
            frame_wire = FrameParser.build_frame(encrypted)
            await self._raw_send(frame_wire)
            logger.info(f"[{self.account_id}] Login sent ({kind}, {len(payload)}B payload)")
            return True
        except Exception as e:
            logger.error(f"[{self.account_id}] Login send failed: {e}")
            self.state = "error"
            return False

    async def wait_for_initial_data(self, timeout: float = 8.0) -> List[Frame]:
        frames: List[Frame] = []
        try:
            data = await asyncio.wait_for(
                self._reader.read(RECEIVE_BUFFER_SIZE), timeout=timeout
            )
            if data:
                self.bytes_rx += len(data)
                parsed = self._parser.feed(data)
                for f in parsed:
                    self.frames_rx += 1
                    decrypted = self._decrypt_frame(f)
                    frames.append(decrypted)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.warning(f"[{self.account_id}] Initial data read: {e}")
        return frames

    def start_receiving(self):
        self._running = True
        self._tasks = [
            asyncio.create_task(self._receiver_loop(), name=f"rx_{self.account_id}"),
            asyncio.create_task(self._keepalive_loop(), name=f"ka_{self.account_id}"),
        ]
        self.state = "connected"
        self.connected_at = time.time()
        logger.info(f"[{self.account_id}] Session active")

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def disconnect(self):
        try:
            await self.stop()
        finally:
            await self._cleanup_socket()
            self.state = "disconnected"
            logger.info(f"[{self.account_id}] Disconnected")

    async def send_frame(self, payload: bytes):
        # Send whenever the socket + crypto exist (i.e. after greeting).
        # NOTE: this must NOT require state == "connected": the login-phase
        # init sequence is transmitted before start_receiving() flips the
        # state, and the old guard silently dropped all of it.
        if self._writer is None or self._crypto is None:
            return
        encrypted = self._crypto.tx.encrypt(payload)
        frame_wire = FrameParser.build_frame(encrypted)
        await self._raw_send(frame_wire)

    async def send_encrypted_raw(self, plaintext: bytes):
        await self.send_frame(plaintext)

    async def send_command(self, msg_id: int, payload: bytes = b""):
        from .protobuf import encode_field_varint, encode_field_bytes
        inner = encode_field_varint(1, msg_id)
        inner += encode_field_bytes(2, payload)  # field 2 is always length-delimited
        await self.send_frame(inner)

    async def _receiver_loop(self):
        logger.debug(f"[{self.account_id}] Receiver loop started")
        try:
            while self._running:
                data = await asyncio.wait_for(
                    self._reader.read(RECEIVE_BUFFER_SIZE),
                    timeout=RECEIVE_TIMEOUT,
                )
                if not data:
                    logger.warning(f"[{self.account_id}] Server closed connection")
                    self.state = "disconnected"
                    break

                self.bytes_rx += len(data)
                frames = self._parser.feed(data)

                for frame in frames:
                    self.frames_rx += 1
                    decrypted = self._decrypt_frame(frame)
                    for handler in self._frame_handlers:
                        try:
                            await handler(decrypted)
                        except Exception as e:
                            logger.error(f"[{self.account_id}] Handler error: {e}")

        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            logger.debug(f"[{self.account_id}] Receiver timeout (idle)")
        except Exception as e:
            logger.error(f"[{self.account_id}] Receiver error: {e}")
            self.state = "error"

    async def _keepalive_loop(self):
        from .behavior import BehaviorSimulator
        sim = BehaviorSimulator(base_interval=5.0, std_dev=0.35)
        logger.debug(f"[{self.account_id}] Keepalive loop started")
        try:
            while self._running:
                delay = sim.next_delay()
                await asyncio.sleep(delay)
                if self._running and self.is_connected:
                    ka = build_keepalive()
                    await self.send_frame(ka)
                    self.frames_tx += 1
        except asyncio.CancelledError:
            pass

    def _decrypt_frame(self, frame: Frame) -> Frame:
        if self._crypto and len(frame.payload) > 0:
            try:
                decrypted_payload = self._crypto.rx.decrypt(frame.payload)
                return Frame(
                    length=frame.length,
                    payload=decrypted_payload,
                    raw=frame.raw,
                )
            except Exception as e:
                logger.warning(f"[{self.account_id}] Decrypt failed: {e}")
        return frame

    async def _raw_send(self, data: bytes):
        if self._writer is None or self._writer.is_closing():
            raise ConnectionError("Not connected")
        self._writer.write(data)
        await self._writer.drain()
        self.bytes_tx += len(data)
        self.frames_tx += 1

        jitter = PacketJitter.micro_jitter()
        if jitter > 0.01:
            await asyncio.sleep(jitter)

    async def _cleanup_socket(self):
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        self._crypto = None
        self._parser = FrameParser()

    def stats(self) -> dict:
        uptime = time.time() - self.connected_at if self.connected_at else 0
        return {
            "state": self.state,
            "account_id": self.account_id,
            "frames_rx": self.frames_rx,
            "frames_tx": self.frames_tx,
            "bytes_rx": self.bytes_rx,
            "bytes_tx": self.bytes_tx,
            "uptime_s": round(uptime, 1),
        }
