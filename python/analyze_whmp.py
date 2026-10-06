#!/usr/bin/env python3
import json, zlib

with open('game_capture.json') as f:
    data = json.load(f)

for p in data:
    if p['srv'] != 'analytics':
        continue
    h = bytes.fromhex(p['hex'])
    d = p['d']
    print(f"\n[{d}] {len(h)}B")
    print(f"  Hex: {h[:60].hex()}")
    
    # WHMP format: "WHMP" + version(1B) + type(1B) + id(2B) + status(4B) + length(4B) + body
    if h[:4] == b'WHMP':
        ver = h[4]
        mtype = h[5]
        mid = int.from_bytes(h[6:8], 'big')
        status = int.from_bytes(h[8:12], 'big')
        body_len = int.from_bytes(h[12:16], 'big')
        print(f"  WHMP: ver={ver} type={mtype} id={mid} status={status} body_len={body_len}")
        body = h[16:]
        
        # Try to decompress
        if body_len > 0:
            # Check if zlib compressed (starts with 0x78)
            if body and body[0] == 0x78:
                try:
                    decompressed = zlib.decompress(body)
                    print(f"  Decompressed: {len(decompressed)}B")
                    print(f"  Data: {decompressed[:100].hex()}")
                    # Try to parse as protobuf
                    print(f"  Text: {decompressed[:200]}")
                except:
                    print(f"  (zlib decompress failed)")
            else:
                print(f"  Body: {body[:100].hex()}")
    else:
        print(f"  Raw: {h.hex()}")
