import sqlite3

conn = sqlite3.connect("/home/ubuntu/bot-backend/rok_cloud.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("Accounts columns:")
for col in cur.execute("PRAGMA table_info(accounts)"):
    print(dict(col))

cur.execute("SELECT * FROM accounts WHERE id IN (SELECT account_id FROM characters WHERE role_id='232812223')")
row = cur.fetchone()
if row:
    d = dict(row)
    print("Account row keys:", list(d.keys()))
    print("Email:", d.get("email"))
