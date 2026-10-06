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
    all_packets = {}
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
                    all_packets[op] = p2
        except Exception: break
    w.close()
    await w.wait_closed()

    # Search each opcode for commanders: 15 (Joan), 34 (Gaius), 36 (Lancelot), 33 (Constance), 6 (Lohar), 32 (Cleopatra)
    check_ids = [15, 34, 36, 33, 6, 32, 38, 24, 1]
    for op, p2 in sorted(all_packets.items()):
        try:
            dec = ProtobufCodec.decode_message(p2)
            # check all fields
            for k, v in dec.items():
                if isinstance(v, list) and len(v) > 0:
                    found_hids = set()
                    for item in v:
                        if isinstance(item, bytes):
                            id_d = ProtobufCodec.decode_message(item)
                            for subk, subv in id_d.items():
                                if subv in check_ids:
                                    found_hids.add((subv, subk))
                    if len(found_hids) >= 3:
                        print(f"*** FOUND COMMANDERS IN OPCODE {op} FIELD {k}! (List len {len(v)}) ***")
                        print(f"   Matched IDs: {found_hids}")
                        # print first 5 items decoded
                        for idx, item in enumerate(v[:5]):
                            if isinstance(item, bytes):
                                print(f"   [{idx}]: {ProtobufCodec.decode_message(item)}")
        except Exception: pass

if __name__ == '__main__':
    asyncio.run(check())
