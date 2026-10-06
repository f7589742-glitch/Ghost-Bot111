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

def print_rss_in_msg(tag_name, dec):
    if not isinstance(dec, dict):
        return
    for k, v in dec.items():
        if isinstance(v, list):
            for i, it in enumerate(v):
                if isinstance(it, bytes):
                    try:
                        it_d = ProtobufCodec.decode_message(it)
                        print_rss_in_msg(f"{tag_name}.{k}[{i}]", it_d)
                    except: pass
                elif isinstance(it, dict):
                    print_rss_in_msg(f"{tag_name}.{k}[{i}]", it)
        elif isinstance(v, bytes) and len(v) > 0:
            try:
                v_d = ProtobufCodec.decode_message(v)
                print_rss_in_msg(f"{tag_name}.{k}", v_d)
            except: pass
        elif isinstance(v, int):
            if v > 100_000:
                print(f"[{tag_name}] key={k} -> {v:,}")

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
    r, w = await open_game_connection(host, port, proxy_url=proxy)

    hdr = await r.readexactly(2)
    gp = await r.readexactly((hdr[0] << 8) | hdr[1])
    sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(gp).get(2, b''))
    tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
    c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)

    w.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1050, 2: b''}))))
    await w.drain()

    deadline = asyncio.get_event_loop().time() + 5.0
    while asyncio.get_event_loop().time() < deadline:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.5)
            length = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(r.readexactly(length), timeout=0.5)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            if isinstance(m, dict):
                op = m.get(1)
                p = m.get(2)
                if op == 125 and isinstance(p, bytes):
                    d125 = ProtobufCodec.decode_message(p)
                    print("\n=== OPCODE 125 ===")
                    print_rss_in_msg("op125", d125)
                elif op == 9999 and isinstance(p, bytes):
                    # Opcode 9999 can have sub frames
                    d9999 = ProtobufCodec.decode_message(p)
                    print_rss_in_msg("op9999", d9999)
                elif op == 1002 and isinstance(p, bytes):
                    d1002 = ProtobufCodec.decode_message(p)
                    print("\n=== OPCODE 1002 ===")
                    print_rss_in_msg("op1002", d1002)
                elif op == 1050 and isinstance(p, bytes):
                    d1050 = ProtobufCodec.decode_message(p)
                    print("\n=== OPCODE 1050 ===")
                    print_rss_in_msg("op1050", d1050)
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            break
    w.close()

if __name__ == "__main__":
    asyncio.run(main())
