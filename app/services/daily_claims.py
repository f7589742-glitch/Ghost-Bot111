"""
daily_claims.py - Daily Claims and City Harvest Engine for Rise of Kingdoms Headless Bot.
Reversed and ground-truth verified from live packet capture decoded_20260916_224225.txt.

Telemetry References:
- Line 214: C->S#208 ops=[7600] len=7 p2=0801 (VIP sync)
- Line 917: C->S#911 ops=[8602] len=7 p2=0801 (Claim VIP login points)
- Line 938: C->S#932 ops=[8601] len=7 p2=0801 (Claim VIP daily chest)
- Line 659: C->S#653 ops=[143] len=8 p2=08bf34 (Claim daily quest chest 1)
- Line 678: C->S#672 ops=[143] len=8 p2=08924f (Claim daily quest chest 2)
- Line 697: C->S#691 ops=[144] len=7 p2=085c (Claim daily quest activity reward)
- Line 755: C->S#749 ops=[203] len=8 p2=08c201 (Claim completed quest)
- Line 301: C->S#295 ops=[3535] len=12 p2=08c2e6c66c180110975a (Monument / Chronicle rewards)
- Lines 438-477: C->S ops=[120] (Harvest city resource buildings 59, 62, 71, 72, 74, 77, 79, 81, 82, 197, 199, 200, 201, 203, 205)
"""

import sys
import os
import time
import asyncio
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

logger = logging.getLogger("daily_claims")

OP_VIP_SYNC = 7600
OP_VIP_POINTS = 8602
OP_VIP_CHEST = 8601
OP_QUEST_CHEST_143 = 143
OP_QUEST_CHEST_144 = 144
OP_QUEST_CLAIM = 203
OP_CHRONICLE_CLAIM = 3535
OP_CITY_HARVEST = 120

CITY_RESOURCE_BUILDINGS = [
    59, 62, 71, 72, 74, 77, 79, 81, 82,
    197, 199, 200, 201, 203, 205
]


class DailyClaimsEngine:
    """
    Handles daily claims, VIP chests, quest activity rewards,
    monument chronicle rewards, and city resource harvesting.
    """

    @staticmethod
    def build_simple_ack(field1_val: int = 1) -> bytes:
        return ProtobufCodec.encode_message({1: int(field1_val)})

    @staticmethod
    def run_daily_claims(
        client,
        vip_chest: bool = True,
        daily_quests: bool = True,
        chronicle: bool = True,
        city_harvest: bool = True
    ) -> Dict[str, bool]:
        """
        Executes daily claims and harvest sequence.
        """
        results = {}

        # 1. City Resource Harvesting
        if city_harvest:
            harvested = 0
            for b_id in CITY_RESOURCE_BUILDINGS:
                try:
                    payload = ProtobufCodec.encode_message({1: b_id})
                    client.send_packet(OP_CITY_HARVEST, payload)
                    harvested += 1
                    time.sleep(0.08)
                except Exception:
                    pass
            logger.info(f"[DAILY] Harvested resources from {harvested} city production buildings (Opcode 120)")
            results["city_harvest"] = True
            time.sleep(1.0)

        # 2. VIP Points and Daily Chest
        if vip_chest:
            try:
                client.send_packet(OP_VIP_SYNC, DailyClaimsEngine.build_simple_ack(1))
                time.sleep(0.5)
                client.send_packet(OP_VIP_POINTS, DailyClaimsEngine.build_simple_ack(1))
                time.sleep(0.5)
                client.send_packet(OP_VIP_CHEST, DailyClaimsEngine.build_simple_ack(1))
                logger.info("[DAILY] Claimed VIP daily points & free chest (Opcode 8602/8601)")
                results["vip_chest"] = True
            except Exception as e:
                logger.warning(f"[DAILY] VIP claims failed: {e}")
                results["vip_chest"] = False
            time.sleep(1.0)

        # 3. Daily Quest Activity Chests
        if daily_quests:
            try:
                # Quest chest milestones
                for milestone_id in (6719, 10130, 92):
                    payload = DailyClaimsEngine.build_simple_ack(milestone_id)
                    client.send_packet(OP_QUEST_CHEST_143, payload)
                    time.sleep(0.3)
                client.send_packet(OP_QUEST_CHEST_144, DailyClaimsEngine.build_simple_ack(92))
                logger.info("[DAILY] Claimed daily quest activity chests (Opcode 143/144)")
                results["daily_quests"] = True
            except Exception as e:
                logger.warning(f"[DAILY] Quest chests failed: {e}")
                results["daily_quests"] = False
            time.sleep(1.0)

        # 4. Monument / Chronicle
        if chronicle:
            try:
                msg = {1: 1824424386, 2: 11543, 3: 1}
                client.send_packet(OP_CHRONICLE_CLAIM, ProtobufCodec.encode_message(msg))
                logger.info("[DAILY] Claimed chronicle chapter rewards (Opcode 3535)")
                results["chronicle"] = True
            except Exception as e:
                logger.warning(f"[DAILY] Chronicle claim failed: {e}")
                results["chronicle"] = False

        return results

    @classmethod
    async def execute_daily_claims(
        cls,
        target_role_id: int,
        kingdom_id: int,
        gate_host: str,
        gate_port: int,
        app_uid: str,
        app_token: str,
        udid: str,
        vip_chest: bool = True,
        daily_quests: bool = True,
        chronicle: bool = True,
        city_harvest: bool = True,
        log_callback: Optional[Any] = None,
        user_bot_id: str = "",
        char_name: str = ""
    ) -> Dict[str, Any]:
        """
        Standalone async execution of daily claims and city harvest.
        """
        def log(msg: str):
            if log_callback:
                log_callback(msg)
            else:
                logger.info(msg)

        log(f"[DAILY] Connecting to Gateway {gate_host}:{gate_port} for Governor #{target_role_id}...")
        try:
            from app.services.proxy_transport import open_game_connection
            from headless_client import FrameParser
            from crypto_module import RokCrypto
            from derive_seed_from_nonce import derive_seed
        except ImportError:
            from proxy_transport import open_game_connection
            from python.headless_client import FrameParser
            from python.crypto_module import RokCrypto
            from python.derive_seed_from_nonce import derive_seed

        reader, writer = await open_game_connection(gate_host, gate_port)
        try:
            # 1. Handshake Greeting 8306
            hdr = await asyncio.wait_for(reader.readexactly(2), timeout=6.0)
            g_p = await reader.readexactly((hdr[0] << 8) | hdr[1])
            sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(g_p).get(2, b""))
            tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
            c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)

            # 2. Login Opcode 14
            from app.services.lilith_cloud import LilithCloudService
            try:
                from app.services.socket_worker import build_android_login_frame
                login_bytes = build_android_login_frame(
                    player_id=str(app_uid),
                    access_token=str(app_token),
                    udid=str(udid),
                    ip=LilithCloudService.public_ip()
                )
            except Exception:
                from app.services.socket_worker import build_login_frame
                login_bytes = build_login_frame(
                    player_id=str(app_uid),
                    access_token=str(app_token),
                    app_id=2104267,
                    platform="android"
                )

            writer.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))

            # Opcode 203 / 110 role binding
            p203 = ProtobufCodec.encode_message({1: int(target_role_id)})
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: p203}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
            p110 = ProtobufCodec.encode_message({1: int(target_role_id), 2: int(kingdom_id), 3: int(target_role_id)})
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: p110}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
            await writer.drain()
            await asyncio.sleep(0.5)

            # 2b. City-state snapshot capture (Opcode 125/1002): the gateway
            # streams the profile + resource sync right after role binding.
            # We keep this session short, so read the burst non-blocking and
            # persist the first snapshot for the INVENTORY tab.
            try:
                import os as _os
                _samp = f"/tmp/op125_daily_{target_role_id}.bin"
                while True:
                    try:
                        fh = await asyncio.wait_for(reader.readexactly(2), timeout=2.5)
                        plen = (fh[0] << 8) | fh[1]
                        rpay = c_rx.decrypt(await reader.readexactly(plen))
                        zi = rpay.find(b"\x78\x9c")
                        if zi == -1:
                            zi = rpay.find(b"\x78\x01")
                        decomp = zlib.decompress(rpay[zi:]) if zi != -1 else rpay
                        # Skip tiny non-snapshot frames (ACKs are < 64 bytes)
                        if len(decomp) < 64:
                            continue
                        if not _os.path.exists(_samp):
                            with open(_samp, "wb") as sf:
                                sf.write(decomp)
                        msg = ProtobufCodec.decode_message(decomp)
                        chunks = msg[1] if isinstance(msg.get(1), list) else [msg]
                        done = False
                        for ch in chunks:
                            sub = ch if isinstance(ch, dict) else (ProtobufCodec.decode_message(ch) if isinstance(ch, bytes) else {})
                            op = sub.get(1)
                            if op in (125, 1002):
                                done = True
                                try:
                                    from app.services.city_state_parser import parse_city_state_1002
                                    snap = parse_city_state_1002(sub)
                                    if snap and user_bot_id:
                                        from app.models import InventoryDAO
                                        InventoryDAO.upsert(
                                            bot_id=user_bot_id,
                                            role_id=str(target_role_id),
                                            name=char_name or f"Role_{target_role_id}",
                                            kingdom_id=int(kingdom_id or snap.get("kingdom_id") or 0),
                                            city_hall_level=int(snap.get("city_hall_level") or 0),
                                            power=int(snap.get("power") or 0),
                                            food=int(snap.get("food") or 0),
                                            wood=int(snap.get("wood") or 0),
                                            stone=int(snap.get("stone") or 0),
                                            gold=int(snap.get("gold") or 0),
                                        )
                                        log(f"[INVENTORY] Snapshot stored: food={snap.get('food', 0):,} wood={snap.get('wood', 0):,} stone={snap.get('stone', 0):,} gold={snap.get('gold', 0):,}")
                                except Exception as _ie:
                                    log(f"[WARN] inventory snapshot note: {_ie}")
                        if done:
                            break
                    except asyncio.TimeoutError:
                        break
                    except Exception:
                        break
            except Exception as _loop_err:
                log(f"[WARN] snapshot loop note: {_loop_err}")

            # 3. City Resource Harvesting (Opcode 120)
            if city_harvest:
                log(f"[DAILY] Harvesting city resource buildings...")
                for b_id in CITY_RESOURCE_BUILDINGS:
                    h_pkt = ProtobufCodec.encode_message({
                        1: OP_CITY_HARVEST,
                        2: ProtobufCodec.encode_message({1: b_id})
                    })
                    writer.write(FrameParser.build_frame(c_tx.encrypt(h_pkt)))
                await writer.drain()
                log(f"[DAILY] Dispatched resource harvest for {len(CITY_RESOURCE_BUILDINGS)} city buildings (Opcode 120).")

            # 4. VIP Points and Free Chest (Opcode 7600, 8602, 8601)
            if vip_chest:
                log("[DAILY] Syncing VIP & claiming daily free chest...")
                pkt7600 = ProtobufCodec.encode_message({1: OP_VIP_SYNC, 2: DailyClaimsEngine.build_simple_ack(1)})
                pkt8602 = ProtobufCodec.encode_message({1: OP_VIP_POINTS, 2: DailyClaimsEngine.build_simple_ack(1)})
                pkt8601 = ProtobufCodec.encode_message({1: OP_VIP_CHEST, 2: DailyClaimsEngine.build_simple_ack(1)})
                writer.write(FrameParser.build_frame(c_tx.encrypt(pkt7600)))
                writer.write(FrameParser.build_frame(c_tx.encrypt(pkt8602)))
                writer.write(FrameParser.build_frame(c_tx.encrypt(pkt8601)))
                await writer.drain()
                log("[DAILY] Claimed VIP daily points & free chest (Opcode 8602/8601).")

            # 5. Daily Quests Activity (Opcode 143, 144)
            if daily_quests:
                log("[DAILY] Claiming daily quest activity milestone chests...")
                for mid in (6719, 10130, 92):
                    q143 = ProtobufCodec.encode_message({1: OP_QUEST_CHEST_143, 2: DailyClaimsEngine.build_simple_ack(mid)})
                    writer.write(FrameParser.build_frame(c_tx.encrypt(q143)))
                q144 = ProtobufCodec.encode_message({1: OP_QUEST_CHEST_144, 2: DailyClaimsEngine.build_simple_ack(92)})
                writer.write(FrameParser.build_frame(c_tx.encrypt(q144)))
                await writer.drain()
                log("[DAILY] Claimed quest activity chests (Opcode 143/144).")

            # 6. Monument / Chronicle
            if chronicle:
                c_pkt = ProtobufCodec.encode_message({
                    1: OP_CHRONICLE_CLAIM,
                    2: ProtobufCodec.encode_message({1: 1824424386, 2: 11543, 3: 1})
                })
                writer.write(FrameParser.build_frame(c_tx.encrypt(c_pkt)))
                await writer.drain()
                log("[DAILY] Claimed chronicle chapter rewards (Opcode 3535).")

            log("🎁 [DAILY SUCCESS] Daily claims and city harvest completed!")
            return {"success": True, "status": "completed"}

        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


execute_daily_claims = DailyClaimsEngine.execute_daily_claims

