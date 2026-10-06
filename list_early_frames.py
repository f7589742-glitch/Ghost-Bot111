import json

d = json.load(open('/home/ubuntu/bot-backend/game_dump.json'))
for i in range(min(25, len(d))):
    e = d[i]
    print(f"[{i}] op={e.get('op')}")
