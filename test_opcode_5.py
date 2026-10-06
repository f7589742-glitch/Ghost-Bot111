import asyncio
import json
import sys
import os
import sqlite3
import zlib

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from cloud_role_switcher import switch_cloud_active_role
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed

async def test():
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
    role_id = int(row['role_id'])
    server_id = int(row['kingdom_id'])

    switch_cloud_active_role(
        role_id=role_id,
        server_id=server_id,
        app_uid=row['app_uid'],
        app_token=row['app_token'],
        udid=row['udid']
    )

    from fleet_manager import resolve_login_bytes
    login_bytes = resolve_login_bytes({
        'role_id': role_id,
        'app_token': row['app_token'],
        'app_uid': row['app_uid'],
        'udid': row['udid'],
        'kingdom_id': server_id
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

    # Login sequence
    w.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 6404, 2: ProtobufCodec.encode_message({1: server_id})}))))
    await w.drain()
    await asyncio.sleep(0.3)

    # Send Opcode 5 (cmd_resource_info)
    print("Sending Opcode 5 ({1: 5, 2: {}})...")
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 5, 2: ProtobufCodec.encode_message({})}))))
    # Also send Opcode 1001
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b''}))))
    await w.drain()

    deadline = asyncio.get_event_loop().time() + 6.0
    while asyncio.get_event_loop().time() < deadline:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.5)
            rl = (rh[0] << 8) | rh[1]
            raw_pkt = await asyncio.wait_for(r.readexactly(rl), timeout=0.5)
            dec = c_rx.decrypt(raw_pkt)
            z_idx = dec.find(b"\x78\x9c")
            if z_idx == -1: z_idx = dec.find(b"\x78\x01")
            data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
            msg = ProtobufCodec.decode_message(data)
            chunks = msg.get(1) if isinstance(msg.get(1), list) else [msg]

            for c in chunks:
                m = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                if isinstance(m, dict):
                    op = m.get(1)
                    p = m.get(2)
                    p_dec = ProtobufCodec.decode_message(p) if isinstance(p, bytes) else p
                    # If op == 5 or op == 6 or related to resources
                    if op in (5, 6, 7, 8, 9, 10, 15, 1005, 1006, 1050):
                        print(f"\n[INTERESTING OP {op}] payload: {p_dec}")
                    # Check for large numbers (> 500,000)
                    def check_large(o, path=""):
                        if isinstance(o, dict):
                            for k, v in o.items(): check_large(v, f"{path}.{k}")
                        elif isinstance(o, list):
                            for idx, it in enumerate(o): check_large(it, f"{path}[{idx}]")
                        elif isinstance(o, bytes):
                            try: check_large(ProtobufCodec.decode_message(o), f"{path}(p)")
                            except: pass
                        elif isinstance(o, int) and o > 500_000:
                            print(f"   [FOUND LARGE RSS] op {op} {path} = {o:,}")
                    check_large(p_dec)
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            print("Err:", e)
            break

    w.close()
    print("Done test.")

if __name__ == "__main__":
    asyncio.run(test())
