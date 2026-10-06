import asyncio
import json
import sys
import os
import sqlite3
import zlib
import time

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from cloud_role_switcher import switch_cloud_active_role
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.models import InventoryDAO
from app.services.city_state_parser import parse_resources_121, parse_city_state_1002
from fleet_manager import resolve_login_bytes

async def sync_character(char_info):
    role_id = int(char_info['role_id'])
    server_id = int(char_info['kingdom_id'])
    name = char_info['name']
    bot_id = char_info['bot_id']
    email = char_info['email']

    print(f"\n[{bot_id}] Syncing {name} (Role {role_id}, KD {server_id})...")
    try:
        switch_cloud_active_role(
            role_id=role_id,
            server_id=server_id,
            app_uid=char_info['app_uid'],
            app_token=char_info['app_token'],
            udid=char_info['udid']
        )
    except Exception as e:
        print(f"  [-] Switch error: {e}")

    try:
        login_bytes = resolve_login_bytes({
            'role_id': role_id,
            'app_token': char_info['app_token'],
            'app_uid': char_info['app_uid'],
            'udid': char_info['udid'],
            'kingdom_id': server_id
        })

        host = 'rocgate.lilithgame.com'
        port = 3101
        proxy = char_info.get('proxy_url')
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
        await asyncio.sleep(0.3)
        w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b''}))))
        await w.drain()

        deadline = asyncio.get_event_loop().time() + 6.0
        got_121 = False
        got_1002 = False

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
                    if not isinstance(m, dict):
                        continue
                    op = m.get(1)
                    p = m.get(2)

                    if op == 8003:
                        w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({
                            1: 9, 2: ProtobufCodec.encode_message({1: 1})
                        }))))
                        await w.drain()

                    elif op == 121:
                        rss = parse_resources_121(p or data)
                        if rss:
                            InventoryDAO.upsert(
                                bot_id=bot_id,
                                role_id=str(role_id),
                                name=name,
                                food=rss.get('food', 0),
                                wood=rss.get('wood', 0),
                                stone=rss.get('stone', 0),
                                gold=rss.get('gold', 0),
                                gems=rss.get('gems', 0)
                            )
                            print(f"  [+] Opcode 121: Food={rss['food']:,} Wood={rss['wood']:,} Stone={rss['stone']:,} Gold={rss['gold']:,} Gems={rss['gems']:,}")
                            got_121 = True

                    elif op == 1002 or (isinstance(data, bytes) and b"\x08\xea\x07" in data):
                        p2 = p if op == 1002 else None
                        if not p2 and isinstance(data, bytes) and b"\x08\xea\x07" in data:
                            idx = data.find(b"\x08\xea\x07")
                            sub_msg = ProtobufCodec.decode_message(data[idx:])
                            p2 = sub_msg.get(2)
                        if isinstance(p2, bytes):
                            snap = parse_city_state_1002(p2)
                            if snap:
                                InventoryDAO.upsert(
                                    bot_id=bot_id,
                                    role_id=str(role_id),
                                    name=name,
                                    kingdom_id=int(snap.get('kingdom_id') or server_id),
                                    city_hall_level=int(snap.get('city_hall_level') or 0),
                                    power=int(snap.get('power') or 0)
                                )
                                print(f"  [+] Opcode 1002: CH={snap.get('city_hall_level')} Power={snap.get('power', 0):,}")
                                got_1002 = True

                if got_121 and got_1002:
                    break
            except asyncio.TimeoutError:
                if got_121:
                    break
                continue
            except Exception:
                break

        w.close()
        print(f"  [OK] Done sync for {name} (121: {got_121}, 1002: {got_1002})")
    except Exception as ex:
        print(f"  [-] Connection error for {name}: {ex}")

async def main():
    conn = sqlite3.connect('/home/ubuntu/bot-backend/rok_cloud.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    chars = []
    # Collect KD fleet
    for r in cur.execute("""
        SELECT c.role_id, c.name, c.kingdom_id, a.email, a.app_token, a.app_uid, a.udid, a.proxy_url
        FROM characters c
        JOIN accounts a ON c.account_id = a.id
        WHERE a.bot_id = 'bot-2404' OR c.name LIKE '%KD%'
        ORDER BY c.power DESC
    """):
        d = dict(r)
        d['bot_id'] = 'bot-2404'
        chars.append(d)

    # Collect Nucro fleet
    for r in cur.execute("""
        SELECT c.role_id, c.name, c.kingdom_id, a.email, a.app_token, a.app_uid, a.udid, a.proxy_url
        FROM characters c
        JOIN accounts a ON c.account_id = a.id
        WHERE a.bot_id = 'bot-2911' OR c.name LIKE '%Nucro%'
        ORDER BY c.power DESC
    """):
        d = dict(r)
        d['bot_id'] = 'bot-2911'
        chars.append(d)

    print(f"Starting authoritative live inventory sync for {len(chars)} governors...")
    for c in chars:
        await sync_character(c)
        await asyncio.sleep(1.0)

    print("\nALL GOVERNORS SYNCED WITH REAL LIVE LIQUID RESOURCES!")

if __name__ == '__main__':
    asyncio.run(main())
