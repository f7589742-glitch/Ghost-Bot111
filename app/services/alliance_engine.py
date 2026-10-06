"""
alliance_engine.py - Alliance Automations for Rise of Kingdoms Headless Bot.
Reversed and ground-truth verified from live packet capture decoded_20260916_224225.txt.

Telemetry References:
- Line 166: C->S#160 ops=[5501] len=7 p2=0801 (Help all alliance members)
- Line 231: C->S#225 ops=[3370] len=7 p2=0801 (Claim territory production / resource pit)
- Line 597: C->S#591 ops=[2045] len=7 p2=1800 (Alliance tech donation)
- Line 322: C->S#316 ops=[3170] len=9 (Claim alliance gifts)
- Line 324: C->S#318 ops=[3132] len=9 (Claim alliance chest)
"""

import sys
import os
import time
import logging
from typing import Optional, Dict, Any, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

PYTHON_DIR = os.path.join(PROJECT_ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

try:
    from headless_client import ProtobufCodec
except ImportError:
    from python.headless_client import ProtobufCodec

logger = logging.getLogger("alliance_engine")

OP_HELP_ALL = 5501               # C->S: Click "Help All" for alliance
OP_CLAIM_TERRITORY = 3370        # C->S: Claim territory resource pit
OP_TECH_DONATION = 2045          # C->S: Donate to recommended tech
OP_CLAIM_GIFTS = 3170            # C->S: Claim alliance gifts
OP_CLAIM_GIFT_CHEST = 3132       # C->S: Claim all alliance gift chests


class AllianceEngine:
    """
    Handles alliance automations: Help all, claim territory pit,
    tech donations, and gift chest harvesting.
    """

    @staticmethod
    def build_help_all_payload() -> bytes:
        """
        Opcode 5501: 0801 (field 1 = 1)
        """
        return ProtobufCodec.encode_message({1: 1})

    @staticmethod
    def build_claim_territory_payload() -> bytes:
        """
        Opcode 3370: 0801 (field 1 = 1)
        """
        return ProtobufCodec.encode_message({1: 1})

    @staticmethod
    def build_tech_donation_payload(tech_id: int = 0) -> bytes:
        """
        Opcode 2045: 1800 (field 3 = 0, donate default recommended tech)
        """
        msg = {3: int(tech_id)}
        return ProtobufCodec.encode_message(msg)

    @staticmethod
    def build_claim_gifts_payload() -> bytes:
        """
        Opcode 3170 / 3132: claim all gifts
        """
        return ProtobufCodec.encode_message({1: 1})

    @staticmethod
    def run_alliance_sweep(
        client,
        help_members: bool = True,
        claim_pit: bool = True,
        donate_tech: bool = True,
        claim_gifts: bool = True
    ) -> Dict[str, bool]:
        """
        Executes a complete alliance sweep with humanized jitter.
        """
        results = {}

        if help_members:
            try:
                client.send_packet(OP_HELP_ALL, AllianceEngine.build_help_all_payload())
                logger.info("[ALLIANCE] Dispatched 'Help All' (Opcode 5501)")
                results["help_members"] = True
            except Exception as e:
                logger.warning(f"[ALLIANCE] Help all failed: {e}")
                results["help_members"] = False
            time.sleep(1.2)

        if claim_pit:
            try:
                client.send_packet(OP_CLAIM_TERRITORY, AllianceEngine.build_claim_territory_payload())
                logger.info("[ALLIANCE] Claimed alliance territory resource pit (Opcode 3370)")
                results["claim_pit"] = True
            except Exception as e:
                logger.warning(f"[ALLIANCE] Claim territory pit failed: {e}")
                results["claim_pit"] = False
            time.sleep(1.2)

        if donate_tech:
            try:
                # Up to 3 donations per sweep if stars available
                for _ in range(3):
                    client.send_packet(OP_TECH_DONATION, AllianceEngine.build_tech_donation_payload())
                    time.sleep(0.8)
                logger.info("[ALLIANCE] Completed alliance tech donations (Opcode 2045)")
                results["donate_tech"] = True
            except Exception as e:
                logger.warning(f"[ALLIANCE] Tech donation failed: {e}")
                results["donate_tech"] = False
            time.sleep(1.2)

        if claim_gifts:
            try:
                client.send_packet(OP_CLAIM_GIFTS, AllianceEngine.build_claim_gifts_payload())
                time.sleep(0.6)
                client.send_packet(OP_CLAIM_GIFT_CHEST, AllianceEngine.build_claim_gifts_payload())
                logger.info("[ALLIANCE] Claimed alliance gifts and chest (Opcode 3170/3132)")
                results["claim_gifts"] = True
            except Exception as e:
                logger.warning(f"[ALLIANCE] Claim gifts failed: {e}")
                results["claim_gifts"] = False

        return results
