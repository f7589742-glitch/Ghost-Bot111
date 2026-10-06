import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from headless_client import ProtobufCodec, LOGIN_PAYLOAD

# Decode and inspect the full LOGIN_PAYLOAD
top = ProtobufCodec.decode_message(LOGIN_PAYLOAD)
print("Top-level:", json.dumps(top, indent=2, default=str))

if 2 in top:
    inner = ProtobufCodec.decode_message(top[2])
    print("\nInner:", json.dumps(inner, indent=2, default=str))
    
    if 7 in inner:
        auth = ProtobufCodec.decode_message(inner[7])
        print("\nAuth (field7):", json.dumps(auth, indent=2, default=str))

    if 4 in inner:
        print("\nField 4:", inner[4])

    # Decode all string fields to see what they contain
    for k, v in sorted(inner.items()):
        if isinstance(v, bytes):
            try:
                decoded = v.decode('utf-8', errors='replace')
                if len(decoded) > 3 and all(32 <= ord(c) < 127 for c in decoded):
                    print(f"  Field {k} (str): {decoded}")
                else:
                    print(f"  Field {k} (bytes): {v.hex()}")
            except:
                print(f"  Field {k} (bytes): {v.hex()}")
        else:
            print(f"  Field {k}: {v}")
