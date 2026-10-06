"""
continuous_auto_gather_daemon.py - Persistent Auto-Gather Daemon
Powered by commercial-grade smart_gather_search.py engine.
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from smart_gather_search import execute_smart_gather

async def persistent_gather_bot():
    print("=" * 65)
    print("  HEADLESS AUTO-GATHER - PERSISTENT 3-MARCH ENGINE")
    print("=" * 65)

    targets = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1].strip() else ["food", "wood", "stone"]
    level = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0

    while True:
        try:
            print(f"\n[DAEMON] Running Smart Multi-Gather Round (Targets: {targets})...")
            await execute_smart_gather(march_targets=targets, target_level=level)
        except Exception as e:
            print(f"[DAEMON] Error during gather round: {e}")

        print("[DAEMON] Round complete. Standing by 120s before checking queue availability...")
        await asyncio.sleep(120)

if __name__ == "__main__":
    asyncio.run(persistent_gather_bot())
