import sqlite3

con = sqlite3.connect('/home/ubuntu/bot-backend/rok_cloud.db')
con.row_factory = sqlite3.Row
chars = con.execute('SELECT id, name, role_id, city_level, alliance_tag FROM characters').fetchall()
for c in chars:
    print(dict(c))
