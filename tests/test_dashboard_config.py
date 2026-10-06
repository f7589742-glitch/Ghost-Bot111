"""Regression checks use a disposable database and never connect to the game."""
import copy
import sqlite3
import unittest
import zlib
from collections import Counter

from app import database
from app.models import CharacterSettingsDAO
from app.services.dashboard_config import (
    dashboard_patch, effective_settings, normalize_gather_config, read_room_config, save_room_config,
)
from app.services.smart_gather_search import (
    allocate_gathering_commanders, decode_stream_chunks, determine_march_resource_targets, parse_max_node_level,
)

CONFIG = {
    "gatherFoodMarches": 1, "gatherWoodMarches": 1, "gatherStoneMarches": 2,
    "gatherGoldMarches": 0, "autoBalanceLowest": False, "maxNodeLevel": 0,
    "skipPartiallyGathered": True, "avoidEnemyTerritory": True,
    "runIntervalHours": "4", "autoTrainTroops": False, "trainSiege": "T1",
    "huntBarbs": False, "healHospital": True,
}


class DashboardConfigTests(unittest.TestCase):
    def setUp(self):
        self.previous = getattr(database._local, "connection", None)
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        database._local.connection = self.db
        database.init_db()
        self.addCleanup(self.restore_connection)
        # These production columns were introduced by deployment migrations.
        self.db.execute("ALTER TABLE accounts ADD COLUMN bot_id TEXT")
        self.db.execute("ALTER TABLE accounts ADD COLUMN next_run TIMESTAMP")
        for aid, uid, bid in ((1, "owner", "bot-2"), (2, "owner", "bot-3"), (3, "other", "bot-2")):
            self.db.execute("INSERT INTO accounts (id,email,user_id,bot_id,encrypted_password,udid) VALUES (?,?,?,?,?,?)",
                            (aid, f"test{aid}@example.invalid", uid, bid, "unused", "unused"))
            self.db.execute("INSERT INTO characters (id,account_id,role_id,name,kingdom_id) VALUES (?,?,?,?,?)",
                            (aid, aid, str(aid), f"test{aid}", 1))
        self.db.commit()

    def restore_connection(self):
        self.db.close()
        database._local.connection = self.previous

    def test_legacy_boolean_does_not_override_count(self):
        normalized = normalize_gather_config({"food": True, "food_marches": 1,
            "wood": True, "wood_marches": 1, "stone": True, "stone_marches": 2, "gold": False})
        self.assertEqual(normalized["marches"], {"food": 1, "wood": 1, "stone": 2, "gold": 0})

    def test_roundtrip_and_tenant_room_isolation(self):
        other_room = copy.deepcopy(CharacterSettingsDAO.get_by_character_id(2))
        other_user = copy.deepcopy(CharacterSettingsDAO.get_by_character_id(3))
        result = save_room_config("owner", "bot-2", CONFIG)
        self.assertEqual(result["characters_updated"], 1)
        self.assertEqual(result["config"], CONFIG)
        self.assertIsNone(read_room_config("owner", "bot-3"))
        self.assertIsNone(read_room_config("other", "bot-2"))
        self.assertEqual(CharacterSettingsDAO.get_by_character_id(2), other_room)
        self.assertEqual(CharacterSettingsDAO.get_by_character_id(3), other_user)
        gather = CharacterSettingsDAO.get_by_character_id(1)["gather"]
        self.assertEqual(gather["stone_marches"], 2)
        self.assertIs(gather["auto_balance_lowest_rss"], False)
        self.assertEqual(gather["max_node_level"], 0)

    def test_new_character_and_stale_task_use_latest_room_settings(self):
        save_room_config("owner", "bot-2", CONFIG)
        result = effective_settings({"id": 999}, {"user_id": "owner", "bot_id": "bot-2"},
                                    {"gather": {"stone_marches": 1, "auto_balance": True}})
        self.assertEqual(result["gather"]["stone_marches"], 2)
        self.assertIs(result["gather"]["auto_balance"], False)
        self.assertIs(result["training"]["enabled"], False)

    def test_invalid_config_is_not_saved(self):
        for changes in ({"maxNodeLevel": 7}, {"gatherStoneMarches": -1}, {"runIntervalHours": "nan"}):
            with self.assertRaises(ValueError):
                save_room_config("owner", "bot-2", {**CONFIG, **changes})
            self.assertIsNone(read_room_config("owner", "bot-2"))

    def test_four_manual_marches_and_zero_allocations(self):
        gather = dashboard_patch(CONFIG)["gather"]
        self.assertEqual(Counter(determine_march_resource_targets(4, gather, {})),
                         Counter(food=1, wood=1, stone=2))
        self.assertEqual(determine_march_resource_targets(0, gather, {}), [])
        zero = normalize_gather_config({r: 0 for r in ("food", "wood", "stone", "gold")})
        self.assertEqual(determine_march_resource_targets(4, zero, {}), [])
        self.assertEqual(parse_max_node_level(0), 6)

    def test_primary_commanders_are_reserved_for_four_queues(self):
        roster = [{"hero_id": hid, "level": 30, "star": 3} for hid in (24, 34, 38, 33)]
        allocation = allocate_gathering_commanders(roster, 4, set(), set(), set(), [])
        self.assertEqual(len(allocation), 4)

    def test_all_compressed_streams_decoded_after_frame_header(self):
        # Protobuf op=1003 and op=1201 in two concatenated streams.
        packet = b"\xff\xff" + zlib.compress(b"\x08\xeb\x07\x12\x00") + zlib.compress(b"\x08\xb1\x09\x12\x00", 9)
        _, chunks = decode_stream_chunks(packet)
        self.assertTrue({1003, 1201}.issubset({c.get(1) for c in chunks if isinstance(c, dict) and isinstance(c.get(1), int)}))


if __name__ == "__main__":
    unittest.main()
