import json

d = json.load(open('/home/ubuntu/bot-backend/game_dump.json'))
for e in d:
    if e.get('op') == 121:
        print(json.dumps(e, indent=2))
