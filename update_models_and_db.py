import sqlite3
import re

# 1. DB Migration
conn = sqlite3.connect('/home/ubuntu/bot-backend/rok_cloud.db')
cur = conn.cursor()
try:
    cur.execute("ALTER TABLE character_inventories ADD COLUMN gems INTEGER DEFAULT 0")
    print("Added gems column to character_inventories")
except Exception as e:
    print("character_inventories gems:", e)

try:
    cur.execute("ALTER TABLE characters ADD COLUMN gems INTEGER DEFAULT 0")
    print("Added gems column to characters")
except Exception as e:
    print("characters gems:", e)

conn.commit()
conn.close()

# 2. Update app/models.py
models_path = '/home/ubuntu/bot-backend/app/models.py'
with open(models_path, 'r', encoding='utf-8') as f:
    content = f.read()

new_upsert = """    @staticmethod
    def upsert(
        bot_id: str,
        role_id: str,
        name: str = "",
        kingdom_id: int = 0,
        city_hall_level: int = 0,
        power: int = 0,
        food: int = 0,
        wood: int = 0,
        stone: int = 0,
        gold: int = 0,
        gems: int = 0
    ) -> None:
        if not role_id:
            return
        con = get_db_connection()
        norm_bot_id = InventoryDAO._normalize_bot_id(bot_id, role_id=str(role_id), name=name)
        with con:
            con.execute(\"\"\"
                INSERT INTO character_inventories (
                    bot_id, role_id, name, kingdom_id, city_hall_level, power,
                    food, wood, stone, gold, gems, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(bot_id, role_id) DO UPDATE SET
                    name = CASE WHEN excluded.name != '' THEN excluded.name ELSE character_inventories.name END,
                    kingdom_id = CASE WHEN excluded.kingdom_id > 0 THEN excluded.kingdom_id ELSE character_inventories.kingdom_id END,
                    city_hall_level = CASE WHEN excluded.city_hall_level > 0 THEN excluded.city_hall_level ELSE character_inventories.city_hall_level END,
                    power = CASE WHEN excluded.power > 0 THEN excluded.power ELSE character_inventories.power END,
                    food = CASE WHEN excluded.food > 0 THEN excluded.food ELSE character_inventories.food END,
                    wood = CASE WHEN excluded.wood > 0 THEN excluded.wood ELSE character_inventories.wood END,
                    stone = CASE WHEN excluded.stone > 0 THEN excluded.stone ELSE character_inventories.stone END,
                    gold = CASE WHEN excluded.gold > 0 THEN excluded.gold ELSE character_inventories.gold END,
                    gems = CASE WHEN excluded.gems > 0 THEN excluded.gems ELSE character_inventories.gems END,
                    updated_at = CURRENT_TIMESTAMP
            \"\"\", (
                norm_bot_id, str(role_id), name, int(kingdom_id or 0),
                int(city_hall_level or 0), int(power or 0),
                int(food or 0), int(wood or 0), int(stone or 0), int(gold or 0), int(gems or 0)
            ))
            con.execute(\"\"\"
                UPDATE characters SET
                    food = CASE WHEN ? > 0 THEN ? ELSE food END,
                    wood = CASE WHEN ? > 0 THEN ? ELSE wood END,
                    stone = CASE WHEN ? > 0 THEN ? ELSE stone END,
                    gold = CASE WHEN ? > 0 THEN ? ELSE gold END,
                    gems = CASE WHEN ? > 0 THEN ? ELSE gems END,
                    power = CASE WHEN ? > 0 THEN ? ELSE power END,
                    city_level = CASE WHEN ? > 0 THEN ? ELSE city_level END,
                    city_hall = CASE WHEN ? > 0 THEN ? ELSE city_hall END,
                    last_run_at = CURRENT_TIMESTAMP
                WHERE role_id = ?
            \"\"\", (
                int(food or 0), int(food or 0),
                int(wood or 0), int(wood or 0),
                int(stone or 0), int(stone or 0),
                int(gold or 0), int(gold or 0),
                int(gems or 0), int(gems or 0),
                int(power or 0), int(power or 0),
                int(city_hall_level or 0), int(city_hall_level or 0),
                int(city_hall_level or 0), int(city_hall_level or 0),
                str(role_id)
            ))"""

# Find old def upsert(...) and replace until @staticmethod
pattern = r"    @staticmethod\s+def upsert\(.*?str\(role_id\)\s*\)\s*\)"
subbed, count = re.subn(pattern, new_upsert, content, flags=re.DOTALL)
if count > 0:
    with open(models_path, 'w', encoding='utf-8') as f:
        f.write(subbed)
    print("Successfully updated InventoryDAO.upsert in app/models.py")
else:
    print("Pattern not matched for InventoryDAO.upsert!")
