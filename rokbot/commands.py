"""
Command library — captured game commands for farming automation.

Commands are loaded from JSON files in the commands/ directory and
can be replayed through an active session connection.
"""
import json
import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .protobuf import (
    decode_deep_proto,
    decode_message,
    encode_field_bytes,
    encode_field_varint,
    encode_message,
    encode_varint,
    f32_to_u32,
    u32_to_f32,
)

logger = logging.getLogger("rokbot.commands")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMMANDS_DIR = PROJECT_ROOT / "commands"

# Troop Type IDs (legacy unit-template space, kept for compat)
TROOP_INFANTRY_T1 = 64
TROOP_CAVALRY_T1 = 72
TROOP_ARCHER_T1 = 207
TROOP_SIEGE_T1 = 206

TROOP_INFANTRY_T2 = 75
TROOP_CAVALRY_T2 = 62
TROOP_SIEGE_T2 = 353

TROOP_INFANTRY_T4 = 267
TROOP_CAVALRY_T4 = 250
TROOP_ARCHER_T4 = 282
TROOP_SIEGE_T4 = 283

# Verified barracks building IDs (AmmAr live capture, smart_troop_trainer.py).
# Op 300 field1 = building_id string, field2 = unit_type (1-4).
BARRACKS_INFANTRY = {"building_id": "59", "unit_type": 1}
BARRACKS_CAVALRY = {"building_id": "72", "unit_type": 2}
BARRACKS_ARCHERY = {"building_id": "63", "unit_type": 3}
BARRACKS_SIEGE = {"building_id": "66", "unit_type": 4}

UNIT_TYPE_TO_CATEGORY = {1: "infantry", 2: "cavalry", 3: "archery", 4: "siege"}

# Resource IDs
RESOURCE_FOOD = 1
RESOURCE_WOOD = 2
RESOURCE_STONE = 3
RESOURCE_GOLD = 5


def fixed32_tag(field_num: int, bits: int) -> bytes:
    """Encode fixed32 tag and value in protobuf wire format."""
    return encode_varint((field_num << 3) | 5) + struct.pack("<I", bits & 0xFFFFFFFF)


def build_cmd_frame(opcode: int, payload: bytes) -> bytes:
    """Construct standard RoK client command frame [f1=opcode, f2=payload]."""
    return encode_message({1: opcode, 2: payload})


# ──────────────────────────────────────────────────────────────────────
# High-Level Verified Command Builders
# ──────────────────────────────────────────────────────────────────────

def build_discover_nodes() -> Tuple[int, bytes]:
    """
    Opcode 1176: Discover surrounding resource nodes.
    Verified: {1: 2, 2: 6}
    """
    payload = encode_message({1: 2, 2: 6})
    return (1176, payload)


def build_gather_march(
    node_id: int,
    army: Optional[List[Tuple[int, int]]] = None,
    march_name: str = "dispatch_troop_1",
    commander_id: int = 23,
) -> Tuple[int, bytes]:
    """
    Opcode 1012: Dispatch march to gather a resource node.
    VERIFIED against authentic_march_packet.json (2026-09-07 live capture):
      f1 = {1: commander_id, 2: 1, 3: 0}
      f2[] = {2: unit_template, 1: count} per troop batch
      f3 = fixed32(0.0, 0.0) — required, server drops frame without it
      f4 = node_id, f5 = march_name, f6/f7/f11 = 0, f14 = 1, f18 = 0
    Authentic unit templates seen live: 10010, 505, 11140, ... (account-specific).
    Caller should pass real templates from Op 1003 / troop profile when known.
    NOTE (verified live 2026-09-10, role ssar3): placeholder army
    [(1020, 1), (500, 3)] is ACCEPTED — server created march 2190606 and
    echoed the units back in S2C Op 1005. Tune per-account when known.
    """
    if army is None:
        army = [(1020, 1), (500, 3)]

    army_msgs = []
    for unit_int, count in army:
        army_msgs.append(encode_message({2: unit_int, 1: count}))

    f3 = fixed32_tag(2, 0) + fixed32_tag(1, 0)
    payload = (
        encode_field_bytes(1, encode_message({1: commander_id, 3: 0, 2: 1}))
        + b"".join(encode_field_bytes(2, m) for m in army_msgs)
        + encode_field_bytes(3, f3)
        + encode_field_varint(4, node_id)
        + encode_field_bytes(5, march_name.encode("utf-8"))
        + encode_field_varint(6, 0)
        + encode_field_varint(7, 0)
        + encode_field_varint(11, 0)
        + encode_field_varint(14, 1)
        + encode_field_varint(18, 0)
    )
    return (1012, payload)


def build_gather_preflight_ack() -> Tuple[int, bytes]:
    """Opcode 9726: empty ACK sent after each 1050 preflight (live capture)."""
    return (9726, b"")


def build_auto_gather(
    alliance_id: int,
    node_id: int,
    city_pos: Tuple[float, float],
    node_pos: Tuple[float, float],
) -> Tuple[int, bytes]:
    """
    Opcode 1050: Auto-gather click before march dispatch.
    VERIFIED authentic_march_packet.json:
      {1: alliance/chief_id, 2: node_id,
       3: fixed32(node f2=x?, f1=y?) city pos,
       4: fixed32 node pos, 5: 0}
    Live wire order inside pos blob is f2-then-f1; both orders decode
    identically, but we emit f2-first to stay byte-exact with the client.
    """
    def pos_bytes(p: Tuple[float, float]) -> bytes:
        # p = (x, y); wire: field2=x, field1=y to match live client bytes
        return fixed32_tag(2, f32_to_u32(p[0])) + fixed32_tag(1, f32_to_u32(p[1]))

    payload = (
        encode_field_varint(1, alliance_id)
        + encode_field_varint(2, node_id)
        + encode_field_bytes(3, pos_bytes(city_pos))
        + encode_field_bytes(4, pos_bytes(node_pos))
        + encode_field_varint(5, 0)
    )
    return (1050, payload)


def build_train_troops(
    unit_template: str = "59",
    unit_type: int = 1,
    count: int = 100,
    building_id: Optional[str] = None,
) -> Tuple[int, bytes]:
    """
    Opcode 300: Train troops.
    VERIFIED (rok_protocol.py + smart_troop_trainer.py live capture):
      {1:300, 2:{1:"<building_id>", 2:<unit_type 1-4>, 3:<count>, 4:0, 5:0}}
    building_id examples: "59"=infantry, "72"=cavalry, "63"=archery, "66"=siege.
    Server confirms with S2C Op 301; busy queue -> Op 1 {1:300, 2:139}.
    `building_id` alias overrides `unit_template` for clarity.
    """
    bid = building_id if building_id is not None else unit_template
    payload = encode_message({
        1: str(bid),
        2: unit_type,
        3: count,
        4: 0,
        5: 0,
    })
    return (300, payload)


def build_collect_troops(building_id: str, unit_type: int) -> Tuple[int, bytes]:
    """Opcode 303: Collect finished troops {1:building_id, 2:unit_type}."""
    return (303, encode_message({1: str(building_id), 2: unit_type}))


def build_troop_click(building_id: str) -> Tuple[int, bytes]:
    """Opcode 303 (variant): unit info click {1:building_id} before train."""
    return (303, encode_message({1: str(building_id)}))


def build_discover_barracks(building_ids: List[str]) -> Tuple[int, bytes]:
    """Opcode 123: query building states {1:[building_id...]} for Op 302 discovery."""
    return (123, encode_message({1: [str(b) for b in building_ids]}))


def build_query_barracks_125(building_ids: Optional[List[str]] = None) -> Tuple[int, bytes]:
    """
    Opcode 125: dynamic barracks query (post-switch flow).
    Shape unconfirmed: mirrors Op 123 ({1:[building_id...]}); with no args
    sends empty inner like other stateless queries. Try ids first, then empty.
    """
    if building_ids:
        return (125, encode_message({1: [str(b) for b in building_ids]}))
    return (125, b"")


def build_barracks_info(building_id: str = "59") -> Tuple[int, bytes]:
    """Opcode 120: building click {1:building_id} (C2S_STATUS_UPDATE)."""
    return (120, encode_message({1: str(building_id)}))


# ──────────────────────────────────────────────────────────────────────
# Post-login handshake (live-verified shapes).
# The server parks the session until this block completes: live client
# sends 104/107 right after login (elicits S2C Op 15 role_info), then
# 161/170/110/1202/1001/1004/5501/8035 after the init wave.
# Sources: live_gather_protocol_details.json, smart_troop_trainer.py,
# rok_headless_bot.py, rok_protocol.py.
# ──────────────────────────────────────────────────────────────────────

def build_role_request() -> Tuple[int, bytes]:
    """Opcode 104: role request (empty). Server answers S2C Op 15 / 1002."""
    return (104, b"")


def build_profile_request() -> Tuple[int, bytes]:
    """Opcode 107: profile request (empty)."""
    return (107, b"")


def build_player_query(player_id: int, kingdom_id: int) -> Tuple[int, bytes]:
    """
    Opcode 110: {1:role, 2:kingdom_id, 3:role}.
    Verified against live_switch_clean.pcap (real client, conn 50000, ssar3):
      raw `10a11818c2e6c66c08c2e6c66c` decodes to f1=227652418 (role),
      f2=3105 (ssar3's kingdom_id), f3=227652418 (role).
    Sending a foreign f2 (e.g. 3140) yields S2C Op 1 {110, 246} reject.
    """
    role = int(player_id)
    return (110, encode_message({1: role, 2: int(kingdom_id), 3: role}))


def build_second_auth(
    app_uid: str,
    access_token: str,
    device_token: str = "",
    locale: str = "en",
    platform: str = "android",
    app_id: int = 2104267,
) -> Tuple[int, bytes]:
    """
    Opcode 161: second auth, EXPERIMENTAL (not in the default handshake).
    Live shape (live_gather_protocol_details.json, op 161 len 111):
      {1: auth_blob{1:app_uid, 2:access_token, 3:app_id, 4:platform, 5:1},
       2: device_hex_token, 3: locale, 4: platform}
    The f1 blob re-serializes the login auth struct (verified by hand:
    f3 varint 2104267, f2 = access token, f1 = app_uid, f4 = platform).
    """
    blob = encode_message({1: str(app_uid), 2: access_token, 3: app_id, 4: platform, 5: 1})
    inner = encode_message({1: blob, 2: device_token, 3: locale, 4: platform})
    return (161, inner)


def build_login_analytics(player_id: str) -> Tuple[int, bytes]:
    """Opcode 170: login analytics (ids parameterized, rest = live template)."""
    inner = encode_message({
        1: 191783318,
        2: str(player_id),
        3: str(player_id),
        4: "ar",
        5: "WIN10",
        6: "220293855",
        7: b"",
        8: "PC",
    })
    return (170, inner)


def build_time_sync_role(player_id: int) -> Tuple[int, bytes]:
    """Opcode 1202: role time-sync {1:role_id}."""
    return (1202, encode_message({1: int(player_id)}))


def build_map_init() -> Tuple[int, bytes]:
    """Opcode 1001: map init query (empty)."""
    return (1001, b"")


def build_army_panel(city_x: float = 2822.8, city_y: float = 4269.1) -> Tuple[int, bytes]:
    """Opcode 1004: open army panel {2:{2:0, 5:1, 1:{2:x_f32, 1:y_f32}}}."""
    pos = fixed32_tag(2, f32_to_u32(city_x)) + fixed32_tag(1, f32_to_u32(city_y))
    return (1004, encode_field_bytes(1, pos) + encode_field_varint(2, 0) + encode_field_varint(5, 1))


def build_session_flag() -> Tuple[int, bytes]:
    """Opcode 5501: session flag {1:1} (live len-7 frame)."""
    return (5501, encode_message({1: 1}))


def build_client_state(player_id: int, state: str = "FTE_STATE") -> Tuple[int, bytes]:
    """
    Opcode 8035: {1:role_id VARINT, 2:state_string} (live: FTE_STATE,
    CityFakeT6Evolved, HeroSystem_MarkHero...). f1 is an int, not a string.
    """
    return (8035, encode_message({1: int(player_id), 2: state}))


def build_role_switch(player_id: int) -> Tuple[int, bytes]:
    """
    Opcode 203: character switch {1:role_id}.
    HOW SWITCHING WORKS (live_switch_clean.pcap, real client, verified):
      1. Login (plain Android login, NO f14). Gateway auto-loads the
         last-played role; S2C Op 15 confirms it ~0.3s after login.
      2. To play another role: send 203 {1:new_role}, then Op 110
         {1:new_role, 2:new_role_kingdom, 3:new_role} (kingdom is PER-ROLE:
         ssar3->3105, AmmAr->11543; wrong f2 => Op 1 {110, 246} reject).
      3. A second S2C Op 15 for the new role confirms the switch.
    NOTES:
      - No S2C Op 204 exists on the wire (not even in the live capture);
        the confirming signal is the new Op 15, not a 204.
      - Op 15/302 role-attach itself is gated server-side: with a stale
        access_token the gateway streams world data but never attaches a
        role (no 15/302) and 203+110 has no effect. A fresh token
        (email_login) restores it. f14 role logins do NOT help.
    """
    return (203, encode_message({1: int(player_id)}))


def build_search_resource(resource_type: int = 1) -> Tuple[int, bytes]:
    """Opcode 1005: search resource {1:type, 2:0} (ported from rok_headless_bot)."""
    return (1005, encode_message({1: resource_type, 2: 0}))


def build_search_resource_v2(resource_type: int = 1) -> Tuple[int, bytes]:
    """Opcode 1006: search resource v2 {1:type, 2:0, 3:0}."""
    return (1006, encode_message({1: resource_type, 2: 0, 3: 0}))


def build_search_resource_type(resource_type: int = 1, level: int = 5) -> Tuple[int, bytes]:
    """Opcode 1007: search resource by type+level {1:type, 2:level}."""
    return (1007, encode_message({1: resource_type, 2: level}))


def build_map_entities() -> Tuple[int, bytes]:
    """Opcode 301 (C2S): map entities query (empty). Note: S2C 301 = train confirm."""
    return (301, encode_message({}))


def build_map_screen() -> Tuple[int, bytes]:
    """Opcode 302 (C2S): map screen query. Note: S2C 302 = barracks state."""
    return (302, encode_message({1: encode_message({}), 2: 1, 3: 1600}))


def build_player_online() -> Tuple[int, bytes]:
    """Opcode 925: player online {1:0} (verified, sent rarely)."""
    return (925, encode_message({1: 0}))


def build_alliance_info() -> Tuple[int, bytes]:
    """Opcode 1200: alliance info query."""
    return (1200, encode_message({1: 0}))


def build_march_move(target_x: float, target_y: float) -> Tuple[int, bytes]:
    """
    Opcode 1004: Move march to coordinates.
    """
    x_bytes = struct.pack("<f", target_x)
    y_bytes = struct.pack("<f", target_y)
    inner = {
        1: {1: x_bytes, 2: y_bytes},
        5: 1,
    }
    return (1004, encode_message(inner))


def build_alliance_help() -> Tuple[int, bytes]:
    """Opcode 1205: Request alliance help (matches CommandLibrary default + live client)."""
    return (1205, b"")


def build_claim_daily(panel: str = "daily_free_9") -> Tuple[int, bytes]:
    """
    Opcode 532: Daily-reward / UI panel action.
    TODO live-verify exact panel string; format matches build_ui_panel
    {1:532, 2:{1:panel, 2:"", 3:0}}.
    """
    inner = encode_message({1: panel, 2: "", 3: 0})
    return (532, inner)


def build_mail_collect() -> Tuple[int, bytes]:
    """
    Mailbox collect. TODO live-verify opcode/payload from Frida capture.
    social.json currently maps this to msg_id 300 with empty payload;
    we return empty payload so replay layer stays safe until verified.
    """
    return (300, b"")


def build_speedup() -> Tuple[int, bytes]:
    """Opcode 120: Trigger building/queue speedup."""
    return (120, encode_message({1: encode_message({})}))


def build_resource_info() -> Tuple[int, bytes]:
    """Opcode 120 / 5: Query current resource amounts."""
    return (120, b"")


def build_keepalive() -> Tuple[int, bytes]:
    """Opcode 9: Exact client heartbeat."""
    return (9, b"")


COMMAND_BUILDERS = {
    "discover_nodes": build_discover_nodes,
    "gather_march": build_gather_march,
    "gather_preflight_ack": build_gather_preflight_ack,
    "auto_gather": build_auto_gather,
    "train_troops": build_train_troops,
    "collect_troops": build_collect_troops,
    "troop_click": build_troop_click,
    "discover_barracks": build_discover_barracks,
    "barracks_info": build_barracks_info,
    "march_move": build_march_move,
    "role_request": build_role_request,
    "profile_request": build_profile_request,
    "player_query": build_player_query,
    "second_auth": build_second_auth,
    "login_analytics": build_login_analytics,
    "time_sync_role": build_time_sync_role,
    "map_init": build_map_init,
    "army_panel": build_army_panel,
    "session_flag": build_session_flag,
    "client_state": build_client_state,
    "role_switch": build_role_switch,
    "alliance_help": build_alliance_help,
    "alliance_info": build_alliance_info,
    "player_online": build_player_online,
    "map_entities": build_map_entities,
    "map_screen": build_map_screen,
    "search_resource": build_search_resource,
    "search_resource_v2": build_search_resource_v2,
    "search_resource_type": build_search_resource_type,
    "speedup": build_speedup,
    "resource_info": build_resource_info,
    "keepalive": build_keepalive,
    "claim_daily": build_claim_daily,
    "mail_collect": build_mail_collect,
    # Aliases matching commands/*.json "builder" strings:
    "build_claim_daily": build_claim_daily,
    "build_mail_collect": build_mail_collect,
}


@dataclass
class CommandDef:
    name: str
    msg_id: int
    payload_hex: str = ""
    payload_template: str = ""
    category: str = "general"
    description: str = ""
    repeatable: bool = True
    cooldown_s: float = 0.0
    builder_name: str = ""

    @property
    def payload_bytes(self) -> bytes:
        if self.builder_name and self.builder_name in COMMAND_BUILDERS:
            try:
                _, payload = COMMAND_BUILDERS[self.builder_name]()
                return payload
            except Exception:
                pass
        return bytes.fromhex(self.payload_hex) if self.payload_hex else b""

    def build_payload(self, **kwargs) -> Tuple[int, bytes]:
        if self.builder_name and self.builder_name in COMMAND_BUILDERS:
            try:
                builder = COMMAND_BUILDERS[self.builder_name]
                return builder(**kwargs) if kwargs else builder()
            except Exception:
                pass
        return (self.msg_id, bytes.fromhex(self.payload_hex) if self.payload_hex else b"")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "msg_id": self.msg_id,
            "payload_hex": self.payload_hex,
            "category": self.category,
            "description": self.description,
        }



class CommandLibrary:
    """
    Manages a library of game commands for farming automation.

    Commands are loaded from JSON files and can be looked up by name
    or category, then sent through an active session.
    """

    def __init__(self):
        self._commands: Dict[str, CommandDef] = {}
        self._categories: Dict[str, List[str]] = {}
        self._load_defaults()
        self._load_from_disk()

    def _load_defaults(self):
        defaults = [
            CommandDef("alliance_help", 1205, category="social", description="Request alliance help"),
            CommandDef("keepalive_empty", 0, category="system", description="Empty keepalive frame"),
            CommandDef("init_client_info", 600, payload_hex="0808", category="init", description="Client info request"),
            CommandDef("init_version", 8030, category="init", description="Version check"),
            CommandDef("init_state", 2003, category="init", description="State request"),
            CommandDef("init_config", 2077, category="init", description="Config request"),
            CommandDef("init_data", 2500, category="init", description="Data request"),
            CommandDef("init_toggle", 2039, payload_hex="0801", category="init", description="Toggle state"),
            CommandDef("init_ui", 8045, category="init", description="UI state"),
            CommandDef("init_ready", 104, category="init", description="Client ready"),
            CommandDef("init_features", 5600, category="init", description="Feature request"),
            CommandDef("init_unknown_a", 930, category="init", description="Init command A"),
            CommandDef("init_unknown_b", 9625, category="init", description="Init command B"),
            CommandDef("init_unknown_c", 6522, category="init", description="Init command C"),
            CommandDef("init_unknown_d", 3157, category="init", description="Init command D"),
            CommandDef("init_config_v2", 6404, payload_hex="08f010", category="init", description="Config v2"),
            CommandDef("init_timestamp", 1202, payload_hex="0896c3b95b", category="init", description="Timestamp"),
            CommandDef("init_unknown_e", 4811, category="init", description="Init command E"),
            CommandDef("init_unknown_f", 2065, category="init", description="Init command F"),
        ]
        for cmd in defaults:
            self._commands[cmd.name] = cmd
            self._categories.setdefault(cmd.category, []).append(cmd.name)

    def _load_from_disk(self):
        if not COMMANDS_DIR.exists():
            return
        for json_file in COMMANDS_DIR.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "commands" in data:
                    for name, info in data["commands"].items():
                        if name not in self._commands:
                            cmd = CommandDef(
                                name=name,
                                msg_id=info.get("msg_id", 0),
                                payload_hex=info.get("payload_hex", ""),
                                category=info.get("category", "farming"),
                                description=info.get("description", ""),
                                builder_name=info.get("builder", ""),
                            )
                            self._commands[name] = cmd
                            self._categories.setdefault(cmd.category, []).append(cmd.name)
                logger.debug(f"Loaded commands from {json_file.name}")
            except Exception as e:
                logger.warning(f"Failed to load {json_file.name}: {e}")

    def get(self, name: str) -> Optional[CommandDef]:
        return self._commands.get(name)

    def by_category(self, category: str) -> List[CommandDef]:
        names = self._categories.get(category, [])
        return [self._commands[n] for n in names if n in self._commands]

    def all_names(self) -> List[str]:
        return list(self._commands.keys())

    def all_categories(self) -> List[str]:
        return list(self._categories.keys())

    def stats(self) -> dict:
        return {
            "total_commands": len(self._commands),
            "categories": {cat: len(cmds) for cat, cmds in self._categories.items()},
        }
