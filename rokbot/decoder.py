"""
decoder.py — High-performance S2C packet parser and real-time game state tracker.

Decodes incoming RoK server frames (Protobuf / WHMP / Zlib compressed) to track:
- Resource Node discovery (Op 9999 marker 1177, Op 1027)
- March state & capacity (Op 1003, Op 1012 ACK, Op 1083, Op 1180)
- Training queues & building timers (Op 121, Op 122, Op 142, Op 301)
- Player resources & status (Op 121, Op 364, Op 601, Op 8003)
- Server ACKs and error codes (Op 1)
"""
from __future__ import annotations

import logging
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .protobuf import (
    decode_deep_proto,
    decode_message,
    u32_to_f32,
)

logger = logging.getLogger("rokbot.decoder")


@dataclass
class ResourceNode:
    node_id: int
    x: float
    y: float
    level: int = 1
    resource_type: int = 1  # 1=food, 2=wood, 3=stone, 5=gold
    amount: int = 0
    discovered_at: float = field(default_factory=time.time)
    occupied: bool = False


@dataclass
class MarchState:
    march_id: int
    target_node_id: int = 0
    target_x: float = 0.0
    target_y: float = 0.0
    status: str = "moving"  # moving, gathering, returning, idle
    start_time: float = field(default_factory=time.time)
    eta_seconds: float = 0.0


@dataclass
class BarracksState:
    building_id: str = ""
    unit_type: int = 0
    category: str = ""
    current_count: int = 0
    remaining_seconds: int = 0
    is_busy: bool = False
    needs_collect: bool = False


@dataclass
class GameState:
    """Real-time in-memory game state for an active bot session."""
    player_id: str = ""
    governor_name: str = ""
    power: int = 0
    kingdom_id: int = 0
    alliance_tag: str = ""
    vip_level: int = 0

    # Resources: food, wood, stone, gold, gems
    resources: Dict[str, int] = field(default_factory=lambda: {
        "food": 0, "wood": 0, "stone": 0, "gold": 0, "gems": 0
    })

    # Discovered Resource Nodes: node_id -> ResourceNode
    resource_nodes: Dict[int, ResourceNode] = field(default_factory=dict)

    # Active Marches: march_id -> MarchState
    active_marches: Dict[int, MarchState] = field(default_factory=dict)

    # Training queues: slot_id -> busy_until_timestamp (legacy numeric slots)
    building_busy_until: Dict[int, float] = field(default_factory=dict)

    # Verified barracks state from S2C Op 302: category -> BarracksState
    barracks: Dict[str, BarracksState] = field(default_factory=dict)

    # Role / profile info from S2C Op 15 / 204 / 1002
    active_role_id: int = 0
    active_role_name: str = ""
    active_power: int = 0
    active_kingdom: int = 0

    # Server config flags
    server_config: Dict[str, Any] = field(default_factory=dict)

    # Estimated city position
    city_pos: Tuple[float, float] = (7057.0, 5687.0)

    # Last ACK status
    last_command_acks: Dict[int, Tuple[int, bool]] = field(default_factory=dict)  # op -> (code, success)

    # Last selected-node amount from S2C Op 903 (no node id inline)
    last_node_amount: int = 0


class PacketDecoder:
    """
    Decodes and processes decrypted server frames, updating the GameState.
    """

    def __init__(self, game_state: Optional[GameState] = None):
        self.state = game_state or GameState()

    def decode_frame(self, decrypted_payload: bytes) -> Dict[str, Any]:
        """
        Parse raw decrypted frame payload into structured dictionary
        and update internal GameState.
        """
        try:
            fields = decode_message(decrypted_payload)
        except Exception:
            return {"opcode": -1, "error": "malformed_protobuf"}

        opcode = fields.get(1, -1)
        inner = fields.get(2, b"")

        result: Dict[str, Any] = {
            "opcode": opcode,
            "size": len(decrypted_payload),
            "timestamp": time.time(),
        }

        if opcode == 8003:
            result["type"] = "heartbeat"

        elif opcode == 1:
            # Universal command ACK: {1: op, 2: status_code}
            # Success codes are per-op: normal ops use 1, but login (op 14)
            # succeeds with 241 (BOT_DOCUMENTATION: 241=success, verified
            # against app_token/password/fake-token logins).
            result["type"] = "command_ack"
            if isinstance(inner, (bytes, bytearray)) and len(inner) >= 2:
                sub = decode_message(bytes(inner))
                resp_op = sub.get(1, -1)
                resp_code = sub.get(2, -1)
                success = (resp_code == 1) or (resp_op == 14 and resp_code == 241)
                result["responded_op"] = resp_op
                result["response_code"] = resp_code
                result["success"] = success
                self.state.last_command_acks[resp_op] = (resp_code, success)
                extra = sub.get(3, b"")
                if isinstance(extra, (bytes, bytearray)) and len(extra) > 0:
                    result["extra"] = decode_deep_proto(bytes(extra))

        elif opcode == 9999:
            # Compressed blob (Zlib)
            result["type"] = "compressed_batch"
            self._handle_op_9999(inner, result)

        elif opcode == 61438:
            # Static Map Data (Zlib)
            result["type"] = "static_map_data"
            self._handle_op_61438(inner, result)

        elif opcode == 121:
            # Queue update / Resource state
            result["type"] = "queue_or_resource_update"
            self._handle_op_121(inner, result)

        elif opcode == 301:
            # Train confirm (S2C). Note: C2S 301 = map entities query.
            result["type"] = "train_confirm"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 302:
            # Barracks training-queue state (S2C). Verified by smart_troop_trainer:
            # {1:[{1:building_id, 2:unit_type, 3:count, 4:remaining_ms}]}
            result["type"] = "barracks_state"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))
                self._handle_op_302(bytes(inner), result)

        elif opcode == 303:
            result["type"] = "troop_click_ack"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 304:
            result["type"] = "troop_collect_ack"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 123:
            result["type"] = "building_query_ack"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 124:
            # City building level/layout (NOT training timers — see Op 302).
            # Live shape: {1:[{1:building_id, 2:{1:?, 2:?}}]} e.g. 59/72/63/66.
            result["type"] = "city_buildings"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))
                self._handle_op_124(bytes(inner), result)

        elif opcode == 162:
            # App+device auth result: {1:"fail"/"success"?, 2:login_code, 3:reason}.
            # Live: {f1:'fail', f2:241, f3:'validate_app_device_token_fail'}.
            result["type"] = "device_auth_result"
            if isinstance(inner, (bytes, bytearray)):
                sub = decode_message(bytes(inner))
                result["data"] = decode_deep_proto(bytes(inner))
                try:
                    st = sub.get(1, b"")
                    if isinstance(st, (bytes, bytearray)):
                        st = st.decode("utf-8", errors="replace")
                    rs = sub.get(3, b"")
                    if isinstance(rs, (bytes, bytearray)):
                        rs = rs.decode("utf-8", errors="replace")
                    result["status"] = st
                    result["reason"] = rs
                    result["auth_ok"] = (st != "fail")
                except Exception:
                    pass

        elif opcode == 15:
            result["type"] = "role_info"
            if isinstance(inner, (bytes, bytearray)):
                sub = decode_message(bytes(inner))
                result["data"] = decode_deep_proto(bytes(inner))
                try:
                    if sub.get(1):
                        self.state.active_role_id = int(sub.get(1))
                    if sub.get(5):
                        rn = sub.get(5)
                        self.state.active_role_name = rn.decode("utf-8", errors="replace") if isinstance(rn, (bytes, bytearray)) else str(rn)
                    if sub.get(6):
                        self.state.active_power = int(sub.get(6))
                    if sub.get(2):
                        self.state.active_kingdom = int(sub.get(2))
                except Exception:
                    pass

        elif opcode == 204:
            result["type"] = "role_switch_ack"
            if isinstance(inner, (bytes, bytearray)):
                sub = decode_message(bytes(inner))
                result["data"] = decode_deep_proto(bytes(inner))
                try:
                    if sub.get(2):
                        self.state.active_role_id = int(sub.get(2))
                except Exception:
                    pass

        elif opcode == 1002:
            result["type"] = "profile_info"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 7922:
            result["type"] = "player_id"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 8563:
            result["type"] = "wait_info"
            if isinstance(inner, (bytes, bytearray)):
                try:
                    result["data"] = bytes(inner).decode("utf-8", errors="replace")
                except Exception:
                    result["data"] = bytes(inner).hex()

        elif opcode == 8600:
            result["type"] = "server_event"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 8703:
            result["type"] = "castle_info"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 8036:
            # Server state echo: {1:?, 2:role_id, 3:state_tag, 4:json_blob}.
            # Live: FTE_STATE echoes tutorial JSON for the bound role —
            # proof the session is attached to that character.
            result["type"] = "server_notice_8036"
            if isinstance(inner, (bytes, bytearray)):
                sub = decode_message(bytes(inner))
                result["data"] = decode_deep_proto(bytes(inner))
                try:
                    tag = sub.get(3, "")
                    blob = sub.get(4, b"")
                    if isinstance(tag, (bytes, bytearray)):
                        tag = tag.decode("utf-8", errors="replace")
                    if isinstance(blob, (bytes, bytearray)):
                        blob = blob.decode("utf-8", errors="replace")
                    if tag and blob:
                        import json as _json
                        try:
                            self.state.server_config[str(tag)] = _json.loads(blob)
                        except Exception:
                            self.state.server_config[str(tag)] = blob
                except Exception:
                    pass

        elif opcode in (9100, 54, 601, 122, 1210, 1329, 1429, 1890, 1980,
                        2047, 2050, 2106, 2114, 2136, 3742, 4608, 6005,
                        7943, 7994, 8023, 8103):
            result["type"] = f"server_msg_{opcode}"
            if isinstance(inner, (bytes, bytearray)) and len(inner) > 0:
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 903:
            # Selected-node resource amount {1: amount}. No node id inline;
            # Bot maps it onto its pending gather target (see last_node_amount).
            result["type"] = "node_amount"
            if isinstance(inner, (bytes, bytearray)):
                sub = decode_message(bytes(inner))
                amount = sub.get(1, 0)
                result["amount"] = amount
                if isinstance(amount, int):
                    self.state.last_node_amount = amount

        elif opcode == 9727:
            # Preflight ACK for C2S Op 9726 (empty). Server answers op+1.
            result["type"] = "preflight_ack"

        elif opcode == 1005:
            # March intel push (answer to our Op 1012 dispatch).
            # Live shape: {1:{1:march_id, 2:slot, 3:{1:march_id, 2:owner_role,
            #   f4:{commander...}, f6:march_name, f7:owner_name, f14:army,
            #   f19:alliance, f23:kingdom, ...}}, 4:?, 6:?, 9:{march pos},
            #   10:{1:node_id, 2:node_pos, ...}}.
            result["type"] = "march_intel"
            if isinstance(inner, (bytes, bytearray)):
                self._handle_op_1005(bytes(inner), result)

        elif opcode == 1177:
            # Top-level resource node list (answer to C2S Op 1176 discovery).
            # Live shape: {1:[{1:{1:x_u32, 2:y_u32}, 2:node_id, 3:{1:u64, 2:u64}}]}.
            result["type"] = "resource_nodes"
            if isinstance(inner, (bytes, bytearray)):
                self._handle_op_1177(bytes(inner), result)

        elif opcode == 1083:
            # March/state update batch (small, live-observed alongside 1177)
            result["type"] = "march_update"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 365:
            # Node state / march on node
            result["type"] = "node_state"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 1003:
            # March created
            result["type"] = "march_created"
            if isinstance(inner, (bytes, bytearray)):
                sub = decode_message(bytes(inner))
                result["march_data"] = sub

        elif opcode == 1180:
            # Entity created
            result["type"] = "entity_created"
            if isinstance(inner, (bytes, bytearray)):
                sub = decode_message(bytes(inner))
                result["entity_id"] = sub.get(1, 0)

        elif opcode == 8500:
            result["type"] = "world_info"

        elif opcode == 7604:
            result["type"] = "game_state_sync"
            if isinstance(inner, (bytes, bytearray)) and len(inner) > 2:
                result["data"] = decode_deep_proto(bytes(inner))

        elif opcode == 219:
            result["type"] = "login_ack"
            if isinstance(inner, (bytes, bytearray)):
                result["data"] = decode_deep_proto(bytes(inner))

        else:
            result["type"] = f"opcode_{opcode}"
            if isinstance(inner, (bytes, bytearray)) and len(inner) > 0:
                result["data"] = decode_deep_proto(bytes(inner))

        return result

    def _handle_op_9999(self, inner: Any, result: Dict[str, Any]):
        if not isinstance(inner, (bytes, bytearray)) or len(inner) < 2:
            return
        try:
            sub = decode_message(bytes(inner))
            cid = sub.get(1, 0)
            result["config_id"] = cid
            zdata = sub.get(2, b"")
            if isinstance(zdata, (bytes, bytearray)) and len(zdata) > 2:
                decompressed = None
                for wb in (15, -15):
                    try:
                        decompressed = zlib.decompress(bytes(zdata), wb)
                        break
                    except Exception:
                        pass
                if decompressed:
                    result["decompressed_size"] = len(decompressed)
                    self._parse_decompressed_batch(decompressed, result)
        except Exception as e:
            logger.debug(f"Error handling op 9999: {e}")

    def _parse_decompressed_batch(self, data: bytes, result: Dict[str, Any]):
        """Parse batch records for marker 1177 (resource nodes) and other entities."""
        try:
            rf = decode_message(data)
            f1, f2 = rf.get(1), rf.get(2)
            markers = f1 if isinstance(f1, list) else [f1]
            payloads = f2 if isinstance(f2, list) else [f2]

            nodes_found = 0
            for marker, payload in zip(markers, payloads):
                if marker == 1177 and isinstance(payload, (bytes, bytearray)):
                    pl = decode_message(bytes(payload))
                    ents = pl.get(1, [])
                    if not isinstance(ents, list):
                        ents = [ents]
                    for e in ents:
                        if not isinstance(e, (bytes, bytearray)):
                            continue
                        ef = decode_message(bytes(e))
                        nid = ef.get(2)
                        pos_bytes = ef.get(1)
                        if isinstance(nid, int) and isinstance(pos_bytes, (bytes, bytearray)):
                            pv = decode_message(bytes(pos_bytes))
                            x_raw = pv.get(1)
                            y_raw = pv.get(2)
                            if isinstance(x_raw, int) and isinstance(y_raw, int):
                                x = round(u32_to_f32(x_raw), 2)
                                y = round(u32_to_f32(y_raw), 2)
                                node = ResourceNode(node_id=nid, x=x, y=y)
                                self.state.resource_nodes[nid] = node
                                nodes_found += 1
            if nodes_found > 0:
                result["nodes_discovered"] = nodes_found
                self._update_estimated_city_pos()
        except Exception as e:
            logger.debug(f"Decompressed batch parse error: {e}")

    UNIT_TYPE_TO_CATEGORY = {1: "infantry", 2: "cavalry", 3: "archery", 4: "siege", 8: "siege"}

    def _handle_op_1005(self, inner: bytes, result: Dict[str, Any]):
        """Parse S2C Op 1005 march intel into GameState.active_marches."""
        try:
            top = decode_message(inner)
            head = top.get(1, b"")
            if not isinstance(head, (bytes, bytearray)):
                return
            h = decode_message(bytes(head))
            march_id = int(h.get(1, 0) or 0)
            detail = h.get(3, b"")
            owner_role, owner_name, march_name = 0, "", ""
            army, kingdom = [], 0
            if isinstance(detail, (bytes, bytearray)):
                d = decode_message(bytes(detail))
                owner_role = int(d.get(2, 0) or 0)
                nm = d.get(7, b"")
                owner_name = nm.decode("utf-8", errors="replace") if isinstance(nm, (bytes, bytearray)) else str(nm or "")
                mn = d.get(6, b"")
                march_name = mn.decode("utf-8", errors="replace") if isinstance(mn, (bytes, bytearray)) else str(mn or "")
                kingdom = int(d.get(23, 0) or 0)
                alist = d.get(14, [])
                if not isinstance(alist, list):
                    alist = [alist]
                for a in alist:
                    if isinstance(a, (bytes, bytearray)):
                        try:
                            ad = decode_message(bytes(a))
                            army.append((int(ad.get(2, 0) or 0), int(ad.get(1, 0) or 0)))
                        except Exception:
                            pass
            node_id, nx, ny = 0, 0.0, 0.0
            tgt = top.get(10, b"")
            if isinstance(tgt, (bytes, bytearray)):
                t = decode_message(bytes(tgt))
                node_id = int(t.get(1, 0) or 0)
                praw = t.get(2, b"")
                if isinstance(praw, (bytes, bytearray)):
                    try:
                        pv = decode_message(bytes(praw))
                        nx, ny = round(u32_to_f32(pv.get(1, 0)), 1), round(u32_to_f32(pv.get(2, 0)), 1)
                    except Exception:
                        pass
            if march_id:
                self.state.active_marches[march_id] = MarchState(
                    march_id=march_id, target_node_id=node_id,
                    target_x=nx, target_y=ny, status="gathering",
                    eta_seconds=0.0,
                )
                result["march_confirmed"] = march_id
                result["march_data"] = {
                    "owner_role": owner_role, "owner_name": owner_name,
                    "march_name": march_name, "army": army, "kingdom": kingdom,
                }
                # Learn the truly active role from the server's attribution.
                if owner_role:
                    self.state.active_role_id = owner_role
                    if owner_name:
                        self.state.active_role_name = owner_name
                if node_id and node_id in self.state.resource_nodes:
                    self.state.resource_nodes[node_id].occupied = True
        except Exception as e:
            logger.debug(f"Error handling op 1005: {e}")

    def _handle_op_1177(self, inner: bytes, result: Dict[str, Any]):
        """Parse top-level Op 1177 node list into GameState.resource_nodes."""
        try:
            top = decode_message(inner)
            ents = top.get(1, [])
            if not isinstance(ents, list):
                ents = [ents]
            found = 0
            for e in ents:
                if not isinstance(e, (bytes, bytearray)):
                    continue
                try:
                    ef = decode_message(bytes(e))
                except Exception:
                    continue
                nid = ef.get(2)
                pos_raw = ef.get(1)
                if not isinstance(nid, int) or not isinstance(pos_raw, (bytes, bytearray)):
                    continue
                try:
                    pv = decode_message(bytes(pos_raw))
                    xr, yr = pv.get(1), pv.get(2)
                    if not isinstance(xr, int) or not isinstance(yr, int):
                        continue
                    x, y = round(u32_to_f32(xr), 1), round(u32_to_f32(yr), 1)
                except Exception:
                    continue
                det = ef.get(3, b"")
                amount = 0
                if isinstance(det, (bytes, bytearray)) and len(det) >= 2:
                    try:
                        dsub = decode_message(bytes(det))
                        for _k in (1, 2):
                            _v = dsub.get(_k, 0)
                            if isinstance(_v, int) and _v > amount:
                                amount = _v
                    except Exception:
                        pass
                self.state.resource_nodes[int(nid)] = ResourceNode(
                    node_id=int(nid), x=x, y=y, amount=amount)
                found += 1
            if found:
                result["nodes_discovered"] = found
                self._update_estimated_city_pos()
        except Exception as e:
            logger.debug(f"Error handling op 1177: {e}")

    def _handle_op_124(self, inner: bytes, result: Dict[str, Any]):
        """Store city building list {building_id: sub-fields} in server_config."""
        try:
            top = decode_message(inner)
            entries = top.get(1, [])
            if not isinstance(entries, list):
                entries = [entries]
            buildings = {}
            for e in entries:
                if not isinstance(e, (bytes, bytearray)):
                    continue
                info = decode_message(bytes(e))
                raw_id = info.get(1, "")
                b_id = raw_id.decode() if isinstance(raw_id, (bytes, bytearray)) else str(raw_id)
                sub = info.get(2, b"")
                buildings[b_id] = decode_deep_proto(bytes(sub)) if isinstance(sub, (bytes, bytearray)) else sub
            if buildings:
                self.state.server_config["city_buildings"] = buildings
                result["buildings_found"] = len(buildings)
        except Exception as e:
            logger.debug(f"Error handling op 124: {e}")

    def _handle_op_302(self, inner: bytes, result: Dict[str, Any]):
        """Parse S2C Op 302 barracks entries into GameState.barracks + busy timers."""
        try:
            p302 = decode_message(inner)
            entries = p302.get(1, [])
            if not isinstance(entries, list):
                entries = [entries]
            now = time.time()
            found = 0
            for bentry in entries:
                if not isinstance(bentry, (bytes, bytearray)):
                    continue
                try:
                    binfo = decode_message(bytes(bentry))
                except Exception:
                    continue
                raw_id = binfo.get(1, "")
                b_id = raw_id.decode() if isinstance(raw_id, (bytes, bytearray)) else str(raw_id)
                u_type = int(binfo.get(2, 0) or 0)
                count = int(binfo.get(3, 0) or 0)
                remaining_ms = int(binfo.get(4, 0) or 0)
                remaining_sec = max(0, remaining_ms // 1000)
                cat = self.UNIT_TYPE_TO_CATEGORY.get(u_type, f"unknown_{u_type}")
                self.state.barracks[cat] = BarracksState(
                    building_id=b_id,
                    unit_type=u_type,
                    category=cat,
                    current_count=count,
                    remaining_seconds=remaining_sec,
                    is_busy=remaining_sec > 0,
                    needs_collect=(remaining_sec == 0) and (count > 0),
                )
                # Keep legacy numeric busy map in sync for Bot.execute_training
                try:
                    self.state.building_busy_until[u_type] = now + float(remaining_sec)
                except Exception:
                    pass
                found += 1
            if found:
                result["barracks_found"] = found
        except Exception as e:
            logger.debug(f"Error handling op 302: {e}")

    def _handle_op_61438(self, inner: Any, result: Dict[str, Any]):
        if not isinstance(inner, (bytes, bytearray)):
            return
        try:
            sub = decode_message(bytes(inner))
            result["data"] = decode_deep_proto(bytes(inner))
            zdata = sub.get(2, bytes(inner))
            if isinstance(zdata, (bytes, bytearray)) and len(zdata) > 2:
                for wb in (15, -15):
                    try:
                        decomp = zlib.decompress(bytes(zdata), wb)
                        result["decompressed_size"] = len(decomp)
                        result["decompressed"] = decomp
                        break
                    except Exception:
                        pass
        except Exception:
            pass

    def _handle_op_121(self, inner: Any, result: Dict[str, Any]):
        if not isinstance(inner, (bytes, bytearray)) or len(inner) < 2:
            return
        try:
            sub = decode_message(bytes(inner))
            items = sub.get(1, [])
            if not isinstance(items, list):
                items = [items]
            now = time.time()
            for item in items:
                if isinstance(item, (bytes, bytearray)):
                    entry = decode_message(bytes(item))
                    slot_or_type = entry.get(1, 0)
                    val = entry.get(2, 0)
                    # If val > 1000, it's a millisecond timer for training/building
                    if val > 1000:
                        self.state.building_busy_until[slot_or_type] = now + (val / 1000.0)
                    else:
                        # Resource amount update: 1=food, 2=wood, 3=stone, 4=gems, 5=gold
                        res_map = {1: "food", 2: "wood", 3: "stone", 4: "gems", 5: "gold"}
                        if slot_or_type in res_map:
                            self.state.resources[res_map[slot_or_type]] = val
        except Exception as e:
            logger.debug(f"Error handling op 121: {e}")

    def _update_estimated_city_pos(self):
        """Estimate city position based on cluster center of discovered nodes."""
        if not self.state.resource_nodes:
            return
        xs = [n.x for n in self.state.resource_nodes.values()]
        ys = [n.y for n in self.state.resource_nodes.values()]
        if xs and ys:
            avg_x = round(sum(xs) / len(xs), 1)
            avg_y = round(sum(ys) / len(ys), 1)
            self.state.city_pos = (avg_x, avg_y)

