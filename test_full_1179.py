import sys, os, asyncio, json, struct, zlib
sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from app.services.combat_engine import CombatEngine, OP_SEARCH_BARBARIAN, OP_BARBARIAN_SEARCH_RESP, safe_decompress, unpack_frames
from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed

async def main():
    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)
    
    target_acc = None
    for acc in fleet:
        for c in acc.get('characters', []):
            if str(c.get('role_id')) == '222157544':
                target_acc = acc
                break
        if target_acc: break

    login_bytes = resolve_login_bytes({
        'role_id': 222157544,
        'app_token': target_acc['access_token'],
        'app_uid': target_acc['app_uid'],
        'udid': target_acc['device_udid'],
        'kingdom_id': 3057,
    })

    reader, writer = await open_game_connection('rocgate.lilithgame.com', 3101)
    hdr = await reader.readexactly(2)
    g_p = await reader.readexactly((hdr[0] << 8) | hdr[1])
    sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(g_p).get(2, b''))
    tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
    c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)

    writer.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))
    writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b''}))))
    writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b''}))))
    # Send 1001 to sync state
    writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b''}))))
    # Send 1004 map request for city
    def encode_point(x, y):
        return b'\x0d' + struct.pack('<f', float(x)) + b'\x15' + struct.pack('<f', float(y))
    f1 = encode_point(4331.4, 4194.6)
    payload = ProtobufCodec.encode_message({1: f1, 2: 0, 5: 1})
    writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1004, 2: payload}))))
    await writer.drain()

    # Read state
    d_init = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < d_init:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
            rl = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
        except Exception:
            break

    print('State synced. Sending 1178 (Level 6)...', flush=True)
    search_pkt = ProtobufCodec.encode_message({
        1: OP_SEARCH_BARBARIAN,
        2: CombatEngine.build_search_barbarian_payload(6)
    })
    writer.write(FrameParser.build_frame(c_tx.encrypt(search_pkt)))
    await writer.drain()

    d_end = asyncio.get_event_loop().time() + 4.0
    while asyncio.get_event_loop().time() < d_end:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
            rl = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                op = it.get(1)
                p2 = it.get(2)
                p2_dec = ProtobufCodec.decode_message(p2) if isinstance(p2, bytes) else p2
                print(f'Server opcode: {op} -> {p2_dec}', flush=True)
        except Exception:
            break

    writer.close()
    await writer.wait_closed()

if __name__ == '__main__':
    asyncio.run(main())
