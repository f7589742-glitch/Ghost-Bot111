import os
import sys
import asyncio
import logging
import time
import zlib
from typing import Optional, Dict, Any, Callable, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(PROJECT_ROOT, "python") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "python"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.models import CharacterDAO, AccountDAO, InventoryDAO
from app.services.lilith_cloud import LilithCloudService

logger = logging.getLogger("SessionManager")

# Global gathering scheduler pause flag
_GATHER_SCHEDULER_PAUSED = False


def toggle_gather_scheduler(paused: bool = True):
    """
    Temporarily pauses or resumes automated gathering workers in the AutonomousScheduler
    to ensure dedicated bandwidth and zero session/march contention during RSS transfers.
    """
    global _GATHER_SCHEDULER_PAUSED
    _GATHER_SCHEDULER_PAUSED = paused
    if paused:
        logger.info("⏸️ [SESSION MANAGER] تم إيقاف جدولة جمع الموارد مؤقتاً لتفريغ المسيرات ونقل الموارد.")
    else:
        logger.info("▶️ [SESSION MANAGER] تم استئناف جدولة جمع الموارد التلقائية لجميع الحسابات.")


def is_gather_scheduler_paused() -> bool:
    """Returns True if the gather scheduler is currently paused for RSS transfer."""
    return _GATHER_SCHEDULER_PAUSED


class HeadlessTransferClient:
    """
    Dedicated lightweight headless connection client for executing RSS transfers and march recalls.
    Wraps gateway connection, dual-LFSR encryption, and packet dispatching.
    """
    def __init__(self, role_id: str, kingdom_id: int, log_cb: Optional[Callable[[str], None]] = None):
        self.role_id = str(role_id)
        self.kingdom_id = int(kingdom_id)
        self.log_cb = log_cb or (lambda msg: logger.info(msg))
        self.char_name = f"Role_{role_id}"
        
        # Load baseline resources immediately from DB so we never show empty 0
        char_db = CharacterDAO.get_by_role_id(self.role_id)
        food_db = int(char_db.get("food") or 0) if char_db else 0
        wood_db = int(char_db.get("wood") or 0) if char_db else 0
        stone_db = int(char_db.get("stone") or 0) if char_db else 0
        gold_db = int(char_db.get("gold") or 0) if char_db else 0
        city_lvl_db = int(char_db.get("city_level") or char_db.get("city_hall") or 17) if char_db else 17
        if char_db and char_db.get("name"):
            self.char_name = char_db["name"]

        self.state: Dict[str, Any] = {
            "resources": {
                "food": food_db,
                "wood": wood_db,
                "stone": stone_db,
                "gold": gold_db
            },
            "buildings": {
                "trading_post_lvl": min(25, max(1, city_lvl_db)),
                # Provenance: True only when opcode 904/302 reports building 23.
                # City-hall-derived values are estimates, never wire truth.
                "trading_post_confirmed": False
            },
            "marches": {}
        }
        self.reader = None
        self.writer = None
        self.crypto_tx = None
        self.crypto_rx = None
        self.login_flood_bytes: List[bytes] = []
        self._connected = False
        self._cached_account: Optional[Dict[str, Any]] = None

    async def connect(self, account: Dict[str, Any]) -> bool:
        """Establishes TCP connection to game gateway, negotiates dual crypto seeds, and logs in."""
        self._cached_account = account
        try:
            from crypto_module import RokCrypto
            from headless_client import ProtobufCodec, FrameParser
            from derive_seed_from_nonce import derive_seed
            from app.services.city_state_parser import parse_resources_121, parse_city_state_1002

            app_uid = str(account.get("app_uid") or "")
            app_token = str(account.get("app_token") or "")
            udid = str(account.get("udid") or "")

            target_char_dict = {
                "role_id": int(self.role_id),
                "kingdom_id": self.kingdom_id,
                "app_uid": app_uid,
                "app_token": app_token,
                "udid": udid,
                "name": self.char_name
            }

            try:
                from cloud_role_switcher import ensure_character_active
                ensure_character_active(target_char_dict)
            except Exception as e_sw:
                logger.debug(f"[{self.role_id}] Role switcher note: {e_sw}")

            try:
                from fleet_manager import resolve_login_bytes
                login_bytes = resolve_login_bytes(target_char_dict)
            except Exception as e_lb:
                logger.debug(f"[{self.role_id}] resolve_login_bytes fallback: {e_lb}")
                login_bytes = ProtobufCodec.encode_message({
                    1: int(self.role_id),
                    2: app_token,
                    3: udid,
                    4: self.kingdom_id
                })

            gate_host, gate_port = LilithCloudService.resolve_gateway(app_uid, app_token, udid, self.kingdom_id)
            self.log_cb(f"[{self.role_id}] 🌐 الاتصال ببوابة الخادم {gate_host}:{gate_port}...")

            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(gate_host, gate_port),
                timeout=10.0
            )

            # 1. Nonce Handshake & Dual Seed Derivation
            hdr = await asyncio.wait_for(self.reader.readexactly(2), timeout=5.0)
            pkt_len = (hdr[0] << 8) | hdr[1]
            greeting_raw = await asyncio.wait_for(self.reader.readexactly(pkt_len), timeout=5.0)
            
            g_fields = ProtobufCodec.decode_message(greeting_raw)
            sub = ProtobufCodec.decode_message(g_fields.get(2, b""))
            sub1 = sub.get(1, 0)
            sub2 = sub.get(2, 0)
            seed_tx, seed_rx = derive_seed(sub1, sub2)

            self.crypto_tx = RokCrypto(seed_tx)
            self.crypto_rx = RokCrypto(seed_rx)

            # 2. Authenticate
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(login_bytes)))
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 6404, 2: ProtobufCodec.encode_message({1: self.kingdom_id})}))))
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: b""}))))
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: b""}))))
            await self.writer.drain()
            await asyncio.sleep(0.3)
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b""}))))
            await self.writer.drain()

            self._connected = True

            # 3. Drain initial incoming packets to populate state (Trading Post, Resources, Marches)
            await self._drain_state(duration=2.5)
            
            # Summary log of live synced resources
            cur_rss = self.state["resources"]
            tp_lvl = self.state["buildings"]["trading_post_lvl"]
            self.log_cb(
                f"[{self.role_id}] 💎 الموارد الفعلية المتوفرة: "
                f"طعام: {cur_rss.get('food', 0):,} | "
                f"خشب: {cur_rss.get('wood', 0):,} | "
                f"حجر: {cur_rss.get('stone', 0):,} | "
                f"ذهب: {cur_rss.get('gold', 0):,} "
                f"(سوق لفل {tp_lvl})"
            )
            return True

        except Exception as e:
            self.log_cb(f"[{self.role_id}] ⚠️ تعذر الاتصال المباشر بالخادم: {e}")
            self._load_fallback_state()
            self._connected = False
            return False

    async def reconnect(self) -> bool:
        """Safely reconnects to game gateway using cached credentials upon socket drop."""
        if not self._cached_account:
            return False
        self.log_cb(f"[{self.role_id}] 🔄 إعادة الاتصال بالسيرفر وتجديد الجلسة السحابية...")
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self._connected = False
        return await self.connect(self._cached_account)

    def _load_fallback_state(self):
        """Loads cached resources and defaults from DB when direct socket drops."""
        try:
            con = CharacterDAO.get_by_role_id(self.role_id)
            if con:
                self.state["resources"] = {
                    "food": int(con.get("food") or 10000000),
                    "wood": int(con.get("wood") or 10000000),
                    "stone": int(con.get("stone") or 5000000),
                    "gold": int(con.get("gold") or 2000000),
                }
                self.state["buildings"]["trading_post_lvl"] = int(con.get("city_level") or con.get("city_hall") or 17)
        except Exception:
            pass

    async def _drain_state(self, duration: float = 2.0):
        """Drains incoming frames to discover live liquid resources, trading post level, and marches."""
        from headless_client import ProtobufCodec
        from app.services.city_state_parser import parse_resources_121, parse_city_state_1002

        deadline = asyncio.get_event_loop().time() + duration
        while asyncio.get_event_loop().time() < deadline:
            try:
                rh = await asyncio.wait_for(self.reader.readexactly(2), timeout=0.4)
                rl = (rh[0] << 8) | rh[1]
                raw_pkt = await asyncio.wait_for(self.reader.readexactly(rl), timeout=0.4)
                dec = self.crypto_rx.decrypt(raw_pkt)
                
                # Cache raw stream bytes for march recall scanner
                self.login_flood_bytes.append(dec)

                for magic in (b"\x78\x9c", b"\x78\x01", b"\x78\xda"):
                    z_idx = dec.find(magic)
                    if z_idx != -1:
                        try:
                            decomp = zlib.decompress(dec[z_idx:])
                            break
                        except Exception:
                            pass
                else:
                    decomp = dec

                msg = ProtobufCodec.decode_message(decomp)
                chunks = msg.get(1) if isinstance(msg.get(1), list) else [msg]

                for c in chunks:
                    m = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                    op = m.get(1)

                    # Opcode 121: Liquid resources authoritative balance
                    if op == 121:
                        p121 = m.get(2) or decomp
                        rss = parse_resources_121(p121)
                        if rss:
                            for r_k in ("food", "wood", "stone", "gold"):
                                if r_k in rss and rss[r_k] is not None:
                                    self.state["resources"][r_k] = int(rss[r_k])

                    # Opcode 1002: Governor profile metadata & City Hall level
                    elif op == 1002:
                        p2 = m.get(2)
                        if isinstance(p2, bytes):
                            snap = parse_city_state_1002(p2)
                            if snap and snap.get("city_hall_level"):
                                ch_lvl = int(snap["city_hall_level"])
                                # Auto-detect trading post level from city hall progression
                                self.state["buildings"]["trading_post_lvl"] = min(25, max(1, ch_lvl))

                    # Opcode 904/302: Building entity updates
                    elif op in (904, 302):
                        p = m.get(2, {})
                        if isinstance(p, dict) and p.get(1) == 23:
                            lvl = p.get(2, 17)
                            self.state["buildings"]["trading_post_lvl"] = int(lvl)
                            self.state["buildings"]["trading_post_confirmed"] = True

            except asyncio.TimeoutError:
                break
            except Exception:
                break

    async def recall_marches(self) -> int:
        """Invokes verified Opcode 1014 march recall service to safely return all outside troops."""
        if not self._connected or not self.reader or not self.writer:
            return 0

        try:
            from app.services.march_recall import recall_character_marches, extract_all_marches
            from headless_client import ProtobufCodec, FrameParser

            def wire_log(ev: str, msg: str):
                logger.info(f"[{self.role_id}] [{ev}] {msg}")

            res = await recall_character_marches(
                reader=self.reader,
                writer=self.writer,
                crypto_tx=self.crypto_tx,
                crypto_rx=self.crypto_rx,
                role_id=self.role_id,
                login_flood_bytes=self.login_flood_bytes,
                log_wire=wire_log,
                ProtobufCodec=ProtobufCodec,
                FrameParser=FrameParser,
                char_name=self.char_name
            )
            recalled = res.get("recalled", 0)
            total_found = res.get("total_found", 0)
            if total_found > 0 or recalled > 0:
                count = max(total_found, recalled)
                self.log_cb(f"[{self.role_id}] ⏳ تم رصد {count} مسيرة خارج الأسوار وإعطاء أمر العودة. جاري مراقبة عودة القوات ودخولها للقلعة...")
                
                # Active physical return tracking - wait until 100% of marches enter city walls
                start_t = asyncio.get_event_loop().time()
                timeout = 40.0
                empty_checks = 0
                while asyncio.get_event_loop().time() - start_t < timeout:
                    # Sync request to keep active march state updated and prevent gateway timeout
                    try:
                        sync_pkt = ProtobufCodec.encode_message({1: 1005, 2: b""})
                        self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(sync_pkt)))
                        kv_pkt = ProtobufCodec.encode_message({1: 1001, 2: b""})
                        self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(kv_pkt)))
                        await self.writer.drain()
                    except (BrokenPipeError, ConnectionResetError, IOError, OSError) as e_pipe:
                        self.log_cb(f"[{self.role_id}] ⚠️ انقطع الاتصال أثناء انتظار القوات ({e_pipe}). جاري تجديد الجلسة...")
                        await self.reconnect()

                    curr_marches = {}
                    drain_until = asyncio.get_event_loop().time() + 1.5
                    while asyncio.get_event_loop().time() < drain_until:
                        try:
                            rh = await asyncio.wait_for(self.reader.readexactly(2), timeout=0.5)
                            rl = (rh[0] << 8) | rh[1]
                            raw = await self.reader.readexactly(rl)
                            dec = self.crypto_rx.decrypt(raw)
                            for magic in (b"\x78\x9c", b"\x78\x01", b"\x78\xda"):
                                zi = dec.find(magic)
                                if zi != -1:
                                    try:
                                        dec = zlib.decompress(dec[zi:])
                                        break
                                    except Exception:
                                        pass
                            msg = ProtobufCodec.decode_message(dec)
                            extract_all_marches(msg, int(self.role_id), curr_marches, ProtobufCodec)
                        except Exception:
                            break

                    elapsed = int(asyncio.get_event_loop().time() - start_t)
                    if not curr_marches:
                        empty_checks += 1
                        if empty_checks >= 2:
                            self.log_cb(f"[{self.role_id}] 🏰 دخلت كافة القوات إلى داخل القلعة والمدينة آمنة 100%! (استغرقت {elapsed} ثانية)")
                            break
                        else:
                            self.log_cb(f"[{self.role_id}] ⏳ جاري تأكيد دخول كافة القوات واستقرارها داخل الأسوار... [{elapsed}ث]")
                    else:
                        empty_checks = 0
                        self.log_cb(f"[{self.role_id}] 🚶 القوات في طريق العودة إلى القلعة (متبقي {len(curr_marches)} مسيرة بالخارج)... [{elapsed}ث]")

                    await asyncio.sleep(1.5)

                if curr_marches:
                    self.log_cb(f"[{self.role_id}] ⚠️ تنبيه: تم إعطاء أمر العودة لجميع القوات. متابعة الإرسال بالمسيرات المتاحة.")
            else:
                self.log_cb(f"[{self.role_id}] 🛡️ المدينة في وضع آمن: لا توجد قوات خارج الأسوار.")
            return recalled
        except Exception as e:
            logger.warning(f"[{self.role_id}] recall_marches error: {e}")
            return 0

    async def inspect_target_city(self, target_role_id: str, target_x: float, target_y: float) -> bool:
        """Inspects recipient city and aligns viewport using authentic Opcodes 1004, 1171, 110, 4311, 1050."""
        if not self._connected or not self.writer:
            return False

        try:
            import struct
            from headless_client import ProtobufCodec, FrameParser

            wx = float(target_x * 6.0)
            wy = float(target_y * 6.0)

            # 1. Opcode 1004: Map viewport
            x_bytes = struct.pack('<f', wx)
            y_bytes = struct.pack('<f', wy)
            p_1004 = ProtobufCodec.encode_message({
                1: ProtobufCodec.encode_message({1: x_bytes, 2: y_bytes}),
                5: 1
            })
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 1004, 2: p_1004}))))

            # 2. Opcode 1171: Handshake hash
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 1171, 2: ProtobufCodec.encode_message({1: 551003})}))))

            # 3. Opcode 110: Player relation {1: target_id, 2: kingdom_id, 3: sender_id}
            p_110 = ProtobufCodec.encode_message({
                1: int(target_role_id),
                2: int(self.kingdom_id),
                3: int(self.role_id)
            })
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: p_110}))))

            # 4. Opcode 4311: Target selection
            p_4311 = ProtobufCodec.encode_message({1: int(target_role_id)})
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 4311, 2: p_4311}))))

            # 5. Opcode 1050: Target entity inspection
            f3_bytes = ProtobufCodec.encode_message({1: x_bytes, 2: y_bytes})
            p_1050 = ProtobufCodec.encode_message({1: 0, 2: 0, 3: f3_bytes, 4: f3_bytes, 5: 1})
            self.writer.write(FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 1050, 2: p_1050}))))

            await self.writer.drain()
            await asyncio.sleep(0.6)
            return True
        except Exception as e:
            logger.warning(f"[{self.role_id}] inspect_target_city error: {e}")
            return False

    async def send_resource_transport(self, target_role_id: str, res_id: int, amount: int) -> Dict[str, Any]:
        """Dispatches authentic Opcode 1056 resource aid caravan to target city with auto-reconnect resilience."""
        for attempt in range(2):
            if not self._connected or not self.writer:
                if self._cached_account:
                    ok = await self.reconnect()
                    if not ok:
                        return {"success": False, "error": "غير متصل بالخادم"}
                else:
                    return {"success": False, "error": "غير متصل بالخادم"}

            try:
                from headless_client import ProtobufCodec, FrameParser
                from app.services.city_state_parser import parse_resources_121

                p_inner = ProtobufCodec.encode_message({
                    1: int(res_id),
                    2: int(amount)
                })
                p_1056 = ProtobufCodec.encode_message({
                    1: int(target_role_id),
                    2: p_inner
                })
                frame = FrameParser.build_frame(self.crypto_tx.encrypt(ProtobufCodec.encode_message({1: 1056, 2: p_1056})))
                self.writer.write(frame)
                await self.writer.drain()

                # Wait for server ACK (Opcode 1057 caravan march dispatch confirmation or Opcode 121 balance deduction)
                ack_success = False
                error_msg = None
                deadline = asyncio.get_event_loop().time() + 4.0
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        rh = await asyncio.wait_for(self.reader.readexactly(2), timeout=0.8)
                        rl = (rh[0] << 8) | rh[1]
                        raw = await asyncio.wait_for(self.reader.readexactly(rl), timeout=0.8)
                        dec = self.crypto_rx.decrypt(raw)
                        for magic in (b"\x78\x9c", b"\x78\x01", b"\x78\xda"):
                            zi = dec.find(magic)
                            if zi != -1:
                                try:
                                    dec = zlib.decompress(dec[zi:])
                                    break
                                except Exception:
                                    pass
                        msg = ProtobufCodec.decode_message(dec)
                        chunks = msg.get(1) if isinstance(msg.get(1), list) else [msg]
                        for c in chunks:
                            m = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                            op = m.get(1)
                            if op == 1057:
                                ack_success = True
                            elif op == 121:
                                rss_upd = parse_resources_121(m.get(2) or dec)
                                if rss_upd:
                                    for k, v in rss_upd.items():
                                        if v is not None:
                                            self.state["resources"][k] = int(v)
                                    ack_success = True
                            elif op == 1:
                                err_data = m.get(2)
                                err_sub = ProtobufCodec.decode_message(err_data) if isinstance(err_data, bytes) else (err_data or {})
                                if err_sub.get(1) == 1056:
                                    err_code = err_sub.get(2)
                                    error_msg = f"كود رفض الخادم {err_code}"
                    except Exception:
                        break

                return {"success": ack_success, "amount": amount, "error": error_msg}

            except (BrokenPipeError, ConnectionResetError, IOError, OSError) as sock_err:
                logger.warning(f"[{self.role_id}] Socket error in send_resource_transport: {sock_err}")
                self._connected = False
                if attempt == 0 and self._cached_account:
                    self.log_cb(f"[{self.role_id}] ⚠️ انقطع اتصال السوكيت ({sock_err}). جاري إعادة الاتصال التلقائي وإعادة المحاولة...")
                    reconnected = await self.reconnect()
                    if reconnected:
                        continue
                return {"success": False, "error": str(sock_err)}
            except Exception as e:
                logger.warning(f"[{self.role_id}] send_resource_transport error: {e}")
                return {"success": False, "error": str(e)}

    async def send_packet(self, opcode: int, payload: Dict[Any, Any]) -> Dict[str, Any]:
        """Encodes and sends an Opcode frame, returns response code."""
        if not self._connected or not self.writer:
            return {"code": -1, "error": "غير متصل بالخادم"}

        try:
            from headless_client import ProtobufCodec, FrameParser
            encoded_payload = ProtobufCodec.encode_message(payload)
            frame_msg = ProtobufCodec.encode_message({1: opcode, 2: encoded_payload})
            encrypted_frame = self.crypto_tx.encrypt(frame_msg)
            self.writer.write(FrameParser.build_frame(encrypted_frame))
            await self.writer.drain()

            # Read quick ACK
            try:
                rh = await asyncio.wait_for(self.reader.readexactly(2), timeout=1.5)
                rl = (rh[0] << 8) | rh[1]
                raw = await asyncio.wait_for(self.reader.readexactly(rl), timeout=1.5)
                dec = self.crypto_rx.decrypt(raw)
                for magic in (b"\x78\x9c", b"\x78\x01"):
                    zi = dec.find(magic)
                    if zi != -1:
                        try:
                            dec = zlib.decompress(dec[zi:])
                            break
                        except Exception:
                            pass
                ack_msg = ProtobufCodec.decode_message(dec)
                return {"code": 0, "ack": ack_msg}
            except Exception:
                return {"code": 0}

        except Exception as e:
            logger.warning(f"send_packet({opcode}) error: {e}")
            return {"code": 0}

    async def close(self):
        """Closes the client socket."""
        self._connected = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


async def get_active_client(farm_role_id: str, user_id: str = "", log_cb: Optional[Callable[[str], None]] = None) -> Optional[HeadlessTransferClient]:
    """
    Factory function to retrieve or instantiate a HeadlessTransferClient for a given farm role.
    """
    char = CharacterDAO.get_by_role_id(farm_role_id)
    kingdom_id = int(char.get("kingdom_id") or 3057) if char else 3057
    client = HeadlessTransferClient(farm_role_id, kingdom_id=kingdom_id, log_cb=log_cb)

    # Fetch corresponding account credentials
    account = None
    if char and char.get("account_id"):
        account = AccountDAO.get_by_id(int(char["account_id"]))

    if account:
        connected = await client.connect(account)
        if not connected:
            log_cb(f"[{farm_role_id}] ❌ فشل الاتصال المباشر بالخادم للمزرعة.")
            await client.close()
            return None
    else:
        log_cb(f"[{farm_role_id}] ❌ لم يتم العثور على بيانات الحساب في قاعدة البيانات.")
        return None

    return client
