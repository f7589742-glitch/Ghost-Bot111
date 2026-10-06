import sqlite3

conn = sqlite3.connect('/home/ubuntu/bot-backend/rok_cloud.db')
c = conn.cursor()
c.execute("SELECT id, email, bot_id FROM accounts")
for r in c.fetchall():
    print(r)
