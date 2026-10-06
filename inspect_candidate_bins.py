import sys
sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')
from headless_client import ProtobufCodec

def inspect_bin(filename):
    print(f"================== {filename} ==================")
    with open(f"/tmp/roster_probe/{filename}", "rb") as f:
        b = f.read()
    m = ProtobufCodec.decode_message(b)
    print("Top keys:", list(m.keys()))
    for k, v in m.items():
        if isinstance(v, list):
            print(f"  Field {k}: List of {len(v)} items")
            if v and isinstance(v[0], bytes):
                print(f"    sample: {ProtobufCodec.decode_message(v[0])}")
            elif v:
                print(f"    sample: {v[0]}")
        elif isinstance(v, bytes):
            print(f"  Field {k}: bytes len {len(v)}")
            try:
                dec = ProtobufCodec.decode_message(v)
                print(f"    decoded keys: {list(dec.keys())}")
            except: pass
        else:
            print(f"  Field {k}: {v}")

for fn in ['op105.bin', 'op111.bin', 'op3944.bin', 'op9875.bin']:
    inspect_bin(fn)
