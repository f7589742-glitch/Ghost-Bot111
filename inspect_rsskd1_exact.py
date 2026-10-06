import sys

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')
from headless_client import ProtobufCodec
from app.services.city_state_parser import parse_city_state_1002

with open('/tmp/op1002_real_rsskd1.bin', 'rb') as f:
    raw = f.read()

snap = parse_city_state_1002(raw)
print('Current parse_city_state_1002 output:', snap)

d = ProtobufCodec.decode_message(raw)
sub_f1 = ProtobufCodec.decode_message(d.get(1, b''))
print("\n=== sub_f1 top keys ===", list(sub_f1.keys()))
t9 = ProtobufCodec.decode_message(sub_f1.get(9, b''))
print("=== sub_f1 Tag 9 keys ===", list(t9.keys()))
print("Tag 9 Field 14 items:")
for it in t9.get(14, []):
    print(" ", ProtobufCodec.decode_message(it))

print("\n=== All numbers > 10,000 in whole packet ===")
def dump_nums(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            dump_nums(v, f"{p}.{k}")
    elif isinstance(o, list):
        for i, it in enumerate(o):
            dump_nums(it, f"{p}[{i}]")
    elif isinstance(o, bytes):
        try:
            dump_nums(ProtobufCodec.decode_message(o), f"{p}(p)")
        except: pass
    elif isinstance(o, int):
        if o > 10000:
            print(f"  {p} = {o:,}")

dump_nums(d)
