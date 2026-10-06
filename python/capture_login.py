#!/usr/bin/env python3
"""Capture the full login flow - kill game, sniff, restart, capture tokens."""

import sys
import time
import json
import threading
import pydivert
import subprocess

SERVERS = {
    "43.159.112.101": "auth_eu2", "43.159.113.101": "auth_eu",
    "34.54.22.150": "auth_asia", "104.76.183.141": "auth_teez",
    "43.109.149.66": "cdn1", "43.109.149.68": "cdn2",
    "43.109.149.71": "cdn3", "43.109.150.39": "cdn4",
    "23.202.60.27": "akamai1", "23.202.60.26": "akamai2",
    "23.202.60.25": "akamai3", "23.202.60.17": "akamai4",
    "47.253.8.175": "game1", "27.222.18.147": "game2",
    "34.120.214.113": "gcloud", "34.128.174.63": "game3",
    "43.175.228.94": "analytics", "43.145.17.237": "lilith1",
    "43.137.87.65": "lilith2", "157.240.203.14": "facebook",
    "74.125.206.188": "gpush", "172.217.168.131": "google",
    "172.217.118.4": "google2", "47.252.97.14": "cdn5",
    "8.222.131.165": "aliyun1", "8.222.179.158": "aliyun2",
}

ALL_GAME_IPS = set(SERVERS.keys())


def extract_sni(payload):
    try:
        if len(payload) < 12 or payload[0] != 0x16 or payload[5] != 0x01:
            return None
        offset = 5 + 4 + 2 + 32 + 1
        sid_len = payload[offset]
        offset += 1 + sid_len
        cs_len = (payload[offset] << 8) | payload[offset + 1]
        offset += 2 + cs_len
        cm_len = payload[offset]
        offset += 1 + cm_len
        if offset + 2 > len(payload):
            return None
        ext_len = (payload[offset] << 8) | payload[offset + 1]
        offset += 2
        ext_end = offset + ext_len
        while offset + 4 < ext_end:
            ext_type = (payload[offset] << 8) | payload[offset + 1]
            ext_data_len = (payload[offset + 2] << 8) | payload[offset + 3]
            offset += 4
            if ext_type == 0x0000 and offset + 5 <= len(payload):
                name_len = (payload[offset + 3] << 8) | payload[offset + 4]
                end = offset + 5 + name_len
                if end <= len(payload):
                    return payload[offset + 5:end].decode('ascii', errors='ignore')
            offset += ext_data_len
        return None
    except Exception:
        return None


def safe_send(w, pkt):
    try:
        w.send(pkt)
    except Exception:
        pass


def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    print(f"[*] Login flow capture - {duration}s")
    print("[*] Starting game...")

    # Start the game
    ld_path = r"C:\LDPlayer\LDPlayer14\dnconsole.exe"
    subprocess.Popen([ld_path, "runapp", "--index", "0", "--packagename", "com.lilithgame.roc.gp"],
                     creationflags=subprocess.CREATE_NO_WINDOW)
    print("[*] Game launched, sniffing...")

    captured = []
    auth_flow = []
    stop = threading.Event()
    threading.Timer(duration, stop.set).start()

    with pydivert.WinDivert("tcp") as w:
        start = time.time()
        while not stop.is_set():
            try:
                pkt = w.recv()
            except Exception:
                continue

            try:
                ip_src = str(pkt.ipv4.src_addr) if pkt.ipv4 else None
                ip_dst = str(pkt.ipv4.dst_addr) if pkt.ipv4 else None
                src_port = pkt.src_port
                dst_port = pkt.dst_port
            except Exception:
                safe_send(w, pkt)
                continue

            if not ip_src or not ip_dst:
                safe_send(w, pkt)
                continue

            is_game = ip_src in ALL_GAME_IPS or ip_dst in ALL_GAME_IPS
            if not is_game:
                safe_send(w, pkt)
                continue

            server = SERVERS.get(ip_dst) or SERVERS.get(ip_src) or "unknown"
            direction = "C->S" if ip_dst in ALL_GAME_IPS else "S->C"

            payload = bytes(pkt.payload) if pkt.payload else b""

            if payload:
                sni_info = ""
                if len(payload) > 5 and payload[0] == 0x16 and payload[5] == 0x01:
                    sni = extract_sni(payload)
                    if sni:
                        sni_info = f" SNI={sni}"
                        print(f"\n  [TLS] {sni}")

                if server.startswith("auth"):
                    prefix = int.from_bytes(payload[:2], 'big') if len(payload) >= 2 else 0
                    print(f"  [AUTH {direction}] {len(payload)}B prefix=0x{prefix:04X} {payload[:40].hex()}")
                    
                    auth_flow.append({
                        "t": round(time.time() - start, 3),
                        "dir": direction, "server": server,
                        "raw": payload.hex()
                    })
                elif server == "analytics":
                    if payload[:4] == b'WHMP':
                        ver = payload[4]
                        print(f"  [WHMP {direction}] ver={ver} {len(payload)}B {payload[:60].hex()}")
                elif server.startswith("gcloud"):
                    if len(payload) > 5 and payload[0] == 0x16 and payload[5] == 0x01:
                        print(f"  [TLS {direction}] {server} {len(payload)}B SNI captured")
                    elif payload[:4] == b'\x17\x03\x03':
                        print(f"  [TLS DATA {direction}] {server} {len(payload)}B {payload[:40].hex()}")

                captured.append({
                    "t": round(time.time() - start, 3),
                    "src": ip_src, "dst": ip_dst,
                    "sp": src_port, "dp": dst_port,
                    "d": direction, "srv": server,
                    "hex": payload.hex()
                })

            safe_send(w, pkt)

    print(f"\n[*] Done. {len(captured)} packets, {len(auth_flow)} auth packets")

    with open("login_capture.json", "w") as f:
        json.dump(captured, f, indent=2)
    
    with open("auth_flow.json", "w") as f:
        json.dump(auth_flow, f, indent=2)

    print("[*] Saved to login_capture.json + auth_flow.json")

    # Print auth flow summary
    if auth_flow:
        print(f"\n=== Auth Flow ({len(auth_flow)} packets) ===")
        for i, p in enumerate(auth_flow):
            h = bytes.fromhex(p['raw'])
            prefix = int.from_bytes(h[:2], 'big')
            print(f"  [{i}] {p['dir']} {p['server']} {len(h)}B prefix=0x{prefix:04X}")
            
            if i == 0 and p['dir'] == 'S->C' and len(h) == 26:
                nonce = h[2:10]
                sub1 = int.from_bytes(h[10:12], 'big')
                sub2 = int.from_bytes(h[12:14], 'big')
                print(f"    GREETING: nonce={nonce.hex()} sub1={sub1}(0x{sub1:04X}) sub2={sub2}(0x{sub2:04X})")

            if prefix == 0x0049 and p['dir'] == 'C->S':
                print(f"    AUTH CMD: {h.hex()}")
            
            if prefix == 0x0004 and p['dir'] == 'S->C':
                print(f"    AUTH RESP: {h.hex()}")


if __name__ == "__main__":
    main()
