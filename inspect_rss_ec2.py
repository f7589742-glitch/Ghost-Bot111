import sqlite3
import json

conn = sqlite3.connect("/home/ubuntu/bot-backend/rok_cloud.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("--- CHARACTER_INVENTORIES for 232812223 ---")
for row in cur.execute("SELECT * FROM character_inventories WHERE role_id='232812223'"):
    print(dict(row))

print("\n--- CHARACTERS TABLE for 232812223 ---")
for row in cur.execute("SELECT * FROM characters WHERE role_id='232812223'"):
    print(dict(row))

print("\n--- ALL CHARACTERS IN BOT-2404 ---")
for row in cur.execute("SELECT role_id, name, food, wood, stone, gold, kingdom_id, city_hall, power FROM character_inventories WHERE bot_id='bot-2404'"):
    print(dict(row))
