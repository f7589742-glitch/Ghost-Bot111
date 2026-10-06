"""
hospital_engine.py - Hospital & Troop Healing Engine for Rise of Kingdoms Headless Bot.
Reversed and ground-truth verified from live packet capture decoded_20260916_224225.txt.

Telemetry References:
- Line 1059: C->S#1053 ops=[330] len=31 p2=280012041001080912041001080d1204100108051204100108010a0236371800 (Heal troops)
- Line 1070: C->S#1064 ops=[2048] len=15 p2=12023637080420001800 (Request alliance help for healing)
- Line 1079: C->S#1073 ops=[336] len=9 p2=0a023637 (Heal complete ACK)
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

logger = logging.getLogger("hospital_engine")

OP_QUERY_WOUNDED = 362           # C->S: Query wounded troops status
OP_QUERY_WOUNDED_RESP = 363      # S->C: Wounded status response
OP_HEAL_TROOPS = 330             # C->S: Start healing batch
OP_ALLIANCE_HELP_REQUEST = 2048  # C->S: Request alliance help
OP_HEAL_ACK = 336                # C->S: Heal ACK confirmation


class HospitalEngine:
    """
    Handles wounded querying, batch healing dispatch, and alliance help requests.
    """

    @staticmethod
    def build_query_wounded_payload() -> bytes:
        """
        Builds Opcode 362 payload to query hospital status.
        """
        return ProtobufCodec.encode_message({1: 1})

    @staticmethod
    def parse_wounded_troops(resp_payload: bytes) -> List[Dict[str, int]]:
        """
        Parses S->C Opcode 363 response for wounded units.
        Returns list of dicts: [{"unit_id": int, "count": int}, ...]
        """
        wounded_list = []
        try:
            msg = ProtobufCodec.decode_message(resp_payload)
            # Wounded entries typically under field 1 or 2 as repeated sub-messages
            for f_id in (1, 2, 3):
                if f_id in msg:
                    val = msg[f_id]
                    if isinstance(val, list):
                        for item in val:
                            if isinstance(item, dict) and 1 in item and 2 in item:
                                wounded_list.append({"unit_id": item[1], "count": item[2]})
                    elif isinstance(val, dict):
                        if 1 in val and 2 in val:
                            wounded_list.append({"unit_id": val[1], "count": val[2]})
        except Exception as e:
            logger.debug(f"[HOSPITAL] Error parsing wounded troops: {e}")
        return wounded_list

    @staticmethod
    def build_heal_payload(troops: List[Dict[str, int]], building_id: str = "67") -> bytes:
        """
        Builds Opcode 330 payload:
        Ground truth line 1059:
        p2=2800 120410010809 12041001080d 120410010805 120410010801 0a023637 1800
        Field 1 (string): building id "67" (wire 0a023637)
        Field 2 (repeated): troops to heal {1: unit_id, 2: count}
        Field 3: 0
        Field 5: 0
        """
        troop_msgs = []
        for t in troops:
            troop_msgs.append({
                1: int(t.get("unit_id", 1)),
                2: int(t.get("count", 1))
            })

        # Encoded manually or via ProtobufCodec
        msg = {
            1: building_id.encode("utf-8"),
            2: troop_msgs,
            3: 0,
            5: 0
        }
        return ProtobufCodec.encode_message(msg)

    @staticmethod
    def build_alliance_help_payload(building_id: str = "67") -> bytes:
        """
        Builds Opcode 2048 payload for alliance healing help.
        Ground truth line 1070:
        12023637 0804 2000 1800
        Field 1 (varint): 4 (type 4 = hospital healing)
        Field 2 (string): "67" (wire 12023637)
        Field 3: 0
        Field 4: 0
        """
        msg = {
            1: 4,
            2: building_id.encode("utf-8"),
            3: 0,
            4: 0
        }
        return ProtobufCodec.encode_message(msg)

    @staticmethod
    def build_heal_ack_payload(building_id: str = "67") -> bytes:
        """
        Builds Opcode 336 payload:
        Ground truth line 1079:
        0a023637 (Field 1 string = "67")
        """
        return ProtobufCodec.encode_message({1: building_id.encode("utf-8")})

    @staticmethod
    def run_healing_cycle(
        client,
        heal_batch: int = 1000,
        building_id: str = "67"
    ) -> bool:
        """
        Executes hospital healing sweep:
        1. Query wounded (362)
        2. Slice troops up to heal_batch
        3. Dispatch heal (330)
        4. Request alliance help (2048)
        5. ACK (336)
        """
        logger.info(f"[HOSPITAL] Checking hospital wounded status (batch limit: {heal_batch})...")
        try:
            # Query wounded
            client.send_packet(OP_QUERY_WOUNDED, HospitalEngine.build_query_wounded_payload())
            time.sleep(1.2)

            # Look for wounded list
            wounded = []
            if hasattr(client, "last_received_packets"):
                for op, p2 in reversed(client.last_received_packets[-15:]):
                    if op == OP_QUERY_WOUNDED_RESP:
                        wounded = HospitalEngine.parse_wounded_troops(p2)
                        if wounded:
                            break

            if not wounded:
                # Default mock check or small batch fallback if wounded count is unknown
                logger.info("[HOSPITAL] No wounded troops detected in hospital.")
                return False

            total_wounded = sum(t["count"] for t in wounded)
            logger.info(f"[HOSPITAL] Found {total_wounded} wounded troops across {len(wounded)} unit types.")

            # Slice troops according to heal_batch
            batch_to_heal = []
            remaining_budget = heal_batch if heal_batch > 0 else total_wounded

            for t in wounded:
                if remaining_budget <= 0:
                    break
                cnt = min(t["count"], remaining_budget)
                if cnt > 0:
                    batch_to_heal.append({"unit_id": t["unit_id"], "count": cnt})
                    remaining_budget -= cnt

            if not batch_to_heal:
                return False

            # Send heal 330
            client.send_packet(OP_HEAL_TROOPS, HospitalEngine.build_heal_payload(batch_to_heal, building_id))
            time.sleep(1.0)

            # Send alliance help 2048
            client.send_packet(OP_ALLIANCE_HELP_REQUEST, HospitalEngine.build_alliance_help_payload(building_id))
            time.sleep(0.8)

            # Send ACK 336
            client.send_packet(OP_HEAL_ACK, HospitalEngine.build_heal_ack_payload(building_id))
            logger.info(f"[HOSPITAL] Successfully initiated healing for {sum(t['count'] for t in batch_to_heal)} troops and requested alliance help.")
            return True

        except Exception as e:
            logger.error(f"[HOSPITAL] Healing cycle failed: {e}", exc_info=True)
            return False

    @classmethod
    async def execute_hospital_healing(
        cls,
        target_role_id: int,
        kingdom_id: int,
        gate_host: str,
        gate_port: int,
        app_uid: str,
        app_token: str,
        udid: str,
        heal_batch: int = 1000,
        building_id: str = "67",
        log_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Standalone async hospital query and healing execution.
        """
        def log(msg: str):
            if log_callback:
                log_callback(msg)
            else:
                logger.info(msg)

        log(f"[HOSPITAL] Connecting to Gateway {gate_host}:{gate_port} for Governor #{target_role_id}...")
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

            # Drain login ACK
            await asyncio.sleep(0.5)

            # 3. Query Wounded Troops (Opcode 362)
            log(f"[HOSPITAL] Querying wounded troops (Building #{building_id})...")
            q_pkt = ProtobufCodec.encode_message({
                1: OP_QUERY_WOUNDED,
                2: HospitalEngine.build_query_wounded_payload()
            })
            writer.write(FrameParser.build_frame(c_tx.encrypt(q_pkt)))
            await writer.drain()

            wounded_troops = []
            deadline = asyncio.get_event_loop().time() + 2.5
            while asyncio.get_event_loop().time() < deadline:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.4)
                    rl = (rh[0] << 8) | rh[1]
                    raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.4)
                    dec = c_rx.decrypt(raw)
                    import zlib
                    z_idx = dec.find(b"\x78\x9c")
                    if z_idx == -1: z_idx = dec.find(b"\x78\x01")
                    decomp = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
                    m = ProtobufCodec.decode_message(decomp)
                    chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                    for c in chunks:
                        it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                        if not isinstance(it, dict): continue
                        if it.get(1) == OP_QUERY_WOUNDED_RESP:
                            wounded_troops = HospitalEngine.parse_wounded_troops(it.get(2, b""))
                            if wounded_troops:
                                break
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

            if not wounded_troops:
                log("[HOSPITAL] No wounded troops in hospital (0 wounded).")
                return {"success": True, "wounded_count": 0, "healed_count": 0}

            total_wounded = sum(t["count"] for t in wounded_troops)
            batch_limit = heal_batch if heal_batch > 0 else total_wounded
            batch = []
            rem = batch_limit
            for t in wounded_troops:
                if rem <= 0: break
                take = min(t["count"], rem)
                if take > 0:
                    batch.append({"unit_id": t["unit_id"], "count": take})
                    rem -= take

            total_to_heal = sum(t["count"] for t in batch)
            log(f"[HOSPITAL] Healing batch of {total_to_heal:,} wounded troops (out of {total_wounded:,})...")

            # 4/5/6. Dispatch Heal (330) + Alliance Help (2048) + ACK (336)
            # معرّف المستشفى يختلف بين المدن (67 في لقطة قديمة، 80 في لقطة
            # اومر المستشفه: 336 p2=0a023830) — نجرب الاثنين والسيرفر
            # يرفض الخاطئ، ونعتمد فقط الرد المؤكد (103/363/124/2047).
            _candidates = []
            for _b in (str(building_id), "67", "80"):
                if _b and _b not in _candidates:
                    _candidates.append(_b)
            for _b in _candidates:
                heal_pkt = ProtobufCodec.encode_message({
                    1: OP_HEAL_TROOPS,
                    2: HospitalEngine.build_heal_payload(batch, _b)
                })
                writer.write(FrameParser.build_frame(c_tx.encrypt(heal_pkt)))
                await asyncio.sleep(0.3)
                help_pkt = ProtobufCodec.encode_message({
                    1: OP_ALLIANCE_HELP_REQUEST,
                    2: HospitalEngine.build_alliance_help_payload(_b)
                })
                writer.write(FrameParser.build_frame(c_tx.encrypt(help_pkt)))
                await asyncio.sleep(0.3)
                ack_pkt = ProtobufCodec.encode_message({
                    1: OP_HEAL_ACK,
                    2: HospitalEngine.build_heal_ack_payload(_b)
                })
                writer.write(FrameParser.build_frame(c_tx.encrypt(ack_pkt)))
                await asyncio.sleep(0.3)
            await writer.drain()

            # 7. انتظر تأكيد السيرفر بدل الادعاء المسبق
            import zlib as _zlib
            _confirmed = False
            _end = asyncio.get_event_loop().time() + 4.0
            while asyncio.get_event_loop().time() < _end:
                try:
                    _h = await asyncio.wait_for(reader.readexactly(2), timeout=0.5)
                    _l = (_h[0] << 8) | _h[1]
                    _raw = await asyncio.wait_for(reader.readexactly(_l), timeout=0.5)
                    _dec = c_rx.decrypt(_raw)
                    _zi = _dec.find(b"\x78\x9c")
                    if _zi == -1:
                        _zi = _dec.find(b"\x78\x01")
                    _dj = _zlib.decompress(_dec[_zi:]) if _zi != -1 else _dec
                    _m = ProtobufCodec.decode_message(_dj)
                    _ops = []
                    _stack = [_m]
                    while _stack:
                        _n = _stack.pop()
                        if isinstance(_n, dict):
                            if isinstance(_n.get(1), int):
                                _ops.append(_n.get(1))
                            for _v in _n.values():
                                if isinstance(_v, (dict, bytes, list)):
                                    _stack.append(_v)
                        elif isinstance(_n, list):
                            _stack.extend(_n)
                        elif isinstance(_n, (bytes, bytearray)) and len(_n) > 2:
                            try:
                                _stack.append(ProtobufCodec.decode_message(bytes(_n)))
                            except Exception:
                                pass
                    if any(_o in (103, 363, 124, 1160, 2047) for _o in _ops):
                        _confirmed = True
                        log(f"[HOSPITAL] Server confirmed heal (ops={sorted(set(_ops))}).")
                        break
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    continue
                except Exception:
                    break

            if not _confirmed:
                log("[HOSPITAL] Server did NOT confirm healing (no 103/363/124/2047) — reporting unconfirmed.")
                return {"success": False, "wounded_count": total_wounded, "healed_count": 0,
                        "healed": 0, "wounded": total_wounded}

            log(f"🩹 [HOSPITAL SUCCESS] Healed {total_to_heal:,} troops and requested alliance help!")
            return {"success": True, "wounded_count": total_wounded, "healed_count": total_to_heal,
                    "healed": total_to_heal, "wounded": total_wounded}

        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


execute_hospital_healing = HospitalEngine.execute_hospital_healing

