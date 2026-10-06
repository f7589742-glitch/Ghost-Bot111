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

async def test_op121():
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

    # Login
    w.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 6404, 2: ProtobufCodec.encode_message({1: server_id})}))))
    await w.drain()

    deadline = asyncio.get_event_loop().time() + 8.0
    got_121 = False

    while asyncio.get_event_loop().time() < deadline:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.6)
            rl = (rh[0] << 8) | rh[1]
            raw_pkt = await asyncio.wait_for(r.readexactly(rl), timeout=0.6)
            dec = c_rx.decrypt(raw_pkt)
            
            # Check for Opcode 8003 -> reply with Opcode 9
            # Also check decompressed frames
            z_idx = dec.find(b"\x78\x9c")
            if z_idx == -1: z_idx = dec.find(b"\x78\x01")
            data = zlib.decompress(dec[z_idx:]) if z_idx != -1 else dec
            msg = ProtobufCodec.decode_message(data)
            
            chunks = msg.get(1) if isinstance(msg.get(1), list) else [msg]
            for c in chunks:
                m = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                if not isinstance(m, dict):
                    continue
                op = m.get(1)
                p = m.get(2)

                if op == 8003:
                    print("[REPLY] Sending Opcode 9 ACK for 8003...")
                    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({
                        1: 9, 2: ProtobufCodec.encode_message({1: 1})
                    }))))
                    await w.drain()

                elif op == 121:
                    print("\n[!!! SUCCESS !!!] RECEIVED OPCODE 121:")
                    items = []
                    if isinstance(p, bytes):
                        sub121 = ProtobufCodec.decode_message(p)
                        items = sub121.get(1, [])
                    elif isinstance(m.get(1), list):
                        items = m.get(1)
                    elif isinstance(p, dict):
                        items = p.get(1, [])

                    res_names = {1: "Food", 2: "Wood", 3: "Stone", 4: "Gold", 5: "Gems"}
                    rss_result = {}
                    for item in items:
                        if isinstance(item, bytes):
                            it_d = ProtobufCodec.decode_message(item)
                        elif isinstance(item, dict):
                            it_d = item
                        else:
                            continue
                        rtype = it_d.get(1)
                        ramt = it_d.get(2, 0)
                        rname = res_names.get(rtype, f"type_{rtype}")
                        rss_result[rname] = ramt
                        print(f"   --> {rname}: {ramt:,}")
                    got_121 = True
                    break

            if got_121:
                break
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            print("Loop err:", e)
            break

    w.close()
    print("Test finished. got_121 =", got_121)

if __name__ == "__main__":
    asyncio.run(test_op121())
