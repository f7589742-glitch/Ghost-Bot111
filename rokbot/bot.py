"""
Bot — single-account autonomous bot with farming logic.

Wraps Session with high-level farming behaviors:
  - Connect and authenticate
  - Send init sequence
  - Real-time S2C parsing (Decoder + GameState)
  - Execute resource discovery (Op 1176)
  - Dispatch gathering marches (Op 1050 + Op 1012)
  - Manage troop training with slot timers (Op 300 / Op 102)
  - Request alliance help & collect rewards
  - Human-like behavior simulation & auto-reconnect
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .auth import AuthManager
from .commands import (
    BARRACKS_ARCHERY,
    BARRACKS_CAVALRY,
    BARRACKS_INFANTRY,
    BARRACKS_SIEGE,
    CommandLibrary,
    build_auto_gather,
    build_collect_troops,
    build_discover_barracks,
    build_discover_nodes,
    build_gather_march,
    build_gather_preflight_ack,
    build_train_troops,
)
from .config import AccountConfig
from .decoder import GameState, PacketDecoder, ResourceNode
from .fingerprint import FingerprintGenerator
from .protocol import Frame
from .proxy import ProxyManager
from .session import Session, SessionState

logger = logging.getLogger("rokbot.bot")


class Bot:
    """
    Autonomous headless bot for a single RoK account.

    Manages the full lifecycle: auth → connect → init → decode → farm → reconnect.
    """

    def __init__(
        self,
        account: AccountConfig,
        auth_manager: AuthManager,
        fingerprint_gen: FingerprintGenerator,
        command_library: CommandLibrary,
        proxy_manager: Optional[ProxyManager] = None,
    ):
        self.account = account
        self.auth = auth_manager
        self.fingerprints = fingerprint_gen
        self.commands = command_library
        self.proxy_manager = proxy_manager

        self.game_state = GameState(player_id=self.account.effective_player_id)
        # Seed the bound role id from the profile: role-bound logins attach
        # the session to this role, and S2C Op 15 may arrive late or never.
        try:
            self.game_state.active_role_id = int(self.account.effective_player_id)
        except (TypeError, ValueError):
            pass
        self.decoder = PacketDecoder(self.game_state)

        self._session: Optional[Session] = None
        self._running = False
        self._frame_log: List[Dict] = []
        self._on_frame_callback: Optional[Callable] = None

        self.stats = {
            "total_frames_rx": 0,
            "total_frames_tx": 0,
            "total_reconnects": 0,
            "gather_marches_sent": 0,
            "troops_trained": 0,
            "nodes_discovered": 0,
            "started_at": 0.0,
        }

    @property
    def is_active(self) -> bool:
        return self._session is not None and self._session.is_active

    def set_frame_callback(self, callback: Callable):
        self._on_frame_callback = callback

    async def start(self):
        """Start the bot's main loop."""
        self._running = True
        self.stats["started_at"] = time.time()

        if self.account.has_proxy and self.proxy_manager:
            self.proxy_manager.assign(self.account.profile_name)

        logger.info(f"[{self.account.profile_name}] Bot starting")

        self._session = Session(
            account=self.account,
            auth_manager=self.auth,
            on_frame=self._handle_frame,
            on_state_change=self._handle_state_change,
        )

        # Run session and autonomous farming loop concurrently
        session_task = asyncio.create_task(self._session.run())
        farming_task = asyncio.create_task(self._farming_loop())

        try:
            await session_task
        finally:
            farming_task.cancel()
            try:
                await farming_task
            except asyncio.CancelledError:
                pass

    async def stop(self):
        self._running = False
        if self._session:
            await self._session._graceful_disconnect()

        if self.proxy_manager:
            self.proxy_manager.release(self.account.profile_name)

        logger.info(f"[{self.account.profile_name}] Bot stopped")

    def _handle_frame(self, frame: Frame):
        self.stats["total_frames_rx"] += 1

        # Real-time decoding and state update
        parsed = self.decoder.decode_frame(frame.payload)
        op = parsed.get("opcode", 0)

        if "nodes_discovered" in parsed:
            self.stats["nodes_discovered"] = len(self.game_state.resource_nodes)
            logger.info(
                f"[{self.account.profile_name}] Discovered {parsed['nodes_discovered']} nodes "
                f"(total: {len(self.game_state.resource_nodes)})"
            )

        log_entry = {
            "ts": time.time(),
            "op": op,
            "len": frame.length,
            "type": parsed.get("type", "unknown"),
        }
        self._frame_log.append(log_entry)

        if len(self._frame_log) > 5000:
            self._frame_log = self._frame_log[-2500:]

        if self._on_frame_callback:
            try:
                self._on_frame_callback(frame, parsed)
            except Exception:
                pass

    def _handle_state_change(self, old: SessionState, new: SessionState):
        if new == SessionState.RECONNECTING:
            self.stats["total_reconnects"] += 1
        if new == SessionState.ACTIVE:
            try:
                from .account import AccountManager
                mgr = AccountManager()
                mgr.save(self.account)
            except Exception as e:
                logger.debug(f"[{self.account.profile_name}] Token save skip: {e}")

    # ──────────────────────────────────────────────────────────────────
    # Intelligent Autonomous Farming Engine
    # ──────────────────────────────────────────────────────────────────

    async def _farming_loop(self):
        """High-level autonomous farming cycle with humanized pacing."""
        try:
            # Initial stabilization wait after connect
            await asyncio.sleep(4.0)

            while self._running:
                if not self.is_active:
                    await asyncio.sleep(2.0)
                    continue

                try:
                    await self.execute_farming_cycle()
                except Exception as e:
                    logger.warning(f"[{self.account.profile_name}] Farming cycle error: {e}")

                behavior = getattr(self._session, "_behavior", None)
                delay = behavior.next_delay() if behavior else 8.0
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass

    async def execute_farming_cycle(self):
        """Full multi-step autonomous farming iteration."""
        if not self._session or not self._session.is_active:
            return

        # 1. Social & Alliance Assistance (every cycle if needed)
        await self.execute_social_actions()

        # 2. Resource Node Discovery
        if len(self.game_state.resource_nodes) < 3:
            await self.execute_discovery()
            await asyncio.sleep(2.0)

        # 3. Dispatch Gathering Marches
        await self.execute_gathering()

        # 4. Manage Troop Training (Op 302 state + Op 303 collect + Op 300 train)
        if not self.game_state.barracks:
            await self.execute_barracks_discovery()
            await asyncio.sleep(1.0)
        await self.execute_training()

        # 5. Query Resource Info & Stats
        await self.execute_resource_query()

    async def execute_discovery(self) -> bool:
        """Trigger map resource node discovery (Opcode 1176)."""
        if not self.is_active:
            return False
        op, payload = build_discover_nodes()
        await self._session.conn.send_command(op, payload)
        logger.debug(f"[{self.account.profile_name}] Sent resource discovery (op=1176)")
        self.stats["total_frames_tx"] += 1
        return True

    async def execute_gathering(self, army: Optional[List[Tuple[int, int]]] = None) -> bool:
        """
        Dispatch gathering march with the live-client sequence:
          Op 1050 (preflight with city/node fixed32) -> Op 9726 (empty ACK)
          -> Op 1012 (dispatch with f18=0).
        Verified in authentic_march_packet.json.
        """
        if not self.is_active:
            return False

        # Check if we have available nodes
        available_nodes = [
            node for node in self.game_state.resource_nodes.values()
            if not node.occupied
        ]
        if not available_nodes:
            logger.debug(f"[{self.account.profile_name}] No unoccupied nodes available to gather")
            return False

        target_node = available_nodes[0]
        city_pos = self.game_state.city_pos
        node_pos = (target_node.x, target_node.y)
        # f1 of Op 1050 is chief/alliance id in live captures (e.g. 293935803).
        # Prefer live role id when known; TODO: capture exact chief_id per account.
        try:
            chief_id = int(self.game_state.active_role_id or 0)
        except Exception:
            chief_id = 0

        # Step 1: Send auto-gather click (Op 1050)
        op_1050, payload_1050 = build_auto_gather(
            alliance_id=chief_id,
            node_id=target_node.node_id,
            city_pos=city_pos,
            node_pos=node_pos,
        )
        await self._session.conn.send_command(op_1050, payload_1050)
        self.stats["total_frames_tx"] += 1
        await asyncio.sleep(0.4)

        # Step 1b: Preflight ACK (Op 9726, empty) — live client sends this
        op_ack, payload_ack = build_gather_preflight_ack()
        await self._session.conn.send_command(op_ack, payload_ack)
        self.stats["total_frames_tx"] += 1
        await asyncio.sleep(0.6)

        # Step 2: Dispatch march (Op 1012)
        op_1012, payload_1012 = build_gather_march(
            node_id=target_node.node_id,
            army=army or [(1020, 1), (500, 3)],
        )
        await self._session.conn.send_command(op_1012, payload_1012)
        self.stats["total_frames_tx"] += 1
        self.stats["gather_marches_sent"] += 1
        target_node.occupied = True

        logger.info(
            f"[{self.account.profile_name}] Dispatched gather march to node {target_node.node_id} "
            f"at ({target_node.x}, {target_node.y})"
        )
        return True

    async def execute_training(self, count: int = 100) -> bool:
        """
        Manage troop training using verified Op 302 state when available.
        Flow per smart_troop_trainer.py: collect finished (Op 303) -> train (Op 300).
        Falls back to legacy numeric busy map when Op 302 has not arrived yet.
        """
        if not self.is_active:
            return False

        now = time.time()
        barracks_order = [BARRACKS_INFANTRY, BARRACKS_CAVALRY, BARRACKS_ARCHERY, BARRACKS_SIEGE]

        # Preferred path: live Op 302 barracks state
        if self.game_state.barracks:
            for b in barracks_order:
                cat = {1: "infantry", 2: "cavalry", 3: "archery", 4: "siege"}[b["unit_type"]]
                live = self.game_state.barracks.get(cat)
                if live and live.is_busy:
                    continue
                bid = live.building_id if live and live.building_id else b["building_id"]
                utype = live.unit_type if live and live.unit_type else b["unit_type"]
                # Collect finished troops first (Op 303) when server says so
                if live and live.needs_collect:
                    op_c, pay_c = build_collect_troops(bid, utype)
                    await self._session.conn.send_command(op_c, pay_c)
                    self.stats["total_frames_tx"] += 1
                    await asyncio.sleep(0.4)
                op, payload = build_train_troops(building_id=bid, unit_type=utype, count=count)
                await self._session.conn.send_command(op, payload)
                self.stats["total_frames_tx"] += 1
                self.stats["troops_trained"] += 1
                self.game_state.building_busy_until[utype] = now + 120.0
                logger.info(f"[{self.account.profile_name}] Started training {cat} (bldg={bid}, type={utype})")
                await asyncio.sleep(1.5)
                return True
            return False

        # Fallback: numeric slots 1-4 with verified building IDs
        for b in barracks_order:
            utype = b["unit_type"]
            busy_until = self.game_state.building_busy_until.get(utype, 0)
            if now >= busy_until:
                op, payload = build_train_troops(building_id=b["building_id"], unit_type=utype, count=count)
                await self._session.conn.send_command(op, payload)
                self.stats["total_frames_tx"] += 1
                self.stats["troops_trained"] += 1
                self.game_state.building_busy_until[utype] = now + 120.0
                logger.info(f"[{self.account.profile_name}] Started training unit_type={utype} (bldg={b['building_id']})")
                await asyncio.sleep(1.5)
                return True
        return False

    async def execute_barracks_discovery(self) -> bool:
        """Query building states (Op 123) to populate Op 302 barracks state."""
        if not self.is_active:
            return False
        bids = [BARRACKS_INFANTRY["building_id"], BARRACKS_CAVALRY["building_id"],
                BARRACKS_ARCHERY["building_id"], BARRACKS_SIEGE["building_id"]]
        op, payload = build_discover_barracks(bids)
        await self._session.conn.send_command(op, payload)
        self.stats["total_frames_tx"] += 1
        return True

    async def switch_character(self, role_id: int, kingdom_id: int) -> bool:
        """
        Attempt in-session character switch via 203 + 110 (live-proven shapes).
        Returns False ONLY on hard negative (S2C Op 1 {110, 246} reject).
        Returns True when the burst was accepted for further verification —
        confirmation itself comes from the next role-attributed push:
          - S2C Op 15 (role_info) — needs fresh/full auth, often absent;
          - S2C Op 1005 owner fields after any march dispatch (reliable:
            owner_role/owner_name reflect the TRUE active character).
        NOTE: sending 203 as the FIRST post-login frame wedges the session
        (live-proven 2026-09-10); always precede with 161 + 104/107.
        """
        import asyncio as _asyncio

        if not self.is_active:
            return False
        from .commands import (
            build_map_init,
            build_player_query,
            build_role_request,
            build_profile_request,
            build_role_switch,
            build_time_sync_role,
        )
        conn = self._session.conn
        await conn.send_command(*build_role_switch(int(role_id)))
        await _asyncio.sleep(0.3)
        if int(kingdom_id) > 0:
            await conn.send_command(*build_player_query(int(role_id), int(kingdom_id)))
        else:
            # Never guess the kingdom: a wrong Op 110 f2 wedges the session
            # (Op 1 {110, 246}). 203 alone is harmless without it.
            logger.warning(
                f"[{self.account.profile_name}] kingdom unknown — "
                f"sent 203 without 110"
            )
        await _asyncio.sleep(0.5)
        for op, pay in (build_role_request(), build_profile_request(),
                        build_time_sync_role(int(role_id)), build_map_init()):
            await conn.send_command(op, pay)
            await _asyncio.sleep(0.05)
        await _asyncio.sleep(3.0)
        ack = self.game_state.last_command_acks.get(110)
        if ack is not None and ack[0] == 246:
            logger.warning(
                f"[{self.account.profile_name}] Switch to {role_id} rejected "
                f"(op110 code 246 — wrong kingdom?)"
            )
            return False
        if self.game_state.active_role_id == int(role_id):
            logger.info(
                f"[{self.account.profile_name}] Switch confirmed: role {role_id}"
            )
            return True
        logger.info(
            f"[{self.account.profile_name}] Switch burst sent for {role_id}; "
            f"pending gather-attribution confirm"
        )
        return True

    async def execute_social_actions(self):
        """Execute alliance help and speedups."""
        if not self.is_active:
            return
        cmd_help = self.commands.get("alliance_help")
        if cmd_help:
            await self._session.conn.send_command(cmd_help.msg_id, cmd_help.payload_bytes)
            self.stats["total_frames_tx"] += 1

    async def execute_resource_query(self):
        """Query player resources."""
        if not self.is_active:
            return
        await self._session.conn.send_command(120, b"")
        self.stats["total_frames_tx"] += 1

    def get_stats(self) -> dict:
        base = dict(self.stats)
        if self._session:
            base["session"] = self._session.stats()
        base["uptime_s"] = round(time.time() - self.stats["started_at"], 1) if self.stats["started_at"] else 0
        base["frame_log_size"] = len(self._frame_log)
        base["active_nodes_count"] = len(self.game_state.resource_nodes)
        base["resources"] = self.game_state.resources
        return base

