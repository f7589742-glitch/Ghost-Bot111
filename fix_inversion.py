import sqlite3

conn = sqlite3.connect('/home/ubuntu/bot-backend/rok_cloud.db')
c = conn.cursor()

# Set Farm Bot #2404 (17 Slots - KD Farm Fleet)
c.execute("""
    UPDATE accounts 
    SET bot_id = 'bot-2404' 
    WHERE email LIKE '%farm4127%' OR email LIKE '%farm4121%' OR id IN (41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51)
""")

# Set Farm Bot #2911 (11 Slots - Kingdom 3057 NucroShop Fleet)
c.execute("""
    UPDATE accounts 
    SET bot_id = 'bot-2911' 
    WHERE email LIKE '%farm12213%' OR email LIKE '%ghaith.malek%' OR id IN (36, 37, 38, 39, 40)
""")

conn.commit()

print("UPDATED ACCOUNTS:")
c.execute("""
    SELECT a.bot_id, a.id, a.email, COUNT(c.id) as char_count, GROUP_CONCAT(c.name)
    FROM accounts a
    LEFT JOIN characters c ON c.account_id = a.id
    GROUP BY a.id
    ORDER BY a.bot_id, a.id
""")
for r in c.fetchall():
    print(f"[{r[0]}] Acc #{r[1]} ({r[2]}) -> {r[3]} chars: {r[4]}")

conn.close()
