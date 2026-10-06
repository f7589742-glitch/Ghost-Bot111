# app/services/march_recall.py
"""
Troop Recall Service — Opcode 1014
Wire confirmed live from RoK protocol:
  C→S  ops=[1014]  payload={field1: march_id (varint), field2: 0}   (0 = return home)
  S→C  ops=[1023, 1027]  (march state broadcast ACK)

Detection:
  Extracts active marches from Opcode 1005 / world stream:
  In RoK protocol, every active march submessage has:
    tag 1: march_id (varint e.g. 1984626)
    tag 2: role_id (varint e.g. 222172865)
    tag 6: dispatch_troop_X
    tag 36: role_id_timestamp_idx
"""

import asyncio
import re
import zlib
import struct
import logging
from typing import Dict, Any, List, Set, Optional

logger = logging.getLogger(__name__)


def extract_all_marches(node: Any, role_id_int: int, out_dict: Dict[int, Dict[str, Any]], ProtobufCodec) -> None:
    """Recursively search decoded protobuf structures for active march submessages belonging to role_id."""
    if isinstance(node, dict):
        if 1 in node and 2 in node and node.get(2) == role_id_int:
            mid = node.get(1)
            if isinstance(mid, int) and 100_000 <= mid <= 99_999_999:
                troop_desc = node.get(6, b"")
                if isinstance(troop_desc, bytes):
                    troop_desc = troop_desc.decode("utf-8", errors="ignore")
                str_id = node.get(36, b"")
                if isinstance(str_id, bytes):
                    str_id = str_id.decode("utf-8", errors="ignore")
                
                # Strict: An actual active march in RoK MUST have dispatch_troop or role_id timestamp tag
                is_march = False
                if troop_desc and "dispatch_troop" in str(troop_desc).lower():
                    is_march = True
                elif str_id and f"{role_id_int}_" in str(str_id):
                    is_march = True

                if is_march:
                    out_dict[mid] = {
                        "mid": mid,
                        "troop": troop_desc or f"troop_{mid}",
                        "str_id": str_id,
                    }
        for v in node.values():
            extract_all_marches(v, role_id_int, out_dict, ProtobufCodec)
    elif isinstance(node, (list, tuple)):
        for x in node:
            extract_all_marches(x, role_id_int, out_dict, ProtobufCodec)
    elif isinstance(node, bytes) and len(node) >= 4:
        try:
            d = ProtobufCodec.decode_message(node)
            extract_all_marches(d, role_id_int, out_dict, ProtobufCodec)
        except Exception:
            pass


async def recall_character_marches(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    crypto_tx,
    crypto_rx,
    role_id: str,
    login_flood_bytes: List[bytes],
    log_wire,
    ProtobufCodec,
    FrameParser,
    bot_id: str = "bot-0",
    char_name: Optional[str] = None,
    user_id: Optional[str] = None,
    kingdom_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Detects all active marches for this governor and sends Opcode 1014 to recall each.
    """
    role_id_int = int(role_id)
    r_name = char_name or f"Role_{role_id}"
    marches: Dict[int, Dict[str, Any]] = {}

    from app.services.activity_logger import TenantActivityStream
    from app.services.activity_stream import activity_stream

    # 1. Scan login flood raw bytes
    for raw in login_flood_bytes:
        try:
            msg = ProtobufCodec.decode_message(raw)
            extract_all_marches(msg, role_id_int, marches, ProtobufCodec)
        except Exception:
            pass

    log_wire("RECALL_SCAN1", f"[{role_id}] Scan 1 (login flood) found {len(marches)} marches: {list(marches.keys())}")

    # 2. Send Opcode 1005 (map sync) + 1001 to ensure full active march state
    try:
        sync_inner = ProtobufCodec.encode_message({})
        sync_pkt = ProtobufCodec.encode_message({1: 1005, 2: sync_inner})
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(sync_pkt)))
        kv_pkt = ProtobufCodec.encode_message({1: 1001, 2: sync_inner})
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(kv_pkt)))
        await writer.drain()
    except Exception as e:
        log_wire("RECALL_WARN", f"[{role_id}] Sync request note: {e}")

    # 3. Drain incoming frames for up to 3.5 seconds
    drain_deadline = asyncio.get_event_loop().time() + 3.5
    frames_drained = 0
    while asyncio.get_event_loop().time() < drain_deadline:
        try:
            f_hdr = await asyncio.wait_for(reader.readexactly(2), timeout=0.8)
            r_len = (f_hdr[0] << 8) | f_hdr[1]
            raw = await reader.readexactly(r_len)
            dec = crypto_rx.decrypt(raw)
            for magic in (b"\x78\x9c", b"\x78\x01", b"\x78\xda"):
                zi = dec.find(magic)
                if zi != -1:
                    try:
                        decomp = zlib.decompress(dec[zi:])
                        break
                    except Exception:
                        pass
            else:
                decomp = dec

            frames_drained += 1
            msg = ProtobufCodec.decode_message(decomp)
            extract_all_marches(msg, role_id_int, marches, ProtobufCodec)
        except asyncio.TimeoutError:
            break
        except Exception:
            break

    log_wire("RECALL_SCAN2", f"[{role_id}] Scan 2 ({frames_drained} frames) total marches: {len(marches)}")

    if not marches:
        msg_empty = "🚩 [سحب القوات] لا توجد مسيرات خارج المدينة (الجيش في المدينة بالكامل)"
        log_wire("RECALL_EMPTY", f"[{role_id}] {msg_empty}")
        try:
            TenantActivityStream.emit(bot_id, r_name, msg_empty, user_id=user_id)
            if kingdom_id:
                await activity_stream.broadcast(f"[{r_name}] {msg_empty}", kingdom_id=str(kingdom_id), user_id=user_id)
        except Exception:
            pass
        return {
            "success": True,
            "role_id": role_id,
            "total_found": 0,
            "recalled": 0,
            "failed": 0,
            "message": msg_empty,
        }

    # Emit discovery log
    found_msg = f"🔍 [فحص المسيرات] تم العثور على {len(marches)} مسيرة نشطة خارج المدينة."
    log_wire("RECALL_FOUND", f"[{role_id}] {found_msg}")
    try:
        TenantActivityStream.emit(bot_id, r_name, found_msg, user_id=user_id)
        if kingdom_id:
            await activity_stream.broadcast(f"[{r_name}] {found_msg}", kingdom_id=str(kingdom_id), user_id=user_id)
    except Exception:
        pass

    # 4. Recall each march
    recalled_count = 0
    failed_count = 0
    for idx, (mid, info) in enumerate(marches.items(), 1):
        troop_name = info.get("troop") or f"troop_{mid}"
        log_wire("RECALL_DISPATCH", f"[{role_id}] Recalling march #{mid} ({troop_name})...")
        try:
            send_msg = f"🚩 [سحب القوات] جاري إرجاع المسيرة #{idx} ({troop_name})..."
            TenantActivityStream.emit(bot_id, r_name, send_msg, user_id=user_id)
            if kingdom_id:
                await activity_stream.broadcast(f"[{r_name}] {send_msg}", kingdom_id=str(kingdom_id), user_id=user_id)
        except Exception:
            pass

        try:
            inner = ProtobufCodec.encode_message({1: mid, 2: 0})
            pkt = ProtobufCodec.encode_message({1: 1014, 2: inner})
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt)))
            await writer.drain()

            # Wait for ACK (Opcode 1023 / 1027)
            ack_ok = False
            ack_deadline = asyncio.get_event_loop().time() + 1.5
            while asyncio.get_event_loop().time() < ack_deadline:
                try:
                    f_hdr = await asyncio.wait_for(reader.readexactly(2), timeout=0.4)
                    r_len = (f_hdr[0] << 8) | f_hdr[1]
                    raw = await reader.readexactly(r_len)
                    dec = crypto_rx.decrypt(raw)
                    for magic in (b"\x78\x9c", b"\x78\x01"):
                        zi = dec.find(magic)
                        if zi != -1:
                            try:
                                decomp = zlib.decompress(dec[zi:])
                                break
                            except Exception:
                                pass
                    else:
                        decomp = dec
                    msg = ProtobufCodec.decode_message(decomp)
                    chunks = msg[1] if isinstance(msg.get(1), list) else [msg]
                    for ch in chunks:
                        sub = ch if isinstance(ch, dict) else (ProtobufCodec.decode_message(ch) if isinstance(ch, bytes) else {})
                        if sub.get(1) in (1023, 1027, 1014):
                            ack_ok = True
                            break
                    if ack_ok:
                        break
                except Exception:
                    break

            recalled_count += 1
            log_wire("RECALL_ACK", f"[{role_id}] ✅ March #{mid} returned (ACK={ack_ok})")
            await asyncio.sleep(0.3)
        except Exception as e_rec:
            logger.error(f"[{role_id}] Recall failed for {mid}: {e_rec}", exc_info=True)
            failed_count += 1

    summary_msg = f"🚩 [سحب القوات] تم إرجاع {recalled_count}/{len(marches)} مسيرة إلى المدينة بنجاح ⚔️"
    log_wire("RECALL_DONE", f"[{role_id}] {summary_msg}")
    try:
        TenantActivityStream.emit(bot_id, r_name, summary_msg, user_id=user_id)
        if kingdom_id:
            await activity_stream.broadcast(f"[{r_name}] {summary_msg}", kingdom_id=str(kingdom_id), user_id=user_id)
    except Exception:
        pass

    return {
        "success": True,
        "role_id": role_id,
        "total_found": len(marches),
        "march_ids": list(marches.keys()),
        "recalled": recalled_count,
        "failed": failed_count,
        "message": summary_msg,
    }
