"""
Daily Routines Engine - Granular Automation for Daily Claims & Alliance Routines
Rise of Kingdoms Headless Bot Framework.

Each routine is isolated and controlled by its own independent dashboard toggle.
Strictly targets live protocol packet bindings from ground-truth packet captures.
"""

import asyncio
import logging
import sys
import os
import zlib
from typing import Dict, Any, Optional

# Make the vendored protocol helpers importable regardless of launch directory.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, "python")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from headless_client import ProtobufCodec
except ImportError:  # pragma: no cover - fallback for alternate layouts
    from python.headless_client import ProtobufCodec

logger = logging.getLogger("daily_routines")

# Protocol Opcode Constants (ground-truth verified from live packet captures)
OP_VIP_SYNC = 7600          # C->S: VIP sync
OP_VIP_POINTS = 8602        # C->S: Claim VIP daily points
OP_VIP_CHEST = 8601         # C->S: Claim VIP daily chest
OP_CITY_HARVEST = 120       # C->S: Harvest city resource buildings
OP_CHRONICLE_CLAIM = 3535   # C->S: Claim chronicle/monument rewards
OP_QUEST_CHEST_143 = 143    # C->S: Claim daily quest activity chests (milestones)
OP_QUEST_CHEST_144 = 144    # C->S: Claim daily quest activity reward
OP_QUEST_CLAIM = 203        # C->S: Claim completed quest
OP_ALLIANCE_HELP = 5501     # C->S: Help all alliance members
OP_CLAIM_TERRITORY = 3370   # C->S: Claim territory resource pit
OP_CLAIM_GIFTS = 3170       # C->S: Claim alliance gifts
OP_CLAIM_GIFT_CHEST = 3132  # C->S: Claim all alliance gift chests
OP_ALLIANCE_CONTEXT = 532   # C->S: Open alliance context

# Mission claim opcodes (live-capture verified)
OP_QUEST_CLAIM_207 = 207    # C->S: claim quest (payload = raw quest entry from op 204)
QUEST_CATS = (1, 2, 3, 4, 6, 7, 8)   # op 203 categories that return a quest list
# فئات إضافية اكتُشفت بالمسح المباشر (9 و12 تعودان بقوائم فعلية ومطالبات مقبولة،
# و5/10/11 فارغة) — تُستخدم مع روتين المهام الجانبية.
SIDE_QUEST_CATS = (9, 12)


def _pb_varint(buf: bytes, i: int = 0):
    val = shift = 0
    while True:
        c = buf[i]
        i += 1
        val |= (c & 0x7F) << shift
        if not (c & 0x80):
            return val, i
        shift += 7


def _pb_map(buf: bytes) -> dict:
    """Tiny protobuf decoder -> {field: value}."""
    out: dict = {}
    i = 0
    try:
        while i < len(buf):
            key, i = _pb_varint(buf, i)
            fn, wt = key >> 3, key & 7
            if wt == 0:
                v, i = _pb_varint(buf, i)
                out[fn] = v
            elif wt == 2:
                ln, i = _pb_varint(buf, i)
                out[fn] = buf[i:i + ln]
                i += ln
            elif wt == 5:
                out[fn] = buf[i:i + 4]
                i += 4
            elif wt == 1:
                out[fn] = buf[i:i + 8]
                i += 8
            else:
                break
    except Exception:
        pass
    return out


def _quest_row(entry: bytes):
    """quest entry -> (quest_id, current, target); progress lives in field 3 {1:cur, 2:tgt}."""
    try:
        m = _pb_map(entry)
        raw_id = m.get(1)
        qid = None
        if isinstance(raw_id, (bytes, bytearray)):
            try:
                qid = int(raw_id.decode())
            except Exception:
                qid = None
        elif isinstance(raw_id, int):
            qid = raw_id
        pr = m.get(3)
        cur = tgt = None
        if isinstance(pr, (bytes, bytearray)) and pr:
            pm = _pb_map(pr)
            cur, tgt = pm.get(1), pm.get(2)
        def _sg(v):
            if v is None:
                return None
            return v - (1 << 64) if v >= (1 << 63) else v
        return qid, _sg(cur), _sg(tgt)
    except Exception:
        return None, None, None


class DailyRoutinesEngine:
    """
    Handles granular daily claims and alliance automations:
    - VIP Points & Free Chest
    - City Resource Harvesting
    - Kingdom Chronicle / Monument Rewards
    - Daily Quest Activity Chests
    - Side & Main Quest Rewards
    - Alliance Help All
    - Alliance Territory Resource Pit
    - Alliance Gifts & Chests
    """

    @staticmethod
    def build_simple_ack(field1_val: int = 1) -> bytes:
        """Build simple protobuf ack with field 1 = value."""
        try:
            from headless_client import ProtobufCodec
        except ImportError:
            from python.headless_client import ProtobufCodec
        return ProtobufCodec.encode_message({1: int(field1_val)})

    @classmethod
    async def execute_daily_routines(
        cls,
        target_role_id: int,
        kingdom_id: int,
        gate_host: str,
        gate_port: int,
        app_uid: str,
        app_token: str,
        udid: str,
        cfg: Dict[str, Any],
        log_callback: Optional[Any] = None,
        user_bot_id: str = "",
        char_name: str = ""
    ) -> Dict[str, Any]:
        """
        Standalone async execution of all enabled daily routines.
        Each routine runs only if its corresponding toggle is True in cfg.
        """
        def log(msg: str):
            if log_callback:
                log_callback(msg)
            else:
                logger.info(msg)

        log(f"[DAILY_ROUTINES] Connecting to Gateway {gate_host}:{gate_port} for Governor #{target_role_id}...")
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

        import time as _perf
        _t0 = _perf.monotonic()

        def _stage(msg: str):
            log(f"[DAILY][STAGE] {msg} (+{(_perf.monotonic() - _t0):.1f}s)")

        def _collect(msg, depth=0):
            """Server frames wrap inner messages as bytes — unwrap until op is an int."""
            out = []
            if not isinstance(msg, dict) or depth > 3:
                return out
            f1 = msg.get(1)
            if isinstance(f1, int):
                out.append(msg)
            elif isinstance(f1, (bytes, bytearray)):
                try:
                    out.extend(_collect(ProtobufCodec.decode_message(f1), depth + 1))
                except Exception:
                    pass
            elif isinstance(f1, list):
                for it in f1:
                    if isinstance(it, dict):
                        out.extend(_collect(it, depth + 1))
                    elif isinstance(it, (bytes, bytearray)):
                        try:
                            out.extend(_collect(ProtobufCodec.decode_message(it), depth + 1))
                        except Exception:
                            pass
            return out

        reader, writer = await open_game_connection(gate_host, gate_port)
        _stage("TCP connected")
        try:
            # 1. Handshake Greeting 8306
            hdr = await asyncio.wait_for(reader.readexactly(2), timeout=6.0)
            g_p = await reader.readexactly((hdr[0] << 8) | hdr[1])
            sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(g_p).get(2, b""))
            tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
            c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)
            _stage("handshake decoded")

            # 2. Login Opcode 14 — MUST use the proven role-binding builder.
            from app.services.lilith_cloud import LilithCloudService
            login_bytes = None
            try:
                from fleet_manager import build_dynamic_login_payload
                login_bytes = build_dynamic_login_payload(
                    app_uid=str(app_uid),
                    access_token=str(app_token),
                    role_id=int(target_role_id),
                    device_id=str(udid),
                    kingdom_id=int(kingdom_id),
                    server_id_int=2104267,
                    public_ip=str(LilithCloudService.public_ip() or ""),
                )
                _stage("login frame built (build_dynamic_login_payload, role bound)")
            except Exception as _le:
                log(f"[WARN] dynamic login builder failed ({_le}); trying android builder")
                try:
                    from app.services.socket_worker import build_android_login_frame
                    login_bytes = build_android_login_frame(
                        app_uid=str(app_uid),
                        access_token=str(app_token),
                        device_udid=str(udid),
                    )
                    _stage("login frame built (build_android_login_frame)")
                except Exception as _ae:
                    log(f"[ERROR] android login builder failed too: {_ae}")

            if not login_bytes:
                raise RuntimeError("could not build a login frame")

            writer.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))

            # Same post-login sequence the (working) gather engine uses:
            # 104 / 107 / 6404(kingdom) / 203 / 110, then 1001 to pull op 1002.
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 6404, 2: ProtobufCodec.encode_message({1: int(kingdom_id)})}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: b""}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: b""}))))
            await writer.drain()
            _stage("login + role binding sent")
            await asyncio.sleep(0.5)
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b""}))))
            await writer.drain()

            # 2b. City-state snapshot capture (Opcode 125/1002)
            try:
                import os as _os
                _samp = f"/tmp/op125_daily_{target_role_id}.bin"
                _frames_seen = 0
                _stage_deadline = _perf.monotonic() + 8.0
                while True:
                    if _perf.monotonic() > _stage_deadline:
                        log(f"[DAILY][SNAPSHOT] hard cap 8s reached after {_frames_seen} frames — proceeding to routines.")
                        break
                    try:
                        fh = await asyncio.wait_for(reader.readexactly(2), timeout=2.5)
                        _frames_seen += 1
                        plen = (fh[0] << 8) | fh[1]
                        rpay = c_rx.decrypt(await asyncio.wait_for(reader.readexactly(plen), timeout=3.0))
                        zi = rpay.find(b"\x78\x9c")
                        if zi == -1:
                            zi = rpay.find(b"\x78\x01")
                        decomp = zlib.decompress(rpay[zi:]) if zi != -1 else rpay
                        if len(decomp) < 64:
                            if _frames_seen <= 12:
                                log(f"[DAILY][SNAPSHOT] frame#{_frames_seen} small ({len(decomp)}B) skipped (+{(_perf.monotonic() - _t0):.1f}s)")
                            continue
                        if not _os.path.exists(_samp):
                            with open(_samp, "wb") as sf:
                                sf.write(decomp)
                        msg = ProtobufCodec.decode_message(decomp)
                        subs = _collect(msg)
                        done = False
                        for sub in subs:
                            op = sub.get(1)
                            if _frames_seen <= 12:
                                log(f"[DAILY][SNAPSHOT] frame#{_frames_seen} op={op} bytes={len(decomp)} (+{(_perf.monotonic() - _t0):.1f}s)")
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
            _stage(f"pre-routines (snapshot frames={locals().get('_frames_seen', -1)})")

            # ---------------------------------------------------------
            # Response tap: every claim below is followed by a short read
            # so rejected/expired packets show up instead of silently dying.
            # ---------------------------------------------------------
            routines_run = []
            wire_seen = {}
            rejected = {}
            acked = {}
            results = []

            def _judge(tag: str, label: str, ok_msg: str, already_msg: str,
                       allow_silent: bool = False, require_op=None):
                """+ = نجح، - = مأخوذ من قبل / مرفوض / بلا رد.

                require_op: صيغة النجاح الحقيقية لبعض العمليات (مثل 122 للحصاد).
                عندها لا يُعتبَّر أي رد "نجاحًا" بل يجب أن يعيد السيرفر ذلك
                الأوبكود فعلًا، وإلا تظهر السطر بعلامة `-`."""
                errs = rejected.get(tag) or []
                wire = wire_seen.get(tag) or []
                replied = any(d.get("op") != 8003 for d in wire)
                hit = None
                if require_op is not None:
                    wanted = require_op if isinstance(require_op, (tuple, list, set)) else (require_op,)
                    hits = [d for d in wire if d.get("op") in wanted]
                    if hits:
                        hit = len(hits)
                if errs:
                    codes = ", ".join(str(c) for _, c in errs)
                    line = f"- [{label}] {already_msg} (رمز: {codes})"
                elif require_op is not None:
                    if hit:
                        line = f"+ [{label}] {ok_msg}" if "{n}" not in ok_msg \
                            else f"+ [{label}] {ok_msg.format(n=hit)}"
                    else:
                        line = f"- [{label}] السيرفر لم يؤكد {tag} (لا يوجد رد مطابق)"
                elif replied or allow_silent:
                    line = f"+ [{label}] {ok_msg}"
                else:
                    line = f"- [{label}] لا يوجد رد من السيرفر"
                results.append(line)
                log(f"[DAILY][RESULT] {line}")
                return not line.startswith("-")

            def _judge_counts(tag: str, label: str, ok_msg: str, already_msg: str,
                              already_codes=(157,), evidence_op=None):
                """لعمليات المسح المتعدد: يعرض عدد ما نجح مقابل ما كان مأخوذًا من قبل.

                evidence_op: أوبكودات الاستجابة الناجحة التي لا يقابلها رمز قبول
                (مثل 3171/3134 لهدايا التحالف) — تُحتسب كنجاح بدل تجاهلها.
                """
                if isinstance(already_codes, int):
                    already_codes = (already_codes,)
                ok = len(acked.get(tag) or [])
                if not ok and evidence_op is not None:
                    wanted = evidence_op if isinstance(evidence_op, (tuple, list, set)) else (evidence_op,)
                    ok = len([d for d in (wire_seen.get(tag) or [])
                              if d.get("op") in wanted])
                errs = rejected.get(tag) or []
                already = [c for _, c in errs if c in already_codes]
                other = [c for _, c in errs if c not in already_codes]
                if ok:
                    line = f"+ [{label}] {ok_msg} ({ok})"
                elif already:
                    line = f"- [{label}] {already_msg} (الكل مأخوذ من قبل)"
                elif other:
                    line = f"- [{label}] {already_msg} (رمز: {', '.join(str(c) for c in other)})"
                else:
                    line = f"- [{label}] لا يوجد رد من السيرفر"
                results.append(line)
                log(f"[DAILY][RESULT] {line}")
                return ok > 0

            async def _tap(tag: str, wait: float = 1.2):
                import time as _time
                end = _time.monotonic() + max(0.2, wait)
                ops = []
                while True:
                    remain = end - _time.monotonic()
                    if remain <= 0:
                        break
                    try:
                        hdr = await asyncio.wait_for(reader.readexactly(2), timeout=remain)
                    except Exception:
                        break
                    plen = (hdr[0] << 8) | hdr[1]
                    try:
                        rpay = c_rx.decrypt(await asyncio.wait_for(reader.readexactly(plen), timeout=2.0))
                    except Exception:
                        break
                    try:
                        zi = rpay.find(b"\x78\x9c")
                        if zi == -1:
                            zi = rpay.find(b"\x78\x01")
                        decomp = zlib.decompress(rpay[zi:]) if zi != -1 else rpay
                        msg = ProtobufCodec.decode_message(decomp)
                        for sub in _collect(msg):
                            op = sub.get(1)
                            if op is None:
                                continue
                            detail = {"op": int(op)}
                            try:
                                p = sub.get(2)
                                if isinstance(p, (bytes, bytearray)) and p:
                                    pm = ProtobufCodec.decode_message(p)
                                    detail["payload"] = repr(pm)[:220]
                                    if int(op) == 204 and isinstance(pm, dict) and isinstance(pm.get(1), list):
                                        # خام المهام ليتم فحص تقدّمها ثم المطالبة بها
                                        detail["entries"] = [e for e in pm[1] if isinstance(e, (bytes, bytearray))]
                                    if int(op) == 1 and isinstance(pm, dict) \
                                            and isinstance(pm.get(1), int) and isinstance(pm.get(2), int):
                                        if pm.get(2) == 1:
                                            acked.setdefault(tag, []).append(pm[1])
                                            log(f"[DAILY][ACK] {tag} -> server accepted request {pm[1]} (code 1 = OK)")
                                        else:
                                            rejected.setdefault(tag, []).append((pm[1], pm[2]))
                                            log(f"[DAILY][REJECT] {tag} -> server refused request {pm[1]} (code {pm[2]})")
                            except Exception:
                                pass
                            ops.append(detail)
                    except Exception:
                        pass
                wire_seen[tag] = ops
                if ops:
                    uniq = sorted({d["op"] for d in ops})
                    log(f"[DAILY][WIRE] {tag} -> server answered opcodes {uniq}")
                    for d in ops[:8]:
                        if "payload" in d:
                            log(f"[DAILY][WIRE]   ↳ op={d['op']} payload={d['payload']}")
                else:
                    log(f"[DAILY][WIRE] {tag} -> no server response (packet likely ignored/rejected)")
                return ops

            # ---------------------------------------------------------
            # ROUTINE 1: VIP Points & Free Chest (Opcode 7600, 8602, 8601)
            # ---------------------------------------------------------
            if cfg.get("daily_vip_claim", True):
                log("[DAILY] Syncing VIP & claiming daily free chest...")
                pkt7600 = ProtobufCodec.encode_message({1: OP_VIP_SYNC, 2: cls.build_simple_ack(1)})
                pkt8602 = ProtobufCodec.encode_message({1: OP_VIP_POINTS, 2: cls.build_simple_ack(1)})
                pkt8601 = ProtobufCodec.encode_message({1: OP_VIP_CHEST, 2: cls.build_simple_ack(1)})
                writer.write(FrameParser.build_frame(c_tx.encrypt(pkt7600)))
                writer.write(FrameParser.build_frame(c_tx.encrypt(pkt8602)))
                writer.write(FrameParser.build_frame(c_tx.encrypt(pkt8601)))
                await writer.drain()
                routines_run.append("daily_vip_claim")
                await _tap("VIP 7600/8602/8601")
                _judge("VIP 7600/8602/8601", "VIP",
                       ok_msg="تم استلام نقاط VIP اليوم وفتح الصندوق اليومي والحصول على المكافأة",
                       already_msg="نقاط VIP والصندوق اليومي مأخوذة من قبل")
                await asyncio.sleep(0.5)

            # ---------------------------------------------------------
            # ROUTINE 2: City Resource Harvesting (Opcode 120)
            # ---------------------------------------------------------
            if cfg.get("city_harvest", True):
                log("[DAILY] Harvesting city resource buildings...")
                CITY_RESOURCE_BUILDINGS = [
                    59, 62, 63, 68, 71, 72, 74, 77, 79, 81, 82,
                    197, 199, 200, 201, 203, 205
                ]
                for b_id in CITY_RESOURCE_BUILDINGS:
                    # الالتقاط الرسمي يرسل معرّف المبنى كأحرف ASCII
                    # (`120 p2=0a023739` = {1: b"79"}) وليس كرقم (varint)،
                    # والصيغة الرقمية تُتجاهل من السيرفر بلا رد.
                    h_pkt = ProtobufCodec.encode_message({
                        1: OP_CITY_HARVEST,
                        2: ProtobufCodec.encode_message({1: str(b_id).encode("ascii")})
                    })
                    writer.write(FrameParser.build_frame(c_tx.encrypt(h_pkt)))
                    await writer.drain()
                    await asyncio.sleep(0.12)
                routines_run.append("city_harvest")
                await _tap("CITY HARVEST 120", wait=3.0)
                _judge("CITY HARVEST 120", "الحصاد",
                       ok_msg="تم حصاد إنتاج المدينة ({n} مبنى يعيد السيرفر 121/122)",
                       already_msg="تعذر حصاد مباني المدينة",
                       require_op=(121, 122))
                await asyncio.sleep(1.0)

            # ---------------------------------------------------------
            # ROUTINE 3: Kingdom Chronicle / Monument (Opcode 3535)
            # ---------------------------------------------------------
            if cfg.get("chronicle_claim", False):
                log("[DAILY] Claiming chronicle chapter rewards...")
                # الالتقاط الحيّ أثبت أن الحقل 1 = رقم الحاكم (role id) وليس رقم ثابت
                c_pkt = ProtobufCodec.encode_message({
                    1: OP_CHRONICLE_CLAIM,
                    2: ProtobufCodec.encode_message({1: int(target_role_id), 2: 11543, 3: 1})
                })
                writer.write(FrameParser.build_frame(c_tx.encrypt(c_pkt)))
                await writer.drain()
                routines_run.append("chronicle_claim")
                await _tap("CHRONICLE 3535", wait=3.0)
                _judge("CHRONICLE 3535", "سجل المملكة",
                       ok_msg="تم استلام مكافآت سجل المملكة (3536)",
                       already_msg="مكافآت السجل مأخوذة من قبل")
                await asyncio.sleep(0.5)

            # ---------------------------------------------------------
            # ROUTINE 4: Daily Quest Activity Chests (Opcode 143, 144)
            # ---------------------------------------------------------
            if cfg.get("claim_daily_quest_chests", True):
                log("[DAILY] Sweeping daily quest activity chests (Opcode 143/144)...")
                # المعرّفات ديناميكية لكل حاكم/فترة، لذا نمسح مجموعة مرشّحة
                # والسيرفر يرد code=1 (استُلم) أو 157/2 (غير متاح / مأخوذ من قبل).
                # 439 و1100002 مثبتة من الالتقاط الرسمي (اومر المهام الريسئه:
                # 143 p2=08b703 و08e29143 بجانب 533 tagclick_quest1).
                chest_ids = list(range(1, 16)) + [439, 6144, 6719, 6742, 6743, 6744, 6745, 10130, 1100002]
                for mid in chest_ids:
                    q143 = ProtobufCodec.encode_message({1: OP_QUEST_CHEST_143, 2: cls.build_simple_ack(mid)})
                    writer.write(FrameParser.build_frame(c_tx.encrypt(q143)))
                for mid in (91, 92):
                    q144 = ProtobufCodec.encode_message({1: OP_QUEST_CHEST_144, 2: cls.build_simple_ack(mid)})
                    writer.write(FrameParser.build_frame(c_tx.encrypt(q144)))
                await writer.drain()
                routines_run.append("claim_daily_quest_chests")
                await _tap("QUEST CHESTS 143/144", wait=4.5)
                _judge_counts("QUEST CHESTS 143/144", "صناديق المهام",
                              ok_msg="تم استلام صناديق نشاط المهام",
                              already_msg="لا توجد صناديق جديدة",
                              already_codes=(157, 2))
                await asyncio.sleep(0.5)

            # ---------------------------------------------------------
            # ROUTINE 5: Completed Daily Quests (Opcode 203)
            # ---------------------------------------------------------
            if cfg.get("claim_daily_quests", True):
                log("[DAILY] Fetching quest lists (Opcode 203)...")
                try:
                    for cat in QUEST_CATS:
                        writer.write(FrameParser.build_frame(c_tx.encrypt(
                            ProtobufCodec.encode_message({1: OP_QUEST_CLAIM, 2: cls.build_simple_ack(cat)}))))
                    await writer.drain()
                    routines_run.append("claim_daily_quests")
                    await _tap("DAILY QUESTS 203", wait=2.5)

                    done = []
                    for _d in wire_seen.get("DAILY QUESTS 203") or []:
                        for _e in _d.get("entries") or []:
                            _qid, _cur, _tgt = _quest_row(_e)
                            # المهمة المكتملة قد يكون تقدمها أكبر من الهدف (11/10 مثلاً)،
                            # والشرط `==` كان يتخطّى المهام القابلة للمطالبة فعلياً.
                            if _qid is not None and _cur is not None and _tgt is not None \
                                    and _cur >= _tgt and _tgt > 0:
                                done.append((_qid, _e))
                    log(f"[DAILY] Completed quests detected: {len(done)}")

                    if done:
                        for _qid, _entry in done[:60]:
                            writer.write(FrameParser.build_frame(c_tx.encrypt(
                                ProtobufCodec.encode_message({1: OP_QUEST_CLAIM_207, 2: _entry}))))
                            await asyncio.sleep(0.12)
                        await writer.drain()
                        await _tap("DAILY QUESTS 207", wait=max(3.0, 0.25 * len(done)))
                        _judge_counts("DAILY QUESTS 207", "المهام اليومية",
                                      ok_msg="وافق السيرفر على استلام مكافآت المهام المكتملة",
                                      already_msg="لا توجد مهام جديدة للمطالبة",
                                      already_codes=(111, 115, 157, 1004, 1007))
                    else:
                        _line = "- [المهام اليومية] لا توجد مهام مكتملة للمطالبة الآن"
                        results.append(_line)
                        log(f"[DAILY][RESULT] {_line}")
                except Exception as quest_err:
                    log(f"[DAILY] Daily quest claim failed: {quest_err}")
                await asyncio.sleep(0.5)

            # ---------------------------------------------------------
            # ROUTINE 6: Side & Main Quests (Opcode 203 -> 207, fallback 2039)
            # ---------------------------------------------------------
            if cfg.get("claim_side_quests", False):
                log("[DAILY] Claiming side & main quest rewards...")
                try:
                    routines_run.append("claim_side_quests")
                    # 1) اجلب فئات المهام الجانبية المكتشفة حديثًا (9 و12)
                    for cat in SIDE_QUEST_CATS:
                        writer.write(FrameParser.build_frame(c_tx.encrypt(
                            ProtobufCodec.encode_message({1: OP_QUEST_CLAIM,
                                                          2: cls.build_simple_ack(cat)}))))
                    await writer.drain()
                    await _tap("SIDE QUESTS 203", wait=2.2)

                    _done = []
                    for _d in wire_seen.get("SIDE QUESTS 203") or []:
                        for _e in _d.get("entries") or []:
                            _qid, _cur, _tgt = _quest_row(_e)
                            if _qid is not None and _cur is not None and _tgt is not None \
                                    and _cur >= _tgt and _tgt > 0:
                                _done.append(_e)
                    log(f"[DAILY] Side quests completed detected: {len(_done)}")

                    if _done:
                        # 2) المطالبة بالمهمة الخام نفسها عبر 207 (كما يفعل العميل الرسمي)
                        for _entry in _done[:40]:
                            writer.write(FrameParser.build_frame(c_tx.encrypt(
                                ProtobufCodec.encode_message({1: OP_QUEST_CLAIM_207,
                                                              2: _entry}))))
                            await asyncio.sleep(0.12)
                        await writer.drain()
                        await _tap("SIDE QUESTS 207", wait=max(3.0, 0.25 * len(_done)))
                        _judge_counts("SIDE QUESTS 207", "المهام الجانبية",
                                      ok_msg="وافق السيرفر على استلام المهام الجانبية المكتملة",
                                      already_msg="لا توجد مهام جانبية جديدة للمطالبة",
                                      already_codes=(111, 115, 157, 1004, 1007))
                    else:
                        # لا توجد قوائم: اطلب المطالبة الجماعية 2039 (سلوك العميل الرسمي)
                        writer.write(FrameParser.build_frame(c_tx.encrypt(
                            ProtobufCodec.encode_message({1: 2039, 2: cls.build_simple_ack(1)}))))
                        await writer.drain()
                        await _tap("SIDE QUESTS 2039", wait=2.0)
                        _judge_counts("SIDE QUESTS 2039", "المهام الجانبية",
                                      ok_msg="وافق السيرفر على استلام المهام الجانبية المكتملة",
                                      already_msg="لا توجد مهام جانبية جديدة للمطالبة",
                                      already_codes=(1004, 1007, 111, 115))
                except Exception as side_err:
                    log(f"[DAILY] Side quest claim failed: {side_err}")
                await asyncio.sleep(0.5)

            # ---------------------------------------------------------
            # ROUTINE 7: Alliance Help All (Opcode 5501 + panel query 534)
            # ---------------------------------------------------------
            if cfg.get("help_alliance_members", True):
                log("[ALLIANCE] Dispatching 'Help All' for alliance members...")
                # الالتقاط الرسمي (اومار المساعد) يفتح لوحة المساعدة عبر 534
                # قبل الضغط، ثم 5501 {1:1} فيرد 5502. نعيد نفس التسلسل.
                try:
                    writer.write(FrameParser.build_frame(c_tx.encrypt(
                        ProtobufCodec.encode_message({1: 534, 2: b""}))))
                    await writer.drain()
                    await asyncio.sleep(0.6)
                except Exception:
                    pass
                writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: OP_ALLIANCE_HELP, 2: ProtobufCodec.encode_message({1: 1})}))))
                await writer.drain()
                routines_run.append("help_alliance_members")
                await _tap("ALLIANCE HELP 5501")
                _judge("ALLIANCE HELP 5501", "مساعدة التحالف",
                       ok_msg="وافق السيرفر على مساعدة كل أعضاء التحالف (5502)",
                       already_msg="لم يؤكد السيرفر المساعدة",
                       require_op=5502)
                await asyncio.sleep(0.5)

            # ---------------------------------------------------------
            # ROUTINE 8: Alliance Territory Resource Pit (Opcode 3370)
            # ---------------------------------------------------------
            if cfg.get("claim_territory_rss", True):
                log("[ALLIANCE] Claiming alliance territory resource pit...")
                writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: OP_CLAIM_TERRITORY, 2: ProtobufCodec.encode_message({1: 1})}))))
                await writer.drain()
                routines_run.append("claim_territory_rss")
                await _tap("TERRITORY RSS 3370")
                _judge("TERRITORY RSS 3370", "موارد أراضي التحالف",
                       ok_msg="تم استلام موارد بئر أراضي التحالف",
                       already_msg="موارد الأراضي مأخوذة من قبل")
                await asyncio.sleep(0.5)

            # ---------------------------------------------------------
            # ROUTINE 9: Alliance Gifts & Chests (Opcode 3170, 3132)
            # ---------------------------------------------------------
            if cfg.get("claim_gifts", True):
                log("[ALLIANCE] Claiming alliance gifts and chests...")
                # العميل الرسمي يرسل الحمولة فارغة تمامًا (3170/3132 len=5)
                writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: OP_CLAIM_GIFTS, 2: b""}))))
                await asyncio.sleep(0.5)
                writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: OP_CLAIM_GIFT_CHEST, 2: b""}))))
                await writer.drain()
                routines_run.append("claim_gifts")
                await _tap("ALLIANCE GIFTS 3170/3132", wait=2.0)
                _judge_counts("ALLIANCE GIFTS 3170/3132", "هدايا التحالف",
                              ok_msg="تم استلام هدايا وصناديق التحالف",
                              already_msg="لا توجد هدايا جديدة",
                              already_codes=(157, 2, 3054, 321, 322),
                              evidence_op=(3171, 3134))
                await asyncio.sleep(0.5)

            # ---------------------------------------------------------
            # ROUTINE 10: Auto Scout (if enabled)
            # ---------------------------------------------------------
            if cfg.get("auto_scout", True):
                log("[DAILY] Auto-scout routine would run here (placeholder).")
                await asyncio.sleep(0.2)

            answered = {k: v for k, v in wire_seen.items() if v}
            rej_flat = [f"{req}({code})" for lst in rejected.values() for (req, code) in lst]
            log(f"✅ [DAILY_ROUTINES SUCCESS] Routines dispatched: {', '.join(routines_run) or 'none'}")
            for _line in results:
                log(f"[DAILY][SUMMARY] {_line}")
            if rej_flat:
                log(f"[DAILY][REJECT] Server refused {len(rej_flat)} request(s): {', '.join(rej_flat)}")
            return {"success": True, "status": "completed",
                    "routines_run": routines_run,
                    "results": results,
                    "server_responses": {k: sorted({d.get("op") for d in v}) for k, v in answered.items()},
                    "rejected": {k: v for k, v in rejected.items()},
                    "silent_routines": [k for k, v in wire_seen.items() if not v]}

        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


# Helper function for socket_worker compatibility
async def run_daily_routines(
    client,
    vip_chest: bool = True,
    daily_quests: bool = True,
    chronicle: bool = True,
    city_harvest: bool = True
) -> Dict[str, Any]:
    """Legacy sync wrapper for backward compatibility."""
    return {
        "vip_chest": vip_chest,
        "daily_quests": daily_quests,
        "chronicle": chronicle,
        "city_harvest": city_harvest
    }


execute_daily_routines = DailyRoutinesEngine.execute_daily_routines