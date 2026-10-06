import asyncio
import sys
import json
import struct
import zlib
import re

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
    all_chunks = []
    while asyncio.get_event_loop().time() < d:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            raw = await asyncio.wait_for(r.readexactly((rh[0]<<8)|rh[1]), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                all_chunks.append(it)
        except Exception:
            break
    w.close()
    await w.wait_closed()

    print(f"Total packets collected: {len(all_chunks)}")

    # Let's search every packet for Hero 36 (Lancelot) with Level 30
    # In protobuf, Hero 36 with Level 30 could be:
    # Field 1: 36 (0x08, 0x24), Field 2: 30 (0x10, 0x1e) or (0x18, 0x1e)
    # Let's search raw bytes in every packet
    pattern_lancelot = b'\x08\x24\x10\x1e' # {1: 36, 2: 30}
    pattern_constance = b'\x08\x21\x10\x1e' # {1: 33, 2: 30}

    found_opcodes = []
    for it in all_chunks:
        op = it.get(1)
        p2 = it.get(2)
        if isinstance(p2, bytes):
            if pattern_lancelot in p2 or pattern_constance in p2 or (b'\x24' in p2 and b'\x1e' in p2 and b'\x21' in p2):
                found_opcodes.append((op, len(p2)))
                print(f"Found commander byte pattern in Opcode {op} (len {len(p2)})")

    # If not found with strict pattern, let's search for list of heroes in Opcode 1002
    for it in all_chunks:
        op = it.get(1)
        if op == 1002:
            p2 = it.get(2)
            if isinstance(p2, bytes):
                sub = ProtobufCodec.decode_message(p2)
                print("Opcode 1002 keys:", list(sub.keys()))
                f1 = sub.get(1)
                if isinstance(f1, bytes):
                    sub_f1 = ProtobufCodec.decode_message(f1)
                    print("Opcode 1002 sub_f1 keys:", list(sub_f1.keys()))
                    for k in sub_f1:
                        val = sub_f1[k]
                        if isinstance(val, bytes):
                            # check if it contains hero IDs 36, 33, 38, 15, 34
                            matches = [hid for hid in [15, 34, 36, 33, 38, 6, 4, 2, 3, 24, 1] if bytes([hid]) in val]
                            if len(matches) >= 3:
                                print(f"  sub_f1 Tag {k} (len {len(val)}) contains hero IDs: {matches}")
                        elif isinstance(val, list):
                            print(f"  sub_f1 Tag {k} is list of len {len(val)}")

if __name__ == '__main__':
    asyncio.run(check())
