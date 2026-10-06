"""
Behavior simulation — Gaussian jitter and anti-pattern timing.

Pure static loop scripts are flagged instantly by Anti-Abuse engines
that analyze network timing distributions. This module introduces
realistic human-like variance using Gaussian distributions and
randomized action sequencing.
"""
from __future__ import annotations

import asyncio
import random
import time

import math


class BehaviorSimulator:
    """
    Generates human-like timing for packet transmissions.

    Instead of exact N-second intervals, produces timing like:
        4.87s, 5.21s, 4.93s, 5.44s, 4.78s ...

    Uses Gaussian distribution centered on the base interval with
    configurable standard deviation.
    """

    def __init__(
        self,
        base_interval: float = 5.0,
        std_dev: float = 0.35,
        min_multiplier: float = 0.7,
        max_multiplier: float = 1.4,
    ):
        self.base_interval = base_interval
        self.std_dev = std_dev
        self.min_multiplier = min_multiplier
        self.max_multiplier = max_multiplier
        self._action_history: list[float] = []

    def next_delay(self) -> float:
        """
        Return a Gaussian-distributed delay around the base interval.

        Clamped to [base * min_mult, base * max_mult] to prevent
        extreme outliers that look unnatural.
        """
        raw = random.gauss(self.base_interval, self.std_dev)
        clamped = max(
            self.base_interval * self.min_multiplier,
            min(self.base_interval * self.max_multiplier, raw),
        )
        return round(clamped, 3)

    async def sleep(self) -> float:
        """Sleep for the next jittered interval. Returns actual sleep time."""
        delay = self.next_delay()
        await asyncio.sleep(delay)
        self._action_history.append(time.monotonic())
        return delay

    def random_action_delay(self) -> float:
        """
        Short random delay between discrete actions (clicks, sends).

        Returns a delay in [0.1, 2.0] seconds with Gaussian clustering
        around 0.5s — mimicking human decision-making pauses.
        """
        raw = random.gauss(0.5, 0.3)
        return round(max(0.1, min(2.0, raw)), 3)

    async def human_pause(self):
        """Pause between discrete actions (building, clicking, etc.)."""
        delay = self.random_action_delay()
        await asyncio.sleep(delay)

    def should_perform_action(self, probability: float = 0.7) -> bool:
        """Stochastic action gate — decides whether to act this cycle."""
        return random.random() < probability

    def jittered_interval(self, base: float, jitter_pct: float = 0.15) -> float:
        """Add percentage-based jitter to any interval."""
        jitter = base * jitter_pct * (2 * random.random() - 1)
        return round(base + jitter, 3)

    def get_session_timing_profile(self) -> dict:
        """Return stats about this session's timing for monitoring."""
        if len(self._action_history) < 2:
            return {"count": len(self._action_history), "avg_interval": 0}
        intervals = [
            self._action_history[i + 1] - self._action_history[i]
            for i in range(len(self._action_history) - 1)
        ]
        return {
            "count": len(self._action_history),
            "avg_interval": round(sum(intervals) / len(intervals), 3),
            "min_interval": round(min(intervals), 3),
            "max_interval": round(max(intervals), 3),
            "std_dev": round(
                math.sqrt(
                    sum((x - sum(intervals) / len(intervals)) ** 2 for x in intervals)
                    / len(intervals)
                ),
                3,
            ),
        }


class PacketJitter:
    """
    Per-packet jitter — adds micro-variance to individual packet
    send times to defeat fine-grained timing analysis.
    """

    @staticmethod
    def micro_jitter() -> float:
        """0-50ms random micro-jitter for individual packets."""
        return random.uniform(0.0, 0.05)

    @staticmethod
    def burst_delay() -> float:
        """
        Delay after sending a burst of packets.
        Real clients pause 10-100ms between bursts.
        """
        return random.uniform(0.01, 0.10)

    @staticmethod
    def inter_frame_delay() -> float:
        """
        Delay between consecutive frames in a batch.
        Real clients send frames with 1-15ms gaps.
        """
        return random.uniform(0.001, 0.015)
