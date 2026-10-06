import sqlite3, json
conn = sqlite3.connect("/home/ubuntu/bot-backend/rok_cloud.db")
cols = [r[1] for r in conn.execute("PRAGMA table_info(characters)").fetchall()]
print("characters cols:", cols)
row = conn.execute("SELECT * FROM characters WHERE role_id='222157544'").fetchone()
print("NUCROSHOP character:", dict(zip(cols, row)) if row else None)

s_cols = [r[1] for r in conn.execute("PRAGMA table_info(character_settings)").fetchall()]
print("character_settings cols:", s_cols)
s_row = conn.execute("SELECT * FROM character_settings WHERE character_id=?", (row[0],)).fetchone() if row else None
if s_row:
    s_dict = dict(zip(s_cols, s_row))
    for k, v in s_dict.items():
        if isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
            try:
                s_dict[k] = json.loads(v)
            except Exception:
                pass
    print("NUCROSHOP settings:", s_dict)
