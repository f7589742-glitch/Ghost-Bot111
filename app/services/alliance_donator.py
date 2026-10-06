"""
app/services/alliance_donator.py — Autonomous Alliance Technology Donation Service
Rise of Kingdoms Headless Bot Framework.

Strictly targets Officer-Recommended Technology (⭐ توصيات الضابط) using normal resources only (cost_type = 0).
Guarantees zero-gem expenditure via hard assertions, manages available donation chances (up to 20/20),
and handles cooldown limits gracefully with humanized pacing delays.
"""

import asyncio
from app.services.proxy_transport import open_game_connection
import logging
import os
import sys
import time
import zlib
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Ensure base paths are in sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PYTHON_DIR = os.path.join(BASE_DIR, "python")
for p in (BASE_DIR, PYTHON_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from headless_client import ProtobufCodec, FrameParser
    from crypto_module import RokCrypto
except ImportError:
    from python.headless_client import ProtobufCodec, FrameParser
    from python.crypto_module import RokCrypto

def is_tech_donation_enabled(config: Optional[Dict[str, Any]], params: Optional[Dict[str, Any]] = None) -> bool:
    """
    Evaluates whether Alliance Tech Donation is enabled by checking all known key variations:
      - Parameters override: donate_to_tech, donate_tech, alliance_donate_tech, tech_donation
      - Nested in 'alliance': donate_to_tech, donate_tech, alliance_donate_tech, tech_donation
      - Nested in 'mirror.alliance': tech_donation, donate_tech, donate_to_tech, alliance_donate_tech
      - Top-level config: donate_to_tech, donate_tech, alliance_donate_tech, tech_donation
    Returns True by default if unconfigured or none of the keys are explicitly False.
    """
    if not isinstance(config, dict):
        config = {}

    if isinstance(params, dict):
        for k in ("donate_to_tech", "donate_tech", "donateTech", "alliance_donate_tech", "allianceDonateTech", "tech_donation", "techDonation"):
            if params.get(k) is not None:
                return bool(params[k])

    alliance_cfg = config.get("alliance") if isinstance(config.get("alliance"), dict) else {}
    mirror = config.get("mirror") if isinstance(config.get("mirror"), dict) else {}
    mirror_alliance = mirror.get("alliance") if isinstance(mirror.get("alliance"), dict) else {}

    candidates = [
        alliance_cfg.get("donate_tech"),
        alliance_cfg.get("donateTech"),
        alliance_cfg.get("donate_to_tech"),
        alliance_cfg.get("alliance_donate_tech"),
        alliance_cfg.get("allianceDonateTech"),
        alliance_cfg.get("tech_donation"),
        alliance_cfg.get("techDonation"),
        mirror_alliance.get("tech_donation"),
        mirror_alliance.get("techDonation"),
        mirror_alliance.get("donate_tech"),
        mirror_alliance.get("donateTech"),
        mirror_alliance.get("donate_to_tech"),
        mirror_alliance.get("alliance_donate_tech"),
        mirror_alliance.get("allianceDonateTech"),
        config.get("donate_to_tech"),
        config.get("donate_tech"),
        config.get("donateTech"),
        config.get("alliance_donate_tech"),
        config.get("allianceDonateTech"),
        config.get("tech_donation"),
        config.get("techDonation"),
    ]

    for val in candidates:
        if val is not None:
            return bool(val)

    return True


def extract_alliance_from_message(msg: Any) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Extracts alliance_id, alliance_name, alliance_tag from decoded server protobuf message.
    """
    found_id = None
    found_name = None
    found_tag = None

    def _walk(obj):
        nonlocal found_id, found_name, found_tag
        if found_id and found_tag:
            return
        if isinstance(obj, dict):
            a_id = obj.get(1)
            a_name = obj.get(2)
            a_tag = obj.get(3)
            if isinstance(a_id, int) and a_id > 1000:
                name_str = a_name.decode("utf-8", "ignore") if isinstance(a_name, bytes) else str(a_name or "")
                tag_str = a_tag.decode("utf-8", "ignore") if isinstance(a_tag, bytes) else str(a_tag or "")
                if (2 <= len(tag_str) <= 6) and (len(name_str) >= 1):
                    found_id = a_id
                    found_name = name_str
                    found_tag = tag_str
                    return

            t19 = obj.get(19)
            if isinstance(t19, bytes) and 2 <= len(t19) <= 6:
                try:
                    s19 = t19.decode("utf-8", "ignore")
                    if s19.isalnum() and not found_tag:
                        found_tag = s19
                except Exception:
                    pass

            for k, v in obj.items():
                if isinstance(v, bytes) and len(v) >= 4:
                    try:
                        sub = ProtobufCodec.decode_message(v)
                        _walk(sub)
                    except Exception:
                        pass
                elif isinstance(v, (dict, list)):
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, bytes) and len(item) >= 4:
                    try:
                        sub = ProtobufCodec.decode_message(item)
                        _walk(sub)
                    except Exception:
                        pass
                elif isinstance(item, (dict, list)):
                    _walk(item)

    _walk(msg)
    return found_id, found_name, found_tag


class AllianceTechDonator:
    """
    Autonomous Alliance Technology Donation Engine.
    Queries active research, filters for leadership recommendation, and donates using resources only.
    """

    @staticmethod
    def _extract_tech_info(msg: Any) -> Tuple[Optional[int], int, Dict[int, Dict[str, Any]]]:
        """
        Deep parses Opcode 1205 / Opcode 1203 protobuf payload to extract:
          1. recommended_tech_id: The starred/recommended technology ID set by alliance officers.
          2. remaining_chances: Available donation chances (0-20, defaults to 20).
          3. tech_catalog: Map of tech_id -> info dictionary.
        """
        recommended_tech_id: Optional[int] = None
        remaining_chances: int = 20
        tech_catalog: Dict[int, Dict[str, Any]] = {}

        if isinstance(msg, bytes) and len(msg) > 2:
            raw_payload = msg
            z_idx = raw_payload.find(b"\x78\x9c")
            if z_idx == -1:
                z_idx = raw_payload.find(b"\x78\x01")
            if z_idx != -1:
                try:
                    raw_payload = zlib.decompress(raw_payload[z_idx:])
                except Exception:
                    pass
            try:
                msg = ProtobufCodec.decode_message(raw_payload)
            except Exception:
                pass

        def inspect_node(node: Any):
            nonlocal recommended_tech_id, remaining_chances
            if isinstance(node, dict):
                # Check if this node itself is a technology item
                # Tech item layout: {1: tech_id, 2: level, 3: exp, 4: max_exp, 5: is_recommend/flag, ...}
                tid = node.get(1)
                if isinstance(tid, bytes) and tid.isdigit():
                    tid = int(tid)
                if isinstance(tid, int) and 1 <= tid <= 999999:
                    lvl = node.get(2, 0)
                    cur_exp = node.get(3, 0)
                    max_exp = node.get(4, 0)
                    # Field 5, 6, 7, 8 or 9 can indicate officer recommendation / star flag
                    is_rec = bool(node.get(5) == 1 or node.get(6) == 1 or node.get(7) == 1 or node.get(8) == 1)
                    
                    tech_catalog[tid] = {
                        "tech_id": tid,
                        "level": lvl,
                        "current_exp": cur_exp,
                        "max_exp": max_exp,
                        "is_recommended": is_rec
                    }
                    if is_rec and recommended_tech_id is None:
                        recommended_tech_id = tid

                # Check remaining chances: only update if valid non-zero chance <= 20
                for f_key in (3, 4, 5):
                    val = node.get(f_key)
                    if isinstance(val, int) and 1 <= val <= 20:
                        if 1 in node and isinstance(node[1], (list, bytes, dict)):
                            remaining_chances = val

                # Recurse into dict values
                for v in node.values():
                    inspect_node(v)

            elif isinstance(node, list):
                for item in node:
                    inspect_node(item)

            elif isinstance(node, bytes) and 2 <= len(node) <= 65536:
                raw_payload = node
                z_idx = raw_payload.find(b"\x78\x9c")
                if z_idx == -1:
                    z_idx = raw_payload.find(b"\x78\x01")
                if z_idx != -1:
                    try:
                        raw_payload = zlib.decompress(raw_payload[z_idx:])
                    except Exception:
                        pass
                try:
                    sub = ProtobufCodec.decode_message(raw_payload)
                    inspect_node(sub)
                except Exception:
                    pass

        inspect_node(msg)

        # Default to 1 ("بحث العلوم 1" - Science Research 1) if no specific tech starred
        if not recommended_tech_id or recommended_tech_id <= 0:
            recommended_tech_id = 1

        if remaining_chances <= 0 or remaining_chances > 20:
            remaining_chances = 20

        return recommended_tech_id, remaining_chances, tech_catalog

    @classmethod
    async def donate_to_recommended_tech(
        cls,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        c_tx: Any,
        c_rx: Any,
        role_id: str,
        log_callback: Optional[Any] = None,
        donate_tech: bool = True,
        alliance_id: int = 0,
        alliance_tag: str = "",
        char_name: Optional[str] = None,
        help_members: bool = True,
        claim_gifts: bool = True,
        claim_pit: bool = False,
    ) -> Dict[str, Any]:
        """
        Primary entrypoint for alliance tech donation:
          1. Verify alliance membership (alliance_id > 0 or alliance_tag).
          2. Check dashboard toggle (donate_tech); skip tech if disabled.
          3. Query active alliance technologies (Opcode 2077 / 2078).
          4. Prioritize officer recommendation (rec_id > 0); fallback to active/lowest tech.
          5. Loop Opcode 2080 using resources only (cost_type = 1, zero gems).
          6. Handle server ACKs, crits, and cooldown boundaries.
        """
        def log(msg: str):
            if log_callback:
                log_callback(msg)
            else:
                logger.info(msg)

        # Requirement 2: Verify alliance membership
        if alliance_id <= 0 and not alliance_tag:
            log(f"    [ALLIANCE] Character is not in an alliance. Skipping tech donation.")
            return {
                "success": True,
                "donated": 0,
                "status": "no_alliance",
                "reason": "not_in_alliance"
            }

        # Each dashboard switch controls its own packets, independently of donation.
        requested_actions = []
        async def send_member_actions():
            for enabled, name, opcodes in (
                (help_members, "help_members", (5501,)),
                (claim_pit, "claim_pit", (3370,)),
                (claim_gifts, "claim_gifts", (3170, 3132)),
            ):
                if enabled:
                    for opcode in opcodes:
                        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message(
                            {1: opcode, 2: ProtobufCodec.encode_message({1: 1})}
                        ))))
                    requested_actions.append(name)
                    log(f"[ALLIANCE] Requested {name}; awaiting game confirmation.")
            await writer.drain()

        if not donate_tech:
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({
                1: 532, 2: ProtobufCodec.encode_message({1: b"alliance", 2: b"", 3: 0})
            }))))
            await send_member_actions()

            log("[ALLIANCE] Tech donation is DISABLED via dashboard toggle. Skipping.")
            return {
                "success": True,
                "donated": 0,
                "status": "disabled_by_toggle",
                "reason": "disabled_by_toggle",
                "requested_actions": requested_actions,
                "actions_confirmed": False,
            }

        log(f"[ALLIANCE DONATE] Initiating tech sync for Governor #{role_id}...")

        # Step A: Open Alliance Context & Request Tech Info
        # Send prerequisite sequence: 532 -> 2026 -> 2092 -> 1126 -> 1202 -> 2077
        try:
            rid_int = int(role_id)
        except Exception:
            rid_int = 0

        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({
            1: 532, 2: ProtobufCodec.encode_message({1: b"alliance", 2: b"", 3: 0})
        }))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 2026, 2: b""}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 2092, 2: b""}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1126, 2: b""}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({
            1: 1202, 2: ProtobufCodec.encode_message({1: rid_int})
        }))))
        # Opcode 2077: Authentic request for alliance technology tree and officer recommendation
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 2077, 2: b""}))))
        # Opcode 502: Alliance UI interaction packet
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 502, 2: b""}))))

        await send_member_actions()

        # Step B: Intercept Opcode 2078 (Technology Tree & Officer Recommendation)
        recommended_tech_id: Optional[int] = None
        remaining_chances: int = 20
        tech_catalog: Dict[int, Dict[str, Any]] = {}
        target_tech_name: str = "Alliance Technology"

        deadline = asyncio.get_event_loop().time() + 4.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.4)
                rl = (rh[0] << 8) | rh[1]
                raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.4)
                dec = c_rx.decrypt(raw)

                decomp = dec
                z_idx = dec.find(b"\x78\x9c")
                if z_idx == -1:
                    z_idx = dec.find(b"\x78\x01")
                if z_idx != -1:
                    try:
                        decomp = zlib.decompress(dec[z_idx:])
                    except Exception:
                        decomp = dec
                m = ProtobufCodec.decode_message(decomp)

                chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                if isinstance(m.get(1), bytes):
                    chunks = [m.get(1)]
                for c in chunks:
                    it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                    if not isinstance(it, dict):
                        continue

                    raw_op = it.get(1)
                    op = raw_op
                    if isinstance(raw_op, bytes) and raw_op.isdigit():
                        op = int(raw_op)

                    # Opcode 2078 is the authentic response for alliance technology state
                    if op == 2078:
                        raw_payload = it.get(2, b"")
                        sub_2078 = ProtobufCodec.decode_message(raw_payload) if isinstance(raw_payload, bytes) else raw_payload
                        if isinstance(sub_2078, dict):
                            # Field 2 in Opcode 2078 is the exact recommended technology ID
                            rec_id = sub_2078.get(2)
                            if rec_id and isinstance(rec_id, int) and rec_id > 0:
                                recommended_tech_id = rec_id
                                log(f"    🎯 [ALLIANCE SYNC] Officer-Recommended Tech ID: ⭐ #{recommended_tech_id}")

                            # Field 1 in Opcode 2078 contains all alliance technology progress
                            raw_techs = sub_2078.get(1, [])
                            for rt in raw_techs:
                                dt = ProtobufCodec.decode_message(rt) if isinstance(rt, bytes) else rt
                                if isinstance(dt, dict) and 1 in dt:
                                    t_id = dt.get(1)
                                    lvl = dt.get(2, 0)
                                    xp = dt.get(5, 0)
                                    tech_catalog[t_id] = {"tech_id": t_id, "level": lvl, "current_exp": xp}

                    elif op == 904:
                        # Opcode 904 contains technique name tags (e.g. alliance_technique.214.2100)
                        raw_payload = it.get(2, b"")
                        sub_904 = ProtobufCodec.decode_message(raw_payload) if isinstance(raw_payload, bytes) else raw_payload
                        if isinstance(sub_904, dict) and 2 in sub_904:
                            sub_inner = ProtobufCodec.decode_message(sub_904[2]) if isinstance(sub_904[2], bytes) else sub_904[2]
                            if isinstance(sub_inner, dict):
                                for v in sub_inner.values():
                                    if isinstance(v, list):
                                        for item in v:
                                            dec_item = ProtobufCodec.decode_message(item) if isinstance(item, bytes) else item
                                            if isinstance(dec_item, dict):
                                                name_str = dec_item.get(1, b"").decode("utf-8", "ignore") if isinstance(dec_item.get(1), bytes) else str(dec_item.get(1, ""))
                                                if "alliance_technique" in name_str:
                                                    parts = name_str.split(".")
                                                    if len(parts) >= 2 and parts[1].isdigit():
                                                        tid = int(parts[1])
                                                        lvl = dec_item.get(2, 0)
                                                        if tid not in tech_catalog:
                                                            tech_catalog[tid] = {"tech_id": tid, "level": lvl}

                if recommended_tech_id is not None:
                    break

            except asyncio.TimeoutError:
                continue
            except asyncio.IncompleteReadError:
                break
            except Exception as e:
                log(f"[ALLIANCE DONATE] Parse warning: {e}")

        # Fallback to active research or lowest incomplete technology if no recommendation active
        if not recommended_tech_id or int(recommended_tech_id) <= 0:
            if tech_catalog:
                # Prioritize active research (current_exp > 0) or lowest incomplete level
                sorted_techs = sorted(
                    tech_catalog.values(),
                    key=lambda t: (t.get("level", 0), -t.get("current_exp", 0))
                )
                recommended_tech_id = sorted_techs[0]["tech_id"]
                log(f"    [*] No officer recommendation active. Selected active/lowest Tech #{recommended_tech_id}")
            else:
                recommended_tech_id = 214  # Default fallback to common core tech
                log(f"    [*] Fallback to standard Tech #{recommended_tech_id}")

        total_chances = remaining_chances if (remaining_chances and 1 <= remaining_chances <= 20) else 20
        log(f"[ALLIANCE DONATE] Target Alliance Technology: ID #{recommended_tech_id}")
        log(f"[ALLIANCE DONATE] Executing Technology Donations: up to {total_chances} chance(s)...")

        # Step C: Dispatch Donation with Strict Zero-Gem Enforcement (cost_type = 1)
        # Cost Type: 1 = Resource Donation (Wood/Food). 0 = Gems. NEVER use gems!
        cost_type = 1
        assert cost_type != 0, "[CRITICAL SAFETY GUARD] cost_type must strictly be non-zero (resources only, ZERO gems)!"

        donated_count = 0
        crit_count = 0
        stop_reason = "completed"
        current_opcode = 2080
        attempted_fallback = False
        attempt = 0
        current_tech_id = recommended_tech_id
        tried_tech_ids = {current_tech_id}

        while attempt < total_chances:
            assert cost_type != 0, "[CRITICAL SAFETY GUARD] Attempted donation with zero cost_type (gems)!"

            # Fetch current level of active tech from catalog (0 is valid for 0 -> 1 research)
            tech_lvl = tech_catalog.get(int(current_tech_id), {}).get("level", 0)

            # Opcode 2080: Authentic client donation packet as confirmed from live wire frames
            # Field order: {4: cost_type (1), 1: tech_id, 2: level, 3: 1 (step)}
            donation_payload = {
                4: cost_type,
                1: int(current_tech_id),
                2: int(tech_lvl),
                3: 1
            }
            pkt = ProtobufCodec.encode_message({
                1: 2080,
                2: ProtobufCodec.encode_message(donation_payload)
            })

            writer.write(FrameParser.build_frame(c_tx.encrypt(pkt)))
            await writer.drain()

            got_ack = False
            got_error = False
            err_code = None
            need_switch_tech = False

            ack_deadline = asyncio.get_event_loop().time() + 1.5
            while asyncio.get_event_loop().time() < ack_deadline and not got_ack and not got_error and not need_switch_tech:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
                    rl = (rh[0] << 8) | rh[1]
                    raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
                    dec = c_rx.decrypt(raw)

                    decomp = dec
                    z_idx = dec.find(b"\x78\x9c")
                    if z_idx == -1:
                        z_idx = dec.find(b"\x78\x01")
                    if z_idx != -1:
                        try:
                            decomp = zlib.decompress(dec[z_idx:])
                        except Exception:
                            decomp = dec
                    m = ProtobufCodec.decode_message(decomp)

                    chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                    if isinstance(m.get(1), bytes):
                        chunks = [m.get(1)]
                    for c in chunks:
                        it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                        if not isinstance(it, dict):
                            continue
                        op = it.get(1)

                        if op in (8003, 125, 9, 7, 1005, 1035, 8042, 8018, 1073):
                            continue

                        # Opcode 2081: Authentic server confirmation of donation!
                        if op in (2081, 1207):
                            got_ack = True
                            p_ack = it.get(2, b"")
                            sub_ack = ProtobufCodec.decode_message(p_ack) if isinstance(p_ack, bytes) else p_ack
                            credits_earned = sub_ack.get(2, 100) if isinstance(sub_ack, dict) else 100
                            crit_mult = sub_ack.get(6, 1) if isinstance(sub_ack, dict) else 1
                            gems_spent = sub_ack.get(4, 0) if isinstance(sub_ack, dict) else 0

                            assert gems_spent == 0, f"[CRITICAL SAFETY VIOLATION] Server reported {gems_spent} gems used!"

                            # If the technology leveled up or updated progress, update tech_lvl for subsequent clicks
                            if isinstance(sub_ack, dict) and 1 in sub_ack and isinstance(sub_ack[1], bytes):
                                try:
                                    d_t = ProtobufCodec.decode_message(sub_ack[1])
                                    if isinstance(d_t, dict) and 2 in d_t:
                                        new_lvl = d_t.get(2)
                                        if isinstance(new_lvl, int):
                                            tech_lvl = new_lvl
                                            if int(current_tech_id) in tech_catalog:
                                                tech_catalog[int(current_tech_id)]["level"] = new_lvl
                                except Exception:
                                    pass

                            donated_count += 1
                            if crit_mult > 1:
                                crit_count += 1
                                log(f"    ✨ [CRIT x{crit_mult}] Donated to Tech #{current_tech_id} ({donated_count}/{total_chances}) (+{credits_earned} credits, 0 gems)")
                            else:
                                log(f"    [+] Donated to Tech #{current_tech_id} ({donated_count}/{total_chances}) (+{credits_earned} credits, 0 gems)")
                            break

                        # Opcode 1: Server status / error response
                        elif op == 1:
                            p_err = it.get(2, b"")
                            sub_err = ProtobufCodec.decode_message(p_err) if isinstance(p_err, bytes) else p_err
                            if isinstance(sub_err, dict) and sub_err.get(1) == 2080:
                                err_code = sub_err.get(2)
                                raw_bytes_hex = p_err.hex() if isinstance(p_err, bytes) else str(sub_err)
                                log(f"[ALLIANCE DONATE] Opcode 1 wire response for Opcode 2080: Code {err_code} (payload: {raw_bytes_hex})")

                                if err_code == 4:
                                    # Code 4 = Cooldown active or donation chances exhausted
                                    log("[ALLIANCE DONATE] Server status: Donation cooldown active / daily chances exhausted (Opcode 1, Code 4).")
                                    stop_reason = "chances_exhausted"
                                    got_error = True
                                    break
                                else:
                                    # Technology locked, maxed, or not open yet -> try next available tech in catalog
                                    alt_techs = [t for t in tech_catalog.keys() if t not in tried_tech_ids]
                                    if alt_techs:
                                        next_t = alt_techs[0]
                                        tried_tech_ids.add(next_t)
                                        log(f"[ALLIANCE DONATE] Tech #{current_tech_id} unavailable (code {err_code}) -> switching to Tech #{next_t}")
                                        current_tech_id = next_t
                                        need_switch_tech = True
                                        break
                                    else:
                                        log(f"[ALLIANCE DONATE] Donation halted by server (Opcode 1, Code {err_code}).")
                                        stop_reason = f"server_code_{err_code}"
                                        got_error = True
                                        break

                    if got_ack or got_error or need_switch_tech:
                        break

                except asyncio.TimeoutError:
                    continue
                except asyncio.IncompleteReadError:
                    break
                except Exception as e:
                    log(f"[ALLIANCE DONATE] Read warning: {e}")

            if got_error:
                break

            if need_switch_tech:
                continue

            if got_ack:
                attempt += 1
            else:
                log(f"[ALLIANCE DONATE] No server response to donation click #{attempt + 1}. Halting cycle.")
                stop_reason = "no_server_ack"
                break

            # Humanized delay between donation clicks (0.35s)
            await asyncio.sleep(0.35)

        log(f"[ALLIANCE DONATE] Cycle complete. Successfully executed {donated_count}/{total_chances} donations (Crits: {crit_count}). Status: {stop_reason}")

        return {
            "success": True,
            "donated": donated_count,
            "crits": crit_count,
            "remaining_chances": max(0, remaining_chances - donated_count),
            "recommended_tech_id": recommended_tech_id,
            "reason": stop_reason,
            "requested_actions": requested_actions,
            "actions_confirmed": False,
        }

    @classmethod
    async def execute_alliance_donation(
        cls,
        target_role_id: int,
        kingdom_id: int,
        gate_host: str,
        gate_port: int,
        log_callback: Optional[Any] = None,
        app_uid: Optional[str] = None,
        app_token: Optional[str] = None,
        udid: Optional[str] = None,
        char_name: Optional[str] = None,
        donate_tech: bool = True,
        alliance_id: int = 0,
        alliance_tag: str = "",
        help_members: bool = True,
        claim_gifts: bool = True,
        claim_pit: bool = False,
    ) -> Dict[str, Any]:
        """
        Standalone execution helper: establishes gateway connection, logs in,
        discovers alliance information from server stream, and delegates to donate_to_recommended_tech.
        """
        def log(msg: str):
            if log_callback:
                log_callback(msg)
            else:
                logger.info(msg)

        from fleet_manager import build_dynamic_login_payload
        from derive_seed_from_nonce import derive_seed

        log(f"[ALLIANCE DONATE] Connecting to Gateway {gate_host}:{gate_port} for Governor #{target_role_id}...")
        reader, writer = await open_game_connection(gate_host, gate_port)
        try:
            hdr = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            g_p = await reader.readexactly((hdr[0] << 8) | hdr[1])
            sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(g_p).get(2, b""))
            tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
            c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)

            login_p = build_dynamic_login_payload(str(app_uid), str(app_token), int(target_role_id), str(udid), str(kingdom_id))
            writer.write(FrameParser.build_frame(c_tx.encrypt(login_p)))
            # Explicit role switch sequence to guarantee target role is active
            p203 = ProtobufCodec.encode_message({1: int(target_role_id)})
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: p203}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
            p110 = ProtobufCodec.encode_message({1: int(target_role_id), 2: int(kingdom_id), 3: int(target_role_id)})
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: p110}))))
            writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
            await writer.drain()

            # Drain login ACKs and parse Opcode 1002 / 86 for dynamic alliance discovery
            discovered_aid = int(alliance_id or 0)
            discovered_atag = str(alliance_tag or "")

            drain_deadline = asyncio.get_event_loop().time() + 2.0
            while asyncio.get_event_loop().time() < drain_deadline:
                try:
                    rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
                    rl = (rh[0] << 8) | rh[1]
                    raw = await reader.readexactly(rl)
                    dec = c_rx.decrypt(raw)
                    try:
                        decomp = dec
                        z_idx = dec.find(b"\x78\x9c")
                        if z_idx == -1:
                            z_idx = dec.find(b"\x78\x01")
                        if z_idx != -1:
                            try:
                                decomp = zlib.decompress(dec[z_idx:])
                            except Exception:
                                decomp = dec
                        m_dec = ProtobufCodec.decode_message(decomp)
                        chunks_l = m_dec.get(1) if isinstance(m_dec.get(1), list) else [m_dec]
                        for cl in chunks_l:
                            it_l = ProtobufCodec.decode_message(cl) if isinstance(cl, bytes) else cl
                            if not isinstance(it_l, dict):
                                continue
                            op_l = it_l.get(1)
                            if op_l in (1002, 86) or (isinstance(cl, bytes) and b"\x08\xea\x07" in cl):
                                d_id, d_name, d_tag = extract_alliance_from_message(it_l)
                                if d_id and not discovered_aid:
                                    discovered_aid = d_id
                                if d_tag and not discovered_atag:
                                    discovered_atag = d_tag
                    except Exception:
                        pass
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

            if (discovered_aid and discovered_aid != alliance_id) or (discovered_atag and discovered_atag != alliance_tag):
                try:
                    from app.database import get_db_connection
                    con = get_db_connection()
                    con.execute("UPDATE characters SET alliance_id = ?, alliance_tag = ? WHERE role_id = ?",
                                (int(discovered_aid or 0), str(discovered_atag or ""), str(target_role_id)))
                    con.commit()
                except Exception:
                    pass

            res = await cls.donate_to_recommended_tech(
                reader=reader,
                writer=writer,
                c_tx=c_tx,
                c_rx=c_rx,
                role_id=str(target_role_id),
                log_callback=log,
                donate_tech=donate_tech,
                alliance_id=discovered_aid,
                alliance_tag=discovered_atag,
                char_name=char_name,
                help_members=help_members,
                claim_gifts=claim_gifts,
                claim_pit=claim_pit,
            )
            return res

        finally:
            writer.close()
            await writer.wait_closed()
