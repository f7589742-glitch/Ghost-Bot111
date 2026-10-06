import sqlite3
import random
from datetime import datetime, timedelta

con = sqlite3.connect('/home/ubuntu/bot-backend/rok_cloud.db')
now = datetime.utcnow()

with con:
    # 1. Reset all accounts across ALL bot rooms
    accounts = con.execute("SELECT id, email, bot_id FROM accounts WHERE is_active = 1").fetchall()
    print(f"🔄 Resetting {len(accounts)} accounts across ALL rooms...")
    for acc in accounts:
        aid, email, bot_id = acc
        jitter = random.randint(-5, 5)
        new_next = (now + timedelta(minutes=180 + jitter)).strftime("%Y-%m-%d %H:%M:%S")
        con.execute("UPDATE accounts SET next_run = ?, status = 'Enabled' WHERE id = ?", (new_next, aid))
        print(f"  [{bot_id}] Account {aid} ({email}) -> next_run: {new_next}")

    # 2. Reset all characters across ALL bot rooms
    characters = con.execute("SELECT id, name, role_id, account_id FROM characters WHERE enabled = 1").fetchall()
    print(f"\n🔄 Resetting {len(characters)} characters across ALL rooms...")
    for c in characters:
        cid, name, role_id, account_id = c
        jitter = random.randint(-5, 5)
        new_next = (now + timedelta(minutes=180 + jitter)).strftime("%Y-%m-%d %H:%M:%S")
        con.execute("UPDATE characters SET next_run = ? WHERE id = ?", (new_next, cid))
        print(f"  Character {cid} [{name}] (#{role_id}) -> next_run: {new_next}")

    # 3. Synchronize global top-level next_run_timestamp in bot_settings
    global_next = (now + timedelta(minutes=180)).strftime("%Y-%m-%d %H:%M:%S")
    bot_ids = set([a[2] for a in accounts if a[2]]) or {'bot-1', 'bot-2', 'bot-3', 'bot-4'}
    for bid in bot_ids:
        con.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (f"next_run_timestamp_{bid}", global_next))
        con.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (f"run_interval_hours_{bid}", "3"))
    con.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", ("next_run_timestamp", global_next))
    con.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", ("run_interval_hours", "3"))

print(f"\n✅ [SUCCESS] Global timer reset complete. Reference 3h timestamp: {global_next}")
