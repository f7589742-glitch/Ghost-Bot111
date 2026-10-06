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

    d = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < d:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            raw = await asyncio.wait_for(r.readexactly((rh[0]<<8)|rh[1]), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                if it.get(1) == 1002 and isinstance(it.get(2), bytes):
                    sub = ProtobufCodec.decode_message(it.get(2))
                    f1 = sub.get(1)
                    if isinstance(f1, bytes):
                        sub_f1 = ProtobufCodec.decode_message(f1)
                        print("=== DUMPING sub_f1 Tag 9 ===")
                        t9 = sub_f1.get(9)
                        if isinstance(t9, bytes):
                            d9 = ProtobufCodec.decode_message(t9)
                            print("Tag 9 keys:", list(d9.keys()))
                            for k9, v9 in d9.items():
                                if isinstance(v9, list):
                                    print(f"  Tag 9 subfield {k9}: List of {len(v9)} items")
                                    for idx, el in enumerate(v9):
                                        if isinstance(el, bytes):
                                            print(f"    [{idx}]: {ProtobufCodec.decode_message(el)}")
                                        else:
                                            print(f"    [{idx}]: {el}")
                                elif isinstance(v9, bytes):
                                    print(f"  Tag 9 subfield {k9}: bytes len {len(v9)}")
                                    try:
                                        print(f"    decoded: {ProtobufCodec.decode_message(v9)}")
                                    except: pass
                                else:
                                    print(f"  Tag 9 subfield {k9}: {v9}")

                        print("=== DUMPING sub_f1 Tag 12 ===")
                        t12 = sub_f1.get(12)
                        if isinstance(t12, bytes):
                            d12 = ProtobufCodec.decode_message(t12)
                            print("Tag 12 keys:", list(d12.keys()))
                            for k12, v12 in d12.items():
                                if isinstance(v12, list):
                                    print(f"  Tag 12 subfield {k12}: List of {len(v12)} items")
                                    for idx, el in enumerate(v12):
                                        if isinstance(el, bytes):
                                            print(f"    [{idx}]: {ProtobufCodec.decode_message(el)}")
                                        else:
                                            print(f"    [{idx}]: {el}")
                                elif isinstance(v12, bytes):
                                    print(f"  Tag 12 subfield {k12}: bytes len {len(v12)}")
                                    try:
                                        print(f"    decoded: {ProtobufCodec.decode_message(v12)}")
                                    except: pass
                                else:
                                    print(f"  Tag 12 subfield {k12}: {v12}")
                    w.close()
                    return
        except Exception: break
    w.close()

if __name__ == '__main__':
    asyncio.run(check())
