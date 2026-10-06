"""
Orchestrator — manage 200+ concurrent headless bots.

Uses asyncio.Semaphore to limit concurrency and provides centralized
monitoring, rate limiting, and lifecycle management for all bots.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import Dict, List, Optional

from .account import AccountManager
from .auth import AuthManager
from .bot import Bot
from .commands import CommandLibrary
from .config import MAX_CONCURRENT_BOTS, AccountConfig
from .fingerprint import FingerprintGenerator
from .proxy import ProxyManager

logger = logging.getLogger("rokbot.orchestrator")


class Orchestrator:
    """
    Central orchestrator for 200+ concurrent headless bots.

    Features:
      - Concurrent bot management with configurable limits
      - Centralized proxy assignment
      - Per-account fingerprint generation
      - Graceful shutdown on SIGINT/SIGTERM
      - Aggregate statistics and monitoring
    """

    def __init__(
        self,
        max_concurrent: int = MAX_CONCURRENT_BOTS,
        proxy_file: Optional[str] = None,
    ):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

        self.account_mgr = AccountManager()
        self.fingerprint_gen = FingerprintGenerator()
        self.proxy_mgr = ProxyManager()
        self.auth_mgr = AuthManager(self.fingerprint_gen)
        self.command_lib = CommandLibrary()

        self._bots: Dict[str, Bot] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._running = False
        self._start_time: float = 0

        if proxy_file:
            self.proxy_mgr.add_proxies_from_file(proxy_file)

    async def start_accounts(
        self,
        account_names: Optional[List[str]] = None,
    ):
        """Start bots for specified accounts (or all if None)."""
        all_accounts = self.account_mgr.load_all()

        if account_names:
            accounts = [a for a in all_accounts if a.profile_name in account_names]
        else:
            accounts = all_accounts

        if not accounts:
            logger.warning("No accounts to start")
            return

        logger.info(f"Starting {len(accounts)} bots (max concurrent: {self.max_concurrent})")
        self._running = True
        self._start_time = time.time()

        for account in accounts:
            await self._launch_bot(account)

        logger.info(f"All {len(self._tasks)} bot tasks launched")

    async def _launch_bot(self, account: AccountConfig):
        bot = Bot(
            account=account,
            auth_manager=self.auth_mgr,
            fingerprint_gen=self.fingerprint_gen,
            command_library=self.command_lib,
            proxy_manager=self.proxy_mgr,
        )
        self._bots[account.profile_name] = bot

        task = asyncio.create_task(
            self._run_bot_with_semaphore(bot),
            name=f"bot_{account.profile_name}",
        )
        self._tasks[account.profile_name] = task
        task.add_done_callback(
            lambda t, name=account.profile_name: self._on_task_done(name, t)
        )

    async def _run_bot_with_semaphore(self, bot: Bot):
        async with self._semaphore:
            await bot.start()

    def _on_task_done(self, name: str, task: asyncio.Task):
        if task.cancelled():
            return
        if task.exception():
            logger.error(f"[{name}] Bot crashed: {task.exception()}")
        else:
            logger.info(f"[{name}] Bot finished")
        self._tasks.pop(name, None)
        self._bots.pop(name, None)

    async def stop_all(self):
        logger.info("Stopping all bots ...")
        self._running = False
        for name, bot in list(self._bots.items()):
            try:
                await bot.stop()
            except Exception as e:
                logger.error(f"[{name}] Stop error: {e}")

        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

        await self.auth_mgr.close()
        logger.info("All bots stopped")

    async def wait_all(self):
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    def get_global_stats(self) -> dict:
        uptime = time.time() - self._start_time if self._start_time else 0
        total_rx = sum(b.stats["total_frames_rx"] for b in self._bots.values())
        total_tx = sum(b.stats["total_frames_tx"] for b in self._bots.values())
        active = sum(1 for b in self._bots.values() if b.is_active)

        return {
            "uptime_s": round(uptime, 1),
            "total_bots": len(self._bots),
            "active_bots": active,
            "total_frames_rx": total_rx,
            "total_frames_tx": total_tx,
            "proxy_stats": self.proxy_mgr.stats(),
            "command_stats": self.command_lib.stats(),
        }

    def print_status(self):
        stats = self.get_global_stats()
        print(f"\n{'=' * 60}")
        print(f"  RoK Bot Orchestrator — {stats['active_bots']}/{stats['total_bots']} active")
        print(f"  Uptime: {stats['uptime_s']:.0f}s | RX: {stats['total_frames_rx']} | TX: {stats['total_frames_tx']}")
        print(f"  Proxies: {stats['proxy_stats']}")
        print(f"{'=' * 60}")

        for name, bot in self._bots.items():
            s = bot.get_stats()
            session = s.get("session", {})
            state = session.get("state", s.get("state", "unknown"))
            rx = session.get("frames_rx", s.get("total_frames_rx", 0))
            print(f"  [{state:>15}] {name:<25} RX={rx}")
        print()


async def run_orchestrator(
    account_names: Optional[List[str]] = None,
    proxy_file: Optional[str] = None,
    max_concurrent: int = MAX_CONCURRENT_BOTS,
    status_interval: float = 30.0,
):
    """
    High-level entry point to run the orchestrator.

    Installs signal handlers for graceful shutdown and prints periodic status.
    """
    orch = Orchestrator(max_concurrent=max_concurrent, proxy_file=proxy_file)

    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    try:
        await orch.start_accounts(account_names)

        async def _status_loop():
            while not shutdown_event.is_set():
                await asyncio.sleep(status_interval)
                orch.print_status()

        status_task = asyncio.create_task(_status_loop())

        await shutdown_event.wait()
        status_task.cancel()

    finally:
        await orch.stop_all()
