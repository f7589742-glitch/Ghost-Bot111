"""
Session state machine — full login-to-play lifecycle with graceful teardown.

Implements the precise sequence:
  1. Token refresh (if needed)
  2. TCP connection (with optional proxy)
  3. Greeting parsing + seed derivation
  4. Login frame transmission
  5. Initial data ingestion
  6. Init sequence (mirroring real client)
  7. Active session with keepalive
  8. Graceful disconnect (clears server-side session cache)
"""
from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Callable, Optional

from .auth import AuthManager
from .behavior import BehaviorSimulator, PacketJitter
from .config import AccountConfig, RECONNECT_BACKOFF_BASE, RECONNECT_BACKOFF_MAX
from .network import GameConnection
from .protocol import Frame

logger = logging.getLogger("rokbot.session")


class SessionState(Enum):
    IDLE = "idle"
    AUTHENTICATING = "authenticating"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    LOGGING_IN = "logging_in"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    DISCONNECTING = "disconnecting"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


# Init sequence mirroring the live Android client (live_gather_protocol_details.json).
# Order matters: greeting(14) -> this list -> 8035 state -> gameplay ops.
# Ops with b"" are empty {op, no inner} frames (5 bytes on wire, verified live).
# 588/8333 carry the exact live payloads; 6404/1202 below are placeholders —
# the session fills role-specific values in _send_init_sequence when known.
INIT_SEQUENCE = [
    # NOTE (live-verified 2026-09-10, fleet_ammar): the server ACKs init ops
    # individually. Dropped ops with proof of rejection on OUR gate:
    #   588 -> code 4 (ids [3088,...] are per-session, stale replay rejected)
    #   3749 -> 306, 6592/6801/6813 -> 301 (unknown ops on this gate)
    (8892, b""),
    (600, b"\x08\x08"),
    (8030, b""),
    (2003, b""),
    (2077, b""),
    (2500, b""),
    (2039, b"\x08\x01"),
    (8045, b""),
    (104, b""),
    (5600, b""),
    (930, b""),
    (9625, b""),
    (941, b""),
    (3303, b""),
    # NOTE: op 52 carries an AppVersion/Token JSON blob (account-specific);
    # sent separately when a token is available, skipped here.
    (3437, b""),
    (3857, b""),
    (6404, b"\x08\xf0\x10"),
    (1202, b"\x08\x96\xc3\xb9\x5b"),
    (4811, b""),
    (2065, b""),
    (2026, b""),
    (6639, b""),
    (3418, b""),
    (6645, b""),
    (8700, b""),
    (9426, b""),
    (1001, b""),
    (5501, b"\x08\x01"),
    (8333, b"\x08\x01\x08\x02\x08\x03\x08\x04\x08\x05\x08\x06"),
    (250, b""),
    (366, b""),
    (140, b""),
    (1041, b""),
    (450, b""),
    (1156, b""),
    (9706, b""),
    (9803, b""),
    (4491, b""),
    (553, b""),
    (544, b""),
    (6704, b""),
    (7600, b""),
    # Legacy ops kept for compat (not in the sampled live capture, harmless):
    (6522, b""),
    (3157, b""),
]


class Session:
    """
    Manages the complete lifecycle of one account's connection to the game server.

    Handles authentication, TCP connection, protocol handshake, init sequence,
    active keepalive, and graceful teardown.
    """

    def __init__(
        self,
        account: AccountConfig,
        auth_manager: AuthManager,
        on_frame: Optional[Callable] = None,
        on_state_change: Optional[Callable] = None,
    ):
        self.account = account
        self.auth = auth_manager
        self.on_frame = on_frame
        self.on_state_change = on_state_change

        self.state = SessionState.IDLE
        self._conn: Optional[GameConnection] = None
        self._behavior = BehaviorSimulator(base_interval=5.0, std_dev=0.35)
        self._consecutive_failures = 0
        self._last_reconnect = 0.0

    @property
    def is_active(self) -> bool:
        return self.state == SessionState.ACTIVE

    @property
    def conn(self) -> Optional[GameConnection]:
        return self._conn

    def _transition(self, new_state: SessionState):
        old = self.state
        self.state = new_state
        logger.info(f"[{self.account.profile_name}] {old.value} → {new_state.value}")
        if self.on_state_change:
            try:
                self.on_state_change(old, new_state)
            except Exception:
                pass

    async def run(self):
        """Main session loop with auto-reconnect."""
        while True:
            try:
                success = await self._connect_and_run()
                if not success:
                    self._consecutive_failures += 1
                    backoff = min(
                        RECONNECT_BACKOFF_BASE * (2 ** self._consecutive_failures),
                        RECONNECT_BACKOFF_MAX,
                    )
                    jitter = backoff * 0.3 * (2 * (asyncio.get_event_loop().time() % 1) - 1)
                    wait = max(backoff + jitter, 1.0)
                    self._transition(SessionState.RECONNECTING)
                    pname = self.account.profile_name
                    logger.info(f"[{pname}] Reconnect in {wait:.1f}s (fail #{self._consecutive_failures})")
                    await asyncio.sleep(wait)
                else:
                    break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.account.profile_name}] Session error: {e}")
                self._consecutive_failures += 1
                await asyncio.sleep(10)

    async def _connect_and_run(self) -> bool:
        # Phase 1: Token refresh
        self._transition(SessionState.AUTHENTICATING)
        if not await self._ensure_token():
            self._transition(SessionState.FAILED)
            return False

        # Phase 2: TCP connect
        self._transition(SessionState.CONNECTING)
        host, port = self.account.server_addr()
        proxy_url = None
        if self.account.has_proxy:
            from .proxy import ProxyConfig
            proxy = ProxyConfig(
                host=self.account.proxy_host,
                port=self.account.proxy_port,
                proxy_type=self.account.proxy_type,
                username=self.account.proxy_user,
                password=self.account.proxy_pass,
            )
            proxy_url = proxy.to_aiohttp_proxy()

        self._conn = GameConnection(
            host=host, port=port, proxy_url=proxy_url,
            account_id=self.account.profile_name,
        )
        self._conn.register_handler(self._on_frame)

        if not await self._conn.connect():
            return False

        # Phase 3: Greeting
        self._transition(SessionState.HANDSHAKING)
        greeting = await self._conn.receive_greeting()
        if not greeting:
            return False

        # Phase 4: Login (role-bound when app_uid + role + device known)
        self._transition(SessionState.LOGGING_IN)
        pid = self.account.effective_player_id
        token = self.account.effective_token
        host, port = self.account.server_addr()
        server_str = f"{host}:{port}"
        if not await self._conn.send_login(
            pid, token, server=server_str,
            app_uid=self.account.app_uid, device_udid=self.account.device_udid,
        ):
            return False

        # Phase 5: Wait for initial data
        initial_frames = await self._conn.wait_for_initial_data(timeout=3.0)
        logger.info(f"[{self.account.profile_name}] Got {len(initial_frames)} initial frames")

        if not initial_frames:
            logger.warning(f"[{self.account.profile_name}] No initial data — session may be stale")

        # Phase 5b: Role/profile request FIRST.
        # Live order (live_switch_clean.pcap, real client): 104 lands early
        # (#9, right after 8045). 161/203/110 come mid-burst (see below).
        from .commands import build_profile_request, build_role_request
        for op, pay in (build_role_request(), build_profile_request()):
            await self._conn.send_command(op, pay)
            await asyncio.sleep(PacketJitter.inter_frame_delay())
        role_frames = await self._conn.wait_for_initial_data(timeout=2.0)
        logger.info(f"[{self.account.profile_name}] Got {len(role_frames)} role frames")

        # Phase 6: Init sequence
        self._transition(SessionState.INITIALIZING)
        await self._send_init_sequence()

        # Phase 7: Active session
        self._transition(SessionState.ACTIVE)
        self._consecutive_failures = 0
        self._conn.start_receiving()

        # Keep alive until disconnected
        try:
            while self.is_active and self._conn and self._conn.is_connected:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

        # Phase 8: Graceful disconnect
        await self._graceful_disconnect()
        return True

    async def _ensure_token(self) -> bool:
        # If we have app_token + app_uid, try refresh first (type=0 + app_token)
        if self.account.app_token and self.account.app_uid:
            try:
                result = await self.auth.refresh_token(
                    self.account.app_token,
                    self.account.app_uid,
                    self.account.profile_name,
                )
                self.account.app_token = result.get("app_token", self.account.app_token)
                self.account.access_token = result.get("access_token", self.account.app_token)
                self.account.app_uid = result.get("app_uid", self.account.app_uid)
                # NEVER overwrite an explicitly configured role id: player_id
                # is the CHARACTER (role), app_uid is the ACCOUNT. A past bug
                # here clobbered role 227658377 with the app_uid and the bot
                # silently played the wrong character. Only fill when empty.
                if result.get("app_uid") and not self.account.player_id:
                    self.account.player_id = result["app_uid"]
                logger.info(f"[{self.account.profile_name}] Token refreshed OK uid={self.account.app_uid}")
                return True
            except Exception as e:
                logger.warning(f"[{self.account.profile_name}] Token refresh failed: {e} — using cached token")
                # Fall through to use cached token
                return True

        # If we have access_token (from previous session), try using it
        if self.account.access_token:
            return True

        # Last resort: email+password login (may fail for PUP passport accounts)
        if self.account.email and self.account.password:
            try:
                result = await self.auth.email_login(
                    self.account.email,
                    self.account.password,
                    self.account.profile_name,
                )
                self.account.access_token = result.get("access_token", "")
                self.account.app_token = result.get("app_token", "")
                self.account.app_uid = result.get("app_uid", "")
                return True
            except Exception as e:
                logger.error(f"[{self.account.profile_name}] Email login failed: {e}")
                return False
        logger.error(f"[{self.account.profile_name}] No credentials available")
        return False

    async def _send_init_sequence(self):
        if not self._conn or not self._conn.is_connected:
            return
        from .commands import build_time_sync_role
        try:
            role_id = int(self.account.effective_player_id)
        except ValueError:
            role_id = 0
        logger.info(f"[{self.account.profile_name}] Sending init sequence ({len(INIT_SEQUENCE)} commands)")
        for msg_id, payload in INIT_SEQUENCE:
            # Never send another role's id: the template's 1202 carries a
            # stale foreign role and 6404 a stale kingdom — both wedged live
            # sessions (world data withheld). Patch with ours at runtime.
            if msg_id == 1202 and role_id:
                _, payload = build_time_sync_role(role_id)
            elif msg_id == 6404 and self.account.kingdom_id:
                from .protobuf import encode_message
                payload = encode_message({1: int(self.account.kingdom_id)})
            await self._conn.send_command(msg_id, payload)
            await asyncio.sleep(PacketJitter.inter_frame_delay())

        # Post-init handshake in LIVE client order (live_switch_clean.pcap):
        #   161 -> 1001 -> 1004 -> 5501 -> 8035 -> 1202 -> 203 -> ... -> 110.
        # The 203+110 pair is the character switch. Op 203 carries {1:role};
        # Op 110 carries {1:role, 2:kingdom_id, 3:role} where kingdom is
        # PER-ROLE (AmmAr 11543, ssar3 3105). A wrong f2 yields Op 1
        # {110, 246} and wedges the session — never guess it (see below).
        # Op 204 does NOT exist on the wire (not even in the live capture);
        # the confirming signal for a switch is a NEW incoming Op 15.
        from .commands import (
            build_army_panel,
            build_client_state,
            build_map_init,
            build_player_query,
            build_role_switch,
            build_second_auth,
            build_session_flag,
            build_time_sync_role,
        )
        try:
            role_id = int(self.account.effective_player_id)
        except ValueError:
            role_id = 0
        city_x, city_y = 2822.8, 4269.1  # TODO: per-account city from Op 15/302
        post_init = []
        if self.account.device_udid and self.account.app_uid:
            post_init.append(build_second_auth(
                app_uid=self.account.app_uid,
                access_token=self.account.effective_token,
                device_token=self.account.device_udid,
            ))
        post_init += [
            build_map_init(),
            build_army_panel(city_x, city_y),
            build_session_flag(),
            build_client_state(role_id, "FTE_STATE"),
            build_time_sync_role(role_id),
            build_role_switch(role_id),
        ]
        if self.account.kingdom_id:
            post_init.append(build_player_query(role_id, self.account.kingdom_id))
        else:
            # A guessed kingdom wedges the session (Op 1 {110, 246}), so a
            # missing kingdom means NO 110 rather than a wrong one.
            logger.warning(
                f"[{self.account.profile_name}] kingdom_id unknown — "
                f"skipping Op 110 (set kingdom_id to enable role switch)"
            )
        for op, pay in post_init:
            await self._conn.send_command(op, pay)
            await asyncio.sleep(PacketJitter.inter_frame_delay())
        switch_frames = await self._conn.wait_for_initial_data(timeout=3.0)
        logger.info(f"[{self.account.profile_name}] Got {len(switch_frames)} switch frames")

    async def _graceful_disconnect(self):
        self._transition(SessionState.DISCONNECTING)
        if self._conn:
            logger.info(f"[{self.account.profile_name}] Graceful disconnect — sending cleanup frames")

            try:
                for msg_id in [2003, 8045, 8030]:
                    await self._conn.send_command(msg_id)
                    await asyncio.sleep(0.05)
            except Exception:
                pass

            await self._conn.disconnect()

    async def _on_frame(self, frame: Frame):
        if self.on_frame:
            try:
                result = self.on_frame(frame)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    def stats(self) -> dict:
        base = {
            "account": self.account.profile_name,
            "state": self.state.value,
            "failures": self._consecutive_failures,
        }
        if self._conn:
            base.update(self._conn.stats())
        return base
