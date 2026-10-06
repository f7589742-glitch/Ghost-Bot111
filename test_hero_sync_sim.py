"""
test_hero_sync_sim.py - Integration simulation for zero-config dynamic hero discovery.

Simulates the live login stream (synthetic wire frames) and verifies the exact
ingestion path used inside CombatEngine.execute_barbarian_hunt:
  outer frame {1: opcode, 2: payload} -> it.get(2) -> hero_parser functions.
No network, no DB, no real accounts touched.
"""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "python"))

from headless_client import ProtobufCodec
from app.services.protocol import hero_parser
from app.services.protocol.hero_parser import (
    parse_heroes_from_1201,
    parse_roster_from_1157,
    parse_wall_garrison_from_1002,
    parse_unlocked_barb_level_from_1002,
    merge_rosters,
    rank_heroes,
    build_roster_payload,
)

OP_HERO_CATALOGUE = 1201
OP_HERO_ROSTER_SUPPLEMENT = 1157
OP_CITY_STATE = 1002

failures = []

def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" -> {detail}" if detail else ""))
    if not cond:
        failures.append(name)

# ---------------------------------------------------------------
# 1. Build synthetic live-stream frames (the exact wire shapes)
# ---------------------------------------------------------------
# Opcode 1201: full roster catalogue {1: [entries]}
e1 = ProtobufCodec.encode_message({1: 6, 2: 60, 3: 5, 4: [101, 102], 5: 1})    # Lohar L60 5* awakened
e2 = ProtobufCodec.encode_message({1: 36, 2: 30, 3: 4, 4: [201], 5: 0})        # Lancelot L30 4*
e3 = ProtobufCodec.encode_message({1: 15, 2: 37, 3: 4, 4: [301], 5: 0})        # Joan L37 4*
e_noise = ProtobufCodec.encode_message({1: 8853268, 2: 9})                     # player-id noise
p1201 = (
    ProtobufCodec.encode_field_bytes(1, e1)
    + ProtobufCodec.encode_field_bytes(1, e2)
    + ProtobufCodec.encode_field_bytes(1, e3)
    + ProtobufCodec.encode_field_bytes(1, e_noise)
)
frame_1201 = ProtobufCodec.encode_message({1: OP_HERO_CATALOGUE, 2: p1201})

# Opcode 1157: supplemental roster {1: [{1: hero_id, 4: level}]}
r1 = ProtobufCodec.encode_message({1: 34, 4: 33})   # Gaius Marius L33
r2 = ProtobufCodec.encode_message({1: 33, 4: 30})   # Constance L30
p1157 = ProtobufCodec.encode_field_bytes(1, r1) + ProtobufCodec.encode_field_bytes(1, r2)
frame_1157 = ProtobufCodec.encode_message({1: OP_HERO_ROSTER_SUPPLEMENT, 2: p1157})

# Opcode 1002: garrison under Tag 9 (field 4 list) + Tag 15 varint = unlocked barb level
g1 = ProtobufCodec.encode_message({1: 15})          # Joan on wall duty
tag9_inner = ProtobufCodec.encode_field_bytes(4, g1)
p1002 = (
    ProtobufCodec.encode_field_bytes(9, tag9_inner)
    + ProtobufCodec.encode_field_varint(15, 6)      # defeated up to L6 -> can hunt L7
    + ProtobufCodec.encode_field_varint(1, 4363)
)
frame_1002 = ProtobufCodec.encode_message({1: OP_CITY_STATE, 2: p1002})

# ---------------------------------------------------------------
# 2. Replay the CombatEngine ingestion loop (it.get(1)/it.get(2))
# ---------------------------------------------------------------
parsed_1201, parsed_1157 = [], []
garrison_ids = set()
server_unlocked_barb_lvl = None

for frame in (frame_1201, frame_1157, frame_1002):
    it = ProtobufCodec.decode_message(frame)          # same as combat_engine read loop
    op = it.get(1)
    if op == OP_HERO_CATALOGUE:
        parsed_1201 = parse_heroes_from_1201(it.get(2))
    elif op == OP_HERO_ROSTER_SUPPLEMENT:
        parsed_1157 = parse_roster_from_1157(it.get(2))
    elif op == OP_CITY_STATE:
        garrison_ids |= parse_wall_garrison_from_1002(it.get(2))
        server_unlocked_barb_lvl = parse_unlocked_barb_level_from_1002(it.get(2))

check("1201 roster parsed", len(parsed_1201) == 3, f"{[h['hero_id'] for h in parsed_1201]}")
check("1157 roster parsed", len(parsed_1157) == 2, f"{[h['hero_id'] for h in parsed_1157]}")
check("garrison extracted", garrison_ids == {15}, str(garrison_ids))
check("unlocked barb level", server_unlocked_barb_lvl == 6, str(server_unlocked_barb_lvl))

# ---------------------------------------------------------------
# 3. Roster resolution (merge -> garrison filter -> rank)
# ---------------------------------------------------------------
live_roster = merge_rosters(parsed_1201, parsed_1157)
all_ids = sorted(h["hero_id"] for h in live_roster)
check("merged roster", all_ids == [6, 15, 33, 34, 36], str(all_ids))

available_heroes = [h for h in all_ids if h not in garrison_ids]
check("garrison filtered", available_heroes == [6, 33, 34, 36], str(available_heroes))

combat_ranked = rank_heroes(live_roster, garrison_ids, "combat")
check("combat ranking (level desc)", combat_ranked == [6, 34, 36, 33], str(combat_ranked))

gather_ranked = rank_heroes(live_roster, garrison_ids, "gather")
check("gather ranking (specialist first)", gather_ranked[0] == 34, str(gather_ranked))

# Level auto-clamp logic (same rule as combat_engine step 4)
clamped = min(25, server_unlocked_barb_lvl + 1) if server_unlocked_barb_lvl else 11
check("target level auto-clamp (Tag15=6 -> L7)", clamped == 7, str(clamped))

# ---------------------------------------------------------------
# 4. Persistence bridge into a TEMP fleet file (isolated)
# ---------------------------------------------------------------
tmpdir = tempfile.mkdtemp()
tmp_fleet = os.path.join(tmpdir, "accounts_fleet.json")
with open(tmp_fleet, "w", encoding="utf-8") as f:
    json.dump({"account_email": "test@x", "characters": [
        {"role_id": 222157544, "name": "SIM", "commanders": [1]},
        {"role_id": 999, "name": "OTHER", "commanders": [1, 2, 3]},
    ]}, f)

orig_fleet_file = hero_parser.FLEET_FILE
hero_parser.FLEET_FILE = tmp_fleet
try:
    payload = build_roster_payload(live_roster, garrison_ids, source="sim")
    ok = hero_parser._update_fleet_file("222157544", payload)
    check("fleet file updated", ok is True)
    with open(tmp_fleet, encoding="utf-8") as f:
        new_fleet = json.load(f)
    sim_char = next(c for c in new_fleet["characters"] if str(c["role_id"]) == "222157544")
    other_char = next(c for c in new_fleet["characters"] if str(c["role_id"]) == "999")
    check("sim char commanders replaced", sim_char["commanders"] == [6, 15, 33, 34, 36], str(sim_char["commanders"]))
    check("sim char meta written",
          sim_char.get("commanders_meta", {}).get("combat_ranked") == [6, 34, 36, 33]
          and sim_char.get("commanders_meta", {}).get("wall_garrison") == [15],
          str(sim_char.get("commanders_meta")))
    check("other char untouched", other_char["commanders"] == [1, 2, 3], str(other_char["commanders"]))
    check("unknown role rejected", hero_parser._update_fleet_file("424242", payload) is False)
finally:
    hero_parser.FLEET_FILE = orig_fleet_file

# ---------------------------------------------------------------
print()
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("RESULT: ALL INTEGRATION SIMULATION TESTS PASSED ✓")
