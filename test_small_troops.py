import sys, asyncio, json, struct, zlib
sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.services.combat_engine import CombatEngine, safe_decompress, unpack_frames

async def test_small_troops():
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
                op = it.get(1)
                if op == 1003:
                    found = CombatEngine.parse_all_barbarians_from_1003(it.get(2, b''), city_x, city_y)
                    barbarians.extend(found)
        except Exception:
            break

    print(f'Found {len(barbarians)} barbarians')
    if not barbarians:
        w.close()
        return

    # Pick the closest barbarian
    barbarians.sort(key=lambda b: (b['x'] - city_x)**2 + (b['y'] - city_y)**2)
    target = barbarians[0]
    teid = target['entity_id']
    tx, ty = target['x'], target['y']
    print(f"Closest Barbarian #{teid} at ({tx}, {ty}) Level {target.get('level')}")

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

    # Wait for 1051
    d_i = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < d_i:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            rl = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(r.readexactly(rl), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                if it.get(1) == 1051:
                    print('Inspect 1051 OK!')
                    break
        except Exception: break

    # Confirm 8
    w.write(FrameParser.build_frame(c_tx.encrypt(CombatEngine.build_send_troop_confirm())))
    await w.drain()
    await asyncio.sleep(0.05)

    # Test commanders with 2000 troops of unit_type 1 (Infantry)
    for cmd_id in [15, 38, 1, 3, 24]:
        print(f"\nTesting Hero #{cmd_id} with 2000 T1 Infantry...")
        f4 = ProtobufCodec.encode_field_varint(4, int(teid))
        f3 = ProtobufCodec.encode_field_bytes(3, bytes.fromhex('15000000000d00000000'))
        it = ProtobufCodec.encode_field_varint(2, 2000) + ProtobufCodec.encode_field_varint(1, 1)
        f2_payload = ProtobufCodec.encode_field_bytes(2, it)
        f14 = ProtobufCodec.encode_field_varint(14, 1)
        c1 = (
            ProtobufCodec.encode_field_varint(1, int(cmd_id))
            + ProtobufCodec.encode_field_varint(3, 0)
            + ProtobufCodec.encode_field_varint(2, 1)
        )
        f1_payload = ProtobufCodec.encode_field_bytes(1, c1)
        f7 = ProtobufCodec.encode_field_varint(7, 0)
        f6 = ProtobufCodec.encode_field_varint(6, 1)
        f11 = ProtobufCodec.encode_field_varint(11, 0)
        f18 = ProtobufCodec.encode_field_varint(18, 0)
        f5 = ProtobufCodec.encode_field_bytes(5, b'dispatch_troop_1')
        body = f4 + f3 + f2_payload + f14 + f1_payload + f7 + f6 + f11 + f18 + f5

        w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1012, 2: body}))))
        await w.drain()

        ack_ok = False
        err_code = None
        d_a = asyncio.get_event_loop().time() + 2.5
        while asyncio.get_event_loop().time() < d_a:
            try:
                rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
                rl = (rh[0] << 8) | rh[1]
                raw = await asyncio.wait_for(r.readexactly(rl), timeout=0.3)
                dec = c_rx.decrypt(raw)
                decomp = safe_decompress(dec)
                m = ProtobufCodec.decode_message(decomp)
                for it_m in unpack_frames(m):
                    op = it_m.get(1)
                    p2 = it_m.get(2)
                    p2_dec = ProtobufCodec.decode_message(p2) if isinstance(p2, bytes) else p2
                    if op in (1013, 1024, 903, 365, 1005, 1023):
                        ack_ok = True
                        print(f'   [SUCCESS ACK] Opcode {op} -> {p2_dec}')
                        break
                    elif op == 1 and isinstance(p2_dec, dict) and p2_dec.get(1) == 1012:
                        err_code = p2_dec.get(2)
                        print(f'   [REJECT] Opcode 1 Error code: {err_code}')
                        break
                if ack_ok or err_code is not None: break
            except Exception: break

        if ack_ok:
            print(f'🎉🎉🎉 HERO #{cmd_id} SUCCESS ON NUCROSHOP6!')
            break
        await asyncio.sleep(0.5)

    w.close()
    await w.wait_closed()

asyncio.run(test_small_troops())
