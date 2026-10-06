import sqlite3
import json

c = sqlite3.connect('/home/ubuntu/bot-backend/rok_cloud.db')
row = c.execute('SELECT id, task_id, status, details FROM task_logs ORDER BY id DESC LIMIT 1').fetchone()
print("ID:", row[0], "TASK_ID:", row[1], "STATUS:", row[2])
if row and row[3]:
    d = json.loads(row[3]) if isinstance(row[3], str) else row[3]
    for w in d.get("wire_logs", []):
        print("WIRE:", w)
    print("DETAILS:", d.get("details"))
