import sys
sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from app.services.protocol.hero_parser import parse_heroes_from_1002, parse_wall_garrison_from_1002

with open('/tmp/roster_probe/op1002.bin', 'rb') as f:
    b = f.read()

heroes = parse_heroes_from_1002(b)
garrison = parse_wall_garrison_from_1002(b)
print("parse_heroes_from_1002:", heroes)
print("parse_wall_garrison_from_1002:", garrison)
