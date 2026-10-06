import json

d = json.load(open('/home/ubuntu/bot-backend/game_dump.json'))
for i, e in enumerate(d):
    if e.get('op') == 121:
        print(f"=== Opcode 121 at index {i} ===")
        for j in range(max(0, i-5), min(len(d), i+3)):
            print(f"  [{j}] dir={d[j].get('dir', '?')} op={d[j].get('op')} d={str(d[j].get('d'))[:120]}")
