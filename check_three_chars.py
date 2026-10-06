import sqlite3

conn = sqlite3.connect("/home/ubuntu/bot-backend/rok_cloud.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

for row in cur.execute("SELECT role_id, name, food, wood, stone, gold, kingdom_id, city_hall_level, power, updated_at FROM character_inventories WHERE role_id IN ('231469447', '231464370', '232812223')"):
    print(dict(row))
