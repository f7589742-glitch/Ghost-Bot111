import asyncio
import sys
import json
import struct
import zlib

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.services.combat_engine import safe_decompress, unpack_frames

async def check():
    role_id = 222157544 # NUCROSHOP
    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)
    acc = next(a for a in fleet if any(str(c.get('role_id')) == str(role_id) for c in a.get('characters', [])))
    login_bytes = resolve_login_bytes({'role_id': role_id, 'app_token': acc['access_token'], 'app_uid': acc['app_uid'], 'udid': acc['device_udid'], 'kingdom_id': 3057})
    r, w = await open_game_connection('rocgate.lilithgame.com', 3101)
    hdr = await r.readexactly(2)
    gp = await r.readexactly((hdr[0] << 8) | hdr[1])
    sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(gp).get(2, b''))
    tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
    c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)

    w.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b''}))))
    await w.drain()

    d = asyncio.get_event_loop().time() + 4.0
    opcodes = {}
    while asyncio.get_event_loop().time() < d:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            raw = await asyncio.wait_for(r.readexactly((rh[0]<<8)|rh[1]), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                op = it.get(1)
                p2 = it.get(2)
                if isinstance(p2, bytes):
                    opcodes[op] = p2
        except Exception: break
    w.close()
    await w.wait_closed()

    print(f"Collected {len(opcodes)} distinct opcodes.")
    target_ids = {15, 34, 36, 33, 6, 32, 24, 8, 1, 38, 4, 2, 3}
    for op, raw in sorted(opcodes.items()):
        try:
            d = ProtobufCodec.decode_message(raw)
            # Find any integer values that match target_ids
            found = set()
            def find_ints(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if isinstance(v, int) and v in target_ids:
                            found.add(v)
                        elif isinstance(v, bytes) and len(v) > 0:
                            try: find_ints(ProtobufCodec.decode_message(v))
                            except: pass
                        elif isinstance(v, list):
                            for x in v: find_ints(x)
                elif isinstance(o, list):
                    for x in o: find_ints(x)
            find_ints(d)
            if len(found) >= 3:
                print(f"--> Opcode {op} (len {len(raw)}) matched {len(found)} commander IDs: {sorted(list(found))}")
                # print summary of fields in d
                print(f"    Keys: {list(d.keys())}")
        except Exception as e:
            pass

if __name__ == '__main__':
    asyncio.run(check())
