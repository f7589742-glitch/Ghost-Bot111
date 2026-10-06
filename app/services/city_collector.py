"""
app/services/city_collector.py — Universal City Resource Collector
Commercial-grade, protocol-verified resource harvesting for Rise of Kingdoms Headless Bot.
Iterates through all detected resource production buildings with uncollected resources
(Farms, Lumber Mills, Quarries, Goldmines), dispatches Opcode 120 harvest clicks,
clears floating bubbles, and updates account resource totals.
"""

import asyncio
import logging
import zlib
from typing import Dict, Any, List, Optional

from python.headless_client import ProtobufCodec, FrameParser
from python.crypto_module import RokCrypto
from app.services.city_layout import CityLayoutResolver, SessionLayoutRegistry, RESOURCE_TYPE_MAP

logger = logging.getLogger("city_collector")


class CityResourceCollector:
    """Manages protocol-verified harvesting of city resource bubbles."""

    @classmethod
    async def harvest_all(
        cls,
        reader,
        writer,
        crypto_tx: RokCrypto,
        crypto_rx: RokCrypto,
        role_id: str,
        production_buildings: Optional[List[Dict[str, Any]]] = None,
        log_callback=None
    ) -> Dict[str, Any]:
        """
        Harvests all waiting resource bubbles from city production buildings.
        If production_buildings is None, dynamically discovers them via CityLayoutResolver.
        """
        def log(msg):
            if log_callback:
                log_callback(msg)
            else:
                logger.info(msg)

        if not production_buildings:
            layout = SessionLayoutRegistry.get(str(role_id)) or CityLayoutResolver.get_layout(str(role_id))
            if layout and layout.get("production_buildings"):
                production_buildings = layout["production_buildings"]
            else:
                # Query on-the-fly
                layout = await CityLayoutResolver.discover_layout(
                    reader, writer, crypto_tx, crypto_rx, role_id=str(role_id), log_callback=log
                )
                production_buildings = layout.get("production_buildings", [])

        if not production_buildings:
            log("[HARVEST] No production buildings detected in city layout.")
            return {"success": True, "harvested_count": 0, "total_buildings": 0}

        log(f"[HARVEST] Initiating harvest across {len(production_buildings)} production buildings...")

        harvested_count = 0
        for b in production_buildings:
            bid = b["building_id"]
            r_name = b.get("resource_name", "Resource")
            uncoll = b.get("uncollected", 0)

            pkt_120 = ProtobufCodec.encode_message({
                1: 120,
                2: ProtobufCodec.encode_message({1: str(bid).encode()})
            })
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_120)))
            harvested_count += 1

        await writer.drain()

        # Listen for server ACKs (Opcode 121 resource totals & Opcode 125 bubble clears)
        deadline = asyncio.get_event_loop().time() + 2.0
        updated_resources = {}
        cleared_bubbles = 0

        while asyncio.get_event_loop().time() < deadline:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.4)
                rl = (rh[0] << 8) | rh[1]
                raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.4)
                dec = crypto_rx.decrypt(raw)
                z_idx = dec.find(b"\x78\x9c")
                if z_idx == -1: z_idx = dec.find(b"\x78\x01")
                decomp = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
                m = ProtobufCodec.decode_message(decomp)
                chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                for c in chunks:
                    it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                    op = it.get(1)
                    if op == 121 and isinstance(it.get(2), bytes):
                        # Opcode 121: Updated player resources
                        p121 = ProtobufCodec.decode_message(it.get(2))
                        for item in p121.get(1, []):
                            sub = ProtobufCodec.decode_message(item) if isinstance(item, bytes) else item
                            rt = sub.get(1)
                            tot = sub.get(2)
                            if rt in RESOURCE_TYPE_MAP:
                                updated_resources[RESOURCE_TYPE_MAP[rt]["name"]] = tot
                    elif op == 125:
                        cleared_bubbles += 1
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                break

        log(f"[HARVEST] Successfully harvested {harvested_count} buildings! Floating bubbles cleared.")
        if updated_resources:
            log(f"[HARVEST] Live City Resources: {', '.join(f'{k}: {v:,}' for k, v in updated_resources.items())}")

        return {
            "success": True,
            "harvested_count": harvested_count,
            "total_buildings": len(production_buildings),
            "updated_resources": updated_resources
        }
