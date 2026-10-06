import sqlite3

conn = sqlite3.connect('/home/ubuntu/bot-backend/rok_cloud.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("--- Accounts and Characters for bot-2404 ---")
for r in cur.execute("""
    SELECT c.role_id, c.name, c.kingdom_id, a.email, a.app_token, a.app_uid, a.udid, a.proxy_url
    FROM characters c
    JOIN accounts a ON c.account_id = a.id
    WHERE a.bot_id = 'bot-2404' OR c.name LIKE '%KD%'
"""):
    print(r["role_id"], r["name"], r["kingdom_id"], r["email"])

print("\n--- Accounts and Characters for bot-2911 ---")
for r in cur.execute("""
    SELECT c.role_id, c.name, c.kingdom_id, a.email, a.app_token, a.app_uid, a.udid, a.proxy_url
    FROM characters c
    JOIN accounts a ON c.account_id = a.id
    WHERE a.bot_id = 'bot-2911' OR c.name LIKE '%Nucro%'
"""):
    print(r["role_id"], r["name"], r["kingdom_id"], r["email"])
