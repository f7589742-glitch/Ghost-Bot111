import sqlite3

conn = sqlite3.connect('/home/ubuntu/bot-backend/rok_cloud.db')
cur = conn.cursor()
print("--- character_inventories ---")
for col in cur.execute('PRAGMA table_info(character_inventories)'):
    print(col)

print("--- characters ---")
for col in cur.execute('PRAGMA table_info(characters)'):
    print(col)
