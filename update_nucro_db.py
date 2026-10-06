import sqlite3
import json

con = sqlite3.connect('/home/ubuntu/bot-backend/rok_cloud.db')
cmds = [15, 34, 36, 33, 38, 6, 24, 1]
con.execute('UPDATE character_settings SET commanders_json=? WHERE character_id=108', (json.dumps(cmds),))
con.commit()
row = con.execute('SELECT commanders_json FROM character_settings WHERE character_id=108').fetchone()
print('Updated NUCROSHOP commanders_json:', row[0])
