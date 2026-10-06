import sys, asyncio, json, struct, zlib
sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.services.combat_engine import CombatEngine, safe_decompress, unpack_frames

async def check_1050():
    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)
    for acc in fleet:
        for c in acc.get('characters', []):
            if str(c.get('role_id')) == '222167622':
                target_acc = acc
                break

    login_bytes = resolve_login_bytes({
        'role_id': 222167622,
        'app_token': target_acc['access_token'],
        'app_uid': target_acc['app_uid'],
        'udid': target_acc['device_udid'],
        'kingdom_id': 3057
    })
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

    city_x, city_y = 4378.21, 4172.01
    f1 = b'\x0d' + struct.pack('<f', city_x) + b'\x15' + struct.pack('<f', city_y)
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1004, 2: ProtobufCodec.encode_message({1: f1, 2: 0, 5: 1})}))))
    await w.drain()

    barbarians = []
    d_map = asyncio.get_event_loop().time() + 2.5
    while asyncio.get_event_loop().time() < d_map:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            rl = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(r.readexactly(rl), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                if it.get(1) == 1003:
                    found = CombatEngine.parse_all_barbarians_from_1003(it.get(2, b''), city_x, city_y)
                    barbarians.extend(found)
        except Exception:
            break

    target = barbarians[0]
    teid = target['entity_id']
    tx, ty = target['x'], target['y']
    print(f"Inspecting Barbarian #{teid} at ({tx}, {ty})")

    # Viewport to target
    f1_t = b'\x0d' + struct.pack('<f', tx) + b'\x15' + struct.pack('<f', ty)
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1004, 2: ProtobufCodec.encode_message({1: f1_t, 2: 0, 5: 1})}))))
    await w.drain()
    await asyncio.sleep(0.1)

    # Inspect (Opcode 1050)
    insp_payload = CombatEngine.build_target_inspect_payload(teid, city_x, city_y, tx, ty, 8719112)
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1050, 2: insp_payload}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('089d0712020800'))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('08a70312020800'))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('08fe4b1200'))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('08091200'))))
    await w.drain()

    # Wait and print all opcodes!
    d_i = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < d_i:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            rl = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(r.readexactly(rl), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                op = it.get(1)
                p2 = it.get(2)
                p2_dec = ProtobufCodec.decode_message(p2) if isinstance(p2, bytes) else p2
                print(f"1050 RESP: Opcode {op} -> {p2_dec}")
        except Exception: break

    w.close()
    await w.wait_closed()

asyncio.run(check_1050())
