import sys
import json

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from headless_client import ProtobufCodec

def inspect_dict(d, indent=0):
    pref = " " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            print(f"{pref}Tag {k} (dict):")
            inspect_dict(v, indent + 2)
        elif isinstance(v, list):
            print(f"{pref}Tag {k} (list of {len(v)} items):")
            for idx, item in enumerate(v):
                if isinstance(item, bytes):
                    try:
                        dec = ProtobufCodec.decode_message(item)
                        print(f"{pref}  [{idx}] (decoded bytes {len(item)}):")
                        inspect_dict(dec, indent + 4)
                    except:
                        print(f"{pref}  [{idx}]: bytes len {len(item)}: {item[:30]}")
                elif isinstance(item, dict):
                    print(f"{pref}  [{idx}] (dict):")
                    inspect_dict(item, indent + 4)
                else:
                    print(f"{pref}  [{idx}]: {item}")
        elif isinstance(v, bytes):
            try:
                dec = ProtobufCodec.decode_message(v)
                if isinstance(dec, dict) and len(dec) > 0:
                    print(f"{pref}Tag {k} (decoded bytes {len(v)}):")
                    inspect_dict(dec, indent + 2)
                else:
                    print(f"{pref}Tag {k}: raw bytes len {len(v)} -> {v}")
            except:
                print(f"{pref}Tag {k}: raw bytes len {len(v)} -> {v}")
        else:
            print(f"{pref}Tag {k}: {v}")

with open("/tmp/op1002_rsskd1.bin", "rb") as f:
    raw = f.read()

print(f"Read {len(raw)} bytes from /tmp/op1002_rsskd1.bin")
decoded = ProtobufCodec.decode_message(raw)
print("Top-level keys in p2:", list(decoded.keys()))
inspect_dict(decoded)
