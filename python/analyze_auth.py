#!/usr/bin/env python3
"""Analyze the RokCrypto auth protocol from captured packets."""

import json

with open('game_capture.json') as f:
    data = json.load(f)

auth_pkts = [p for p in data if p['srv'] == 'auth_eu2']

print(f"=== Auth Protocol Analysis ({len(auth_pkts)} packets) ===\n")

for i, p in enumerate(auth_pkts):
    h = bytes.fromhex(p['hex'])
    d = p['d']
    direction = "S->C" if d == "S->C" else "C->S"
    
    # Parse prefix
    prefix = int.from_bytes(h[:2], 'big')
    body_len = prefix & 0x0FFF
    msg_type = (prefix >> 12) & 0xF
    
    print(f"[{i:3d}] {direction} {len(h)}B prefix=0x{prefix:04X} type={msg_type} bodylen={body_len}")
    
    # First packet from server should be greeting
    if i == 0 and d == "S->C" and len(h) == 26:
        print(f"  *** GREETING ***")
        print(f"  Raw: {h.hex()}")
        # Parse greeting: type(2) + nonce(8) + sub1(2) + sub2(2) + zero(2) + magic(4)
        nonce = h[2:10]
        sub1 = int.from_bytes(h[10:12], 'big')
        sub2 = int.from_bytes(h[12:14], 'big')
        zero = int.from_bytes(h[14:16], 'big')
        magic = int.from_bytes(h[16:20], 'big')
        tail = h[20:26]
        print(f"  Nonce: {nonce.hex()}")
        print(f"  sub1: {sub1} (0x{sub1:04X})")
        print(f"  sub2: {sub2} (0x{sub2:04X})")
        print(f"  zero: {zero}")
        print(f"  magic: {magic} (0x{magic:08X})")
        print(f"  tail: {tail.hex()}")
    
    # Client messages
    elif d == "C->S" and prefix == 0x0004:
        # 6B keepalive
        if len(h) == 6:
            seq = int.from_bytes(h[2:4], 'big')
            ack = int.from_bytes(h[4:6], 'big')
            print(f"  Keepalive seq={seq} ack={ack}")
        # 75B auth command
        elif len(h) == 75:
            print(f"  AUTH COMMAND")
            print(f"  Raw: {h.hex()}")
            # Likely: type(2) + encrypted_payload(69) + checksum(4)
    
    # Server data packets
    elif d == "S->C" and len(h) == 26:
        # RokCrypto encrypted data
        print(f"  RokCrypto data")
        print(f"  Raw: {h.hex()}")
    
    # Server response to auth
    elif d == "S->C" and len(h) == 6:
        print(f"  Auth response")
        print(f"  Raw: {h.hex()}")
    
    # Show hex for any unusual packets
    if len(h) not in [6, 26, 75]:
        print(f"  UNUSUAL PACKET: {h.hex()}")
