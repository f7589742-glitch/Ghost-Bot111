"""
app/services/alliance_donation.py — Pure Headless Alliance Technology Donation Engine
Rise of Kingdoms Headless Bot — Opcode 2080 & 2078

- Opcode 2077 -> request alliance tech state
- Opcode 2078 -> response: Tag 2 = officer recommended tech_id, Tag 1 = list of tech nodes
- Opcode 2080 -> donate: Tag1 tech_id, Tag2 current_level, Tag3 donate_type=1 (Resources ONLY, NEVER 2 gems), Tag4 count=1
  Wire hex: 200108cc0110031801 (204=Officer Recommended)
- Opcode 2081 -> ACK success
Strictly zero gems, falls back to random non-maxed tech if recommended is completed/under-research or missing.
Integrated with TaskLogDAO + activity_stream for dashboard binding.
"""

import asyncio
import time
import zlib
import random
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("AllianceDonation")

# Robust imports for headless_client
try:
    from headless_client import ProtobufCodec, FrameParser
except ImportError:
    try:
        from python.headless_client import ProtobufCodec, FrameParser
    except ImportError:
        import sys, os
        _bd = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if _bd not in sys.path:
            sys.path.insert(0, _bd)
            sys.path.insert(0, os.path.join(_bd, "python"))
        from headless_client import ProtobufCodec, FrameParser

async def execute_alliance_donation(writer, reader, crypto_tx, crypto_rx, role_id: int, char_name: str, max_donations: int = 20) -> int:
    print(f"[ALLIANCE] Initiating tech donation for {char_name} (Role {role_id})...")
    try:
        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({1: 2077, 2: b""}))))
        await writer.drain()
        print(f"[ALLIANCE] Sent Opcode 2077 tech state request")
    except Exception as e:
        print(f"[ALLIANCE] Failed to send 2077: {e}")
    recommended_tech_id = 0
    tech_levels: Dict[int, int] = {}
    tech_maxed: Dict[int, bool] = {}
    start_wait = time.time()
    got_state = False
    while time.time() - start_wait < 3.5:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.5)
            rl = (rh[0] << 8) | rh[1]
            raw_b = await asyncio.wait_for(reader.readexactly(rl), timeout=0.5)
            dec = crypto_rx.decrypt(raw_b)
            z_idx = dec.find(b"\x78\x9c")
            if z_idx == -1:
                z_idx = dec.find(b"\x78\x01")
            data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
            try:
                m = ProtobufCodec.decode_message(data)
            except Exception:
                continue
            chunks = m.get(1) if isinstance(m.get(1), list) else [m]
            if isinstance(m.get(1), bytes):
                chunks = [m.get(1)]
            if not isinstance(chunks, list):
                chunks = [chunks]
            for c in chunks:
                try:
                    item = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                except Exception:
                    continue
                if not isinstance(item, dict):
                    continue
                op = item.get(1)
                if isinstance(op, bytes) and op.isdigit():
                    try:
                        op = int(op)
                    except: pass
                if op not in (2078, 1205, 904, 1203):
                    continue
                if op == 2078:
                    p2_raw = item.get(2, b"")
                    try:
                        p2 = ProtobufCodec.decode_message(p2_raw) if isinstance(p2_raw, bytes) else p2_raw
                    except Exception:
                        p2 = {}
                    if not isinstance(p2, dict):
                        continue
                    rec = p2.get(2, 0)
                    if isinstance(rec, int) and rec > 0:
                        recommended_tech_id = rec
                    nodes = p2.get(1, [])
                    if not isinstance(nodes, list):
                        nodes = [nodes]
                    for nd_bytes in nodes:
                        try:
                            nd = ProtobufCodec.decode_message(nd_bytes) if isinstance(nd_bytes, bytes) else nd_bytes
                        except Exception:
                            continue
                        if not isinstance(nd, dict):
                            continue
                        t_id = nd.get(1)
                        t_lvl = nd.get(2, 1)
                        if isinstance(t_id, int) and t_id > 0:
                            tech_levels[t_id] = int(t_lvl) if isinstance(t_lvl, int) else 1
                            tech_maxed[t_id] = False
                    got_state = True
                    print(f"[ALLIANCE] Received Opcode 2078: recommended={recommended_tech_id} nodes={len(tech_levels)}")
                elif op in (904, 1205):
                    try:
                        p2_raw = item.get(2, b"")
                        sub = ProtobufCodec.decode_message(p2_raw) if isinstance(p2_raw, bytes) else p2_raw
                        def search_alliance(obj):
                            if isinstance(obj, dict):
                                for k,v in obj.items():
                                    if isinstance(v, bytes) and b"alliance_technique" in v:
                                        try:
                                            s = v.decode("utf-8", "ignore")
                                            if "alliance_technique" in s:
                                                parts = s.split(".")
                                                for part in parts:
                                                    if part.isdigit():
                                                        tid = int(part)
                                                        if 1 <= tid <= 9999 and tid not in tech_levels:
                                                            tech_levels[tid] = 1
                                        except: pass
                                    elif isinstance(v, (dict, list)):
                                        search_alliance(v)
                                    elif isinstance(v, bytes):
                                        try:
                                            dec = ProtobufCodec.decode_message(v)
                                            search_alliance(dec)
                                        except: pass
                            elif isinstance(obj, list):
                                for it in obj:
                                    search_alliance(it)
                        search_alliance(sub)
                    except: pass
            if got_state and recommended_tech_id:
                break
            if got_state and tech_levels:
                if time.time() - start_wait > 1.5:
                    break
        except asyncio.TimeoutError:
            continue
        except asyncio.IncompleteReadError:
            break
        except Exception:
            continue
    target_tech_id = 0
    target_level = 1
    is_recommended = False
    if recommended_tech_id and recommended_tech_id in tech_levels:
        lvl = tech_levels.get(recommended_tech_id, 1)
        if tech_maxed.get(recommended_tech_id, False):
            print(f"[ALLIANCE] Recommended Tech #{recommended_tech_id} is completed/maxed -> fallback to random")
        else:
            target_tech_id = recommended_tech_id
            target_level = lvl
            is_recommended = True
    elif recommended_tech_id and recommended_tech_id not in tech_levels and recommended_tech_id > 0:
        target_tech_id = recommended_tech_id
        target_level = 1
        is_recommended = True
        print(f"[ALLIANCE] Recommended Tech #{recommended_tech_id} not in catalog but will attempt (officer star)")
    if not target_tech_id:
        candidates = [tid for tid, lvl in tech_levels.items() if not tech_maxed.get(tid, False)]
        if not candidates:
            candidates = list(tech_levels.keys())
        if candidates:
            target_tech_id = random.choice(candidates)
            target_level = tech_levels.get(target_tech_id, 1)
            print(f"[ALLIANCE] Fallback random tech #{target_tech_id} (Lv {target_level}) from {len(candidates)} candidates")
        else:
            target_tech_id = recommended_tech_id if recommended_tech_id else 204
            target_level = tech_levels.get(target_tech_id, 1)
            print(f"[ALLIANCE] Ultimate fallback Tech #{target_tech_id}")
    if not target_tech_id:
        target_tech_id = 204
        target_level = 1
    print(f"[ALLIANCE] Selected Tech Node #{target_tech_id} (Level {target_level}) | Recommended by Officer: {is_recommended} | Catalog {len(tech_levels)} techs")
    donations_done = 0
    total_score = 0
    tried_techs = set([target_tech_id])
    current_tech = target_tech_id
    current_level = target_level
    ack_crit = 1
    for i in range(max_donations):
        donate_type = 1
        assert donate_type == 1, "CRITICAL: donate_type must be 1 (resources), never 2 (gems)!"
        body = (
            ProtobufCodec.encode_field_varint(4, 1)
            + ProtobufCodec.encode_field_varint(1, int(current_tech))
            + ProtobufCodec.encode_field_varint(2, int(current_level))
            + ProtobufCodec.encode_field_varint(3, 1)
        )
        pkt_2080 = ProtobufCodec.encode_message({1: 2080, 2: body})
        try:
            writer.write(FrameParser.build_frame(crypto_tx.encrypt(pkt_2080)))
            await writer.drain()
        except Exception as e:
            print(f"[ALLIANCE] Write failed: {e}")
            break
        got_ack = False
        got_limit = False
        got_need_research = False
        ack_score = 0
        ack_crit_tmp = 1
        wait_ack = time.time()
        while time.time() - wait_ack < 1.6:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.35)
                rl = (rh[0] << 8) | rh[1]
                raw_b = await asyncio.wait_for(reader.readexactly(rl), timeout=0.35)
                dec = crypto_rx.decrypt(raw_b)
                z_idx = dec.find(b"\x78\x9c")
                if z_idx == -1:
                    z_idx = dec.find(b"\x78\x01")
                data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
                try:
                    m = ProtobufCodec.decode_message(data)
                except Exception:
                    continue
                chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                if isinstance(m.get(1), bytes):
                    chunks = [m.get(1)]
                if not isinstance(chunks, list):
                    chunks = [chunks]
                for c in chunks:
                    try:
                        item = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                    except Exception:
                        continue
                    if not isinstance(item, dict):
                        continue
                    op = item.get(1)
                    if isinstance(op, bytes) and op.isdigit():
                        try: op = int(op)
                        except: pass
                    if op == 2081:
                        got_ack = True
                        p2_ack_raw = item.get(2, b"")
                        try:
                            p2_ack = ProtobufCodec.decode_message(p2_ack_raw) if isinstance(p2_ack_raw, bytes) else p2_ack_raw
                        except:
                            p2_ack = {}
                        if isinstance(p2_ack, dict):
                            ack_score = p2_ack.get(7, p2_ack.get(4, p2_ack.get(2, 100)))
                            ack_crit_tmp = p2_ack.get(6, p2_ack.get(3, 1))
                        if not isinstance(ack_score, int):
                            ack_score = 100
                        if not isinstance(ack_crit_tmp, int):
                            ack_crit_tmp = 1
                        total_score += int(ack_score) if isinstance(ack_score, int) else 100
                        ack_crit = ack_crit_tmp
                        break
                    elif op == 1:
                        p2_err_raw = item.get(2, b"")
                        try:
                            p2_err = ProtobufCodec.decode_message(p2_err_raw) if isinstance(p2_err_raw, bytes) else p2_err_raw
                        except:
                            p2_err = {}
                        if isinstance(p2_err, dict) and p2_err.get(1) == 2080:
                            code = p2_err.get(2, 0)
                            if code != 1:
                                print(f"[ALLIANCE] Donation limit/cooldown or tech unavailable (code {code}) for Tech #{current_tech}")
                                if i == 0 and donations_done == 0 and len(tech_levels) > 1:
                                    others = [t for t in tech_levels.keys() if t not in tried_techs]
                                    if others:
                                        new_tech = random.choice(others)
                                        tried_techs.add(new_tech)
                                        print(f"[ALLIANCE] Tech #{current_tech} unavailable -> switching to random Tech #{new_tech}")
                                        current_tech = new_tech
                                        current_level = tech_levels.get(new_tech, 1)
                                        got_need_research = True
                                        break
                                got_limit = True
                                break
                        elif isinstance(p2_err, dict) and p2_err.get(2) not in (None, 1):
                            got_limit = True
                            break
                    elif op in (2088, 121, 9104):
                        continue
                if got_ack or got_limit or got_need_research:
                    break
            except asyncio.TimeoutError:
                continue
            except asyncio.IncompleteReadError:
                break
            except Exception:
                break
        if got_need_research:
            continue
        if got_ack:
            donations_done += 1
            crit_str = f" CRIT x{ack_crit_tmp}" if ack_crit_tmp and ack_crit_tmp > 1 else ""
            print(f"[ALLIANCE] Donation {donations_done}/{max_donations} to Tech #{current_tech} OK{crit_str} (+{ack_score} score)")
            await asyncio.sleep(0.35)
        elif got_limit:
            print(f"[ALLIANCE] Donation stopped: limit/cooldown reached after {donations_done} donations")
            break
        else:
            print(f"[ALLIANCE] No ACK for Tech #{current_tech} donation #{i+1} -> stopping")
            break
    print(f"[ALLIANCE] Completed {donations_done} donations for Tech #{current_tech} (Total Score: {total_score}) Recommended={is_recommended}")
    if donations_done > 0:
        char_pfx = f"[{char_name}] " if char_name else ""
        dash_msg = f"{char_pfx}Donated {donations_done}x to Alliance Tech #{current_tech} (Lv {current_level}) - Score: +{total_score:,}"
        if ack_crit and ack_crit > 1:
            dash_msg += f" (Crit x{ack_crit})"
        if not is_recommended:
            dash_msg += " [Random fallback]"
        try:
            from app.models import TaskLogDAO, CharacterDAO
            db_c = CharacterDAO.get_by_role_id(str(role_id))
            TaskLogDAO.create(
                task_id=f"donate_{role_id}_{int(time.time())}",
                role_id=str(role_id),
                task_type="alliance_donation",
                status="SUCCESS",
                details={
                    "message": dash_msg,
                    "character_name": char_name,
                    "tech_id": int(current_tech),
                    "tech_level": int(current_level),
                    "donations_count": int(donations_done),
                    "score": int(total_score),
                    "recommended": bool(is_recommended),
                    "crit": int(ack_crit) if isinstance(ack_crit, int) else 1
                },
                character_id=int(db_c["id"]) if db_c and db_c.get("id") else None
            )
            try:
                from app.services.activity_stream import activity_stream
                import asyncio as _aio
                _aio.create_task(activity_stream.broadcast(dash_msg, user_id=""))
            except Exception:
                pass
            # Clean per-bot telemetry hook (official vocabulary)
            try:
                from app.services.activity_logger import clean_activity
                clean_activity.emit("", char_name, f"Donated {donations_done}x to alliance tech")
            except Exception:
                pass
        except Exception as e_log:
            print(f"[-] TaskLog write notice: {e_log}")
    return donations_done

async def donate_to_recommended_tech(*args, **kwargs):
    return await execute_alliance_donation(*args, **kwargs)
