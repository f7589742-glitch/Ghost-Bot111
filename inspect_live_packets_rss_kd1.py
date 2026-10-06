import asyncio
import json
import sys
import os
import sqlite3

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
import zlib

def safe_decompress(b: bytes) -> bytes:
    try:
        return zlib.decompress(b)
    except Exception:
        return b

def unpack_frames(m):
    out = []
    if not isinstance(m, dict):
        return out
    if 1 in m and isinstance(m[1], int):
        out.append(m)
    # Check if nested list of messages or frames
    for v in m.values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and 1 in item and isinstance(item[1], int):
                    out.append(item)
                elif isinstance(item, bytes):
                    try:
                        dec = ProtobufCodec.decode_message(item)
                        if isinstance(dec, dict) and 1 in dec and isinstance(dec[1], int):
                            out.append(dec)
                    except Exception:
                        pass
    return out

def find_numbers_in_obj(obj, path=""):
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            results.extend(find_numbers_in_obj(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            results.extend(find_numbers_in_obj(item, f"{path}[{idx}]"))
    elif isinstance(obj, (bytes, bytearray)):
        try:
            dec = ProtobufCodec.decode_message(bytes(obj))
            if isinstance(dec, dict) and len(dec) > 0:
                results.extend(find_numbers_in_obj(dec, f"{path}(proto)"))
        except Exception:
            pass
    elif isinstance(obj, int) and not isinstance(obj, bool):
        # Look for anything > 10,000
        if obj > 10000:
            results.append((obj, path))
    return results

async def main():
    conn = sqlite3.connect("/home/ubuntu/bot-backend/rok_cloud.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT a.email, a.app_token, a.app_uid, a.udid, a.proxy_url, c.role_id, c.kingdom_id, c.name
        FROM characters c
        JOIN accounts a ON c.account_id = a.id
        WHERE c.role_id = '232812223'
    """)
    row = dict(cur.fetchone())
    print("Found character:", row["name"], row["role_id"], "in kingdom:", row["kingdom_id"])

    from fleet_manager import resolve_login_bytes
    login_bytes = resolve_login_bytes({
        'role_id': int(row['role_id']),
        'app_token': row['app_token'],
        'app_uid': row['app_uid'],
        'udid': row['udid'],
        'kingdom_id': row['kingdom_id']
    })

    host = 'rocgate.lilithgame.com'
    port = 3101
    proxy = row.get('proxy_url')
    print(f"Connecting to {host}:{port} (proxy: {bool(proxy)})...")
    r, w = await open_game_connection(host, port, proxy_url=proxy)

    hdr = await r.readexactly(2)
    gp = await r.readexactly((hdr[0] << 8) | hdr[1])
    sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(gp).get(2, b''))
    tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
    c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)

    print("Connected & handshake OK! Sending login packets...")
    w.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1050, 2: b''}))))
    await w.drain()

    deadline = asyncio.get_event_loop().time() + 5.0
    all_hits = []

    while asyncio.get_event_loop().time() < deadline:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.5)
            length = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(r.readexactly(length), timeout=0.5)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            
            # Print top-level opcodes
            if isinstance(m, dict):
                op = m.get(1)
                p = m.get(2)
                p_len = len(p) if isinstance(p, (bytes, bytearray)) else 0
                print(f"[PACKET] Opcode {op}, payload len {p_len}")
                hits = find_numbers_in_obj(m, f"op_{op}")
                for val, pth in hits:
                    # Filter for numbers near 7.6M, 4.8M, 7.3M, 694K or 57K, 72K, 55K, 37K
                    if (7_000_000 <= val <= 8_500_000) or \
                       (4_000_000 <= val <= 5_500_000) or \
                       (600_000 <= val <= 800_000) or \
                       (50_000 <= val <= 80_000) or \
                       (val > 500_000 and "rss" in pth.lower() or "item" in pth.lower()):
                        print(f"   --> MATCH: {val:,} at {pth}")
                        all_hits.append((val, pth))

                # If op is 1002 or 1050 or 1004, let's dump subfield structures!
                if op in (1002, 1050, 1004, 1003, 1010):
                    if isinstance(p, (bytes, bytearray)):
                        try:
                            dec_sub = ProtobufCodec.decode_message(p)
                            print(f"   [DUMP OP {op}] sub keys: {list(dec_sub.keys())}")
                            if op == 1002 and 1 in dec_sub and isinstance(dec_sub[1], (bytes, bytearray)):
                                sub_f1 = ProtobufCodec.decode_message(dec_sub[1])
                                print(f"   [DUMP OP 1002 f1] sub_f1 keys: {list(sub_f1.keys())}")
                                # Check all keys of sub_f1
                                for k, v in sub_f1.items():
                                    hits_k = find_numbers_in_obj(v, f"1002.sub_f1.{k}")
                                    for val, pth in hits_k:
                                        if val > 100_000 or (50_000 <= val <= 80_000):
                                            print(f"      f1.{k} match: {val:,} at {pth}")
                        except Exception as ex:
                            print(f"   Err decoding op {op}: {ex}")

        except asyncio.TimeoutError:
            continue
        except Exception as e:
            print("Loop exit:", e)
            break

    w.close()
    print("Done! Total matches found:", len(all_hits))

if __name__ == "__main__":
    asyncio.run(main())
