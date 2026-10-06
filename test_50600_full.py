@"
import sys, os
PROJECT_ROOT = '/home/ubuntu/bot-backend'
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'python'))

import asyncio, zlib, struct
from app.models import CharacterDAO, AccountDAO
from app.services.combat_engine import CombatEngine
from app.services.lilith_cloud import LilithCloudService
from cloud_role_switcher import ensure_character_active
from fleet_manager import resolve_login_bytes
from python.headless_client import ProtobufCodec, FrameParser
from python.crypto_module import RokCrypto
from python.derive_seed_from_nonce import derive_seed

async def test_full_cycle():
    char = CharacterDAO.get_by_role_id('222157544')
    acc = AccountDAO.get_by_id(char['account_id'])
    target_char = {
        'role_id': int(char['role_id']),
        'kingdom_id': int(char['kingdom_id'] or 3057),
        'app_uid': str(acc['app_uid']),
        'app_token': str(acc['app_token']),
        'udid': str(acc['udid']),
        'name': char['name']
    }
    ensure_character_active(target_char)
    login_bytes = resolve_login_bytes(target_char)

    r, w = await asyncio.open_connection('rocgate.lilithgame.com', 3101)
    hdr = await r.readexactly(2)
    gp = await r.readexactly((hdr[0]<<8)|hdr[1])
    sg = ProtobufCodec.decode_message(ProtobufCodec.decode_message(gp).get(2, b''))
    tx, rx = derive_seed(sg.get(1,0), sg.get(2,0))
    c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)

    w.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))
    p203 = ProtobufCodec.encode_message({1: int(char['role_id'])})
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: p203}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b''}))))
    p110 = ProtobufCodec.encode_message({1: int(char['role_id']), 2: int(char['kingdom_id'] or 3057), 3: int(char['role_id'])})
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: p110}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b''}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 6404, 2: ProtobufCodec.encode_message({1: int(char['kingdom_id'] or 3057)})}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b''}))))
    await w.drain()

    # Read state
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            raw = await asyncio.wait_for(r.readexactly((rh[0]<<8)|rh[1]), timeout=0.3)
            dec = c_rx.decrypt(raw)
        except Exception: pass

    # 1. Spawn Barbarian via Opcode 1178 (Level 10)
    print('1. Sending Opcode 1178 spawn request (Level 10)...')
    p1178 = bytes([0x18, 0x01, 0x10, 10, 0x08, 0x01, 0x20, 0x01])
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1178, 2: p1178}))))
    await w.drain()

    target_barb = None
    deadline = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            raw = await asyncio.wait_for(r.readexactly((rh[0]<<8)|rh[1]), timeout=0.3)
            dec = c_rx.decrypt(raw)
            zi = dec.find(b'\x78\x9c')
            if zi == -1: zi = dec.find(b'\x78\x01')
            decomp = zlib.decompress(dec[zi:]) if zi != -1 else dec
            m = ProtobufCodec.decode_message(decomp)
            chunks = m.get(1) if isinstance(m.get(1), list) else [m]
            for c in chunks:
                it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                if isinstance(it, dict) and it.get(1) == 1179:
                    p2 = it.get(2)
                    if isinstance(p2, bytes):
                        dp2 = ProtobufCodec.decode_message(p2)
                        f1 = dp2.get(1)
                        if isinstance(f1, bytes):
                            df1 = ProtobufCodec.decode_message(f1)
                            eid = df1.get(2)
                            sub_pos = df1.get(1)
                            if isinstance(sub_pos, bytes) and len(sub_pos) >= 10:
                                # In sub_pos: \r x_flt \x15 y_flt
                                bx = struct.unpack('<f', sub_pos[1:5])[0]
                                by = struct.unpack('<f', sub_pos[6:10])[0]
                                lvl = dp2.get(3, 10)
                                target_barb = {'eid': eid, 'x': bx, 'y': by, 'lvl': lvl}
                                print(f'SPAWNED BARBARIAN: EID={eid}, pos=({bx:.2f}, {by:.2f}), lvl={lvl}')
                                break
            if target_barb:
                break
        except Exception: pass

    if not target_barb:
        print('Failed to spawn barbarian via 1179, will check viewport...')
        return

    # 2. Inspect Target via Opcode 1050
    teid = target_barb['eid']
    tx_pos = target_barb['x']
    ty_pos = target_barb['y']
    city_x, city_y = 4331.4, 4194.6

    print(f'2. Inspecting Barbarian #{teid} at ({tx_pos:.2f}, {ty_pos:.2f})...')
    insp_payload = CombatEngine.build_target_inspect_payload(
        target_entity_id=int(teid),
        city_x=city_x,
        city_y=city_y,
        target_x=tx_pos,
        target_y=ty_pos,
        alliance_id=8719112
    )
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1050, 2: insp_payload}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('089d0712020800'))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('08a70312020800'))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('08fe4b1200'))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('08091200'))))
    await w.drain()

    # Wait for 1051
    got_1051 = False
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            raw = await asyncio.wait_for(r.readexactly((rh[0]<<8)|rh[1]), timeout=0.3)
            dec = c_rx.decrypt(raw)
            zi = dec.find(b'\x78\x9c')
            if zi == -1: zi = dec.find(b'\x78\x01')
            decomp = zlib.decompress(dec[zi:]) if zi != -1 else dec
            m = ProtobufCodec.decode_message(decomp)
            chunks = m.get(1) if isinstance(m.get(1), list) else [m]
            for c in chunks:
                it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                if isinstance(it, dict):
                    op = it.get(1)
                    if op == 1051:
                        got_1051 = True
                        print('3. GOT OPCODE 1051 CONFIRMATION FOR INSPECT!')
                    elif op == 1:
                        print('1050 REJECT/ERROR:', it.get(2))
            if got_1051: break
        except Exception: pass

    # 4. Send SendTroopConfirm (8) and Opcode 1012 (Single Encoded!)
    print('4. Sending SendTroopConfirm (Opcode 8)...')
    w.write(FrameParser.build_frame(c_tx.encrypt(CombatEngine.build_send_troop_confirm())))
    await w.drain()
    await asyncio.sleep(0.05)

    # Let us try Hero #1 (City Keeper) or #3 (Sun Tzu) or other heroes
    for hero_id in [1, 3, 2, 23, 38]:
        print(f'5. Attempting Opcode 1012 March Dispatch with Hero #{hero_id}...')
        # Note: build_combat_dispatch_payload returns {1: 1012, 2: body}
        # We send it directly WITHOUT wrapping in another 1012!
        dispatch_pkt = CombatEngine.build_combat_dispatch_payload(
            target_entity_id=int(teid),
            primary_commander_id=hero_id,
            secondary_commander_id=0,
            troops=[(1, 1000)], # 1000 infantry
            march_index=1
        )
        w.write(FrameParser.build_frame(c_tx.encrypt(dispatch_pkt)))
        await w.drain()

        # Listen for ACK
        confirmed = False
        error_code = None
        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                rh = await asyncio.wait_for(r.readexactly(2), timeout=0.4)
                raw = await asyncio.wait_for(r.readexactly((rh[0]<<8)|rh[1]), timeout=0.4)
                dec = c_rx.decrypt(raw)
                zi = dec.find(b'\x78\x9c')
                if zi == -1: zi = dec.find(b'\x78\x01')
                decomp = zlib.decompress(dec[zi:]) if zi != -1 else dec
                m = ProtobufCodec.decode_message(decomp)
                chunks = m.get(1) if isinstance(m.get(1), list) else [m]
                for c in chunks:
                    it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                    if isinstance(it, dict):
                        op = it.get(1)
                        p2 = it.get(2)
                        p2_dec = ProtobufCodec.decode_message(p2) if isinstance(p2, bytes) else p2
                        print(f'   [ACK] Opcode {op} -> {p2_dec}')
                        if op in (903, 365, 1013, 1005, 1024, 1023):
                            confirmed = True
                            break
                        if op == 1 and isinstance(p2_dec, dict) and p2_dec.get(1) == 1012:
                            code = p2_dec.get(2, -1)
                            if code in (0, 1):
                                confirmed = True
                                break
                            else:
                                error_code = code
                                break
                if confirmed or error_code is not None:
                    break
            except Exception: pass

        if confirmed:
            print(f'🎉🎉 SUCCESS! Combat march confirmed on wire with Hero #{hero_id}!')
            break
        else:
            print(f'Hero #{hero_id} failed (Error code: {error_code}). Trying next hero...')

    w.close()

asyncio.run(test_full_cycle())
"@ | & ssh.exe -i C:\Users\MaleK\Downloads\rok-bot-server1.pem -o StrictHostKeyChecking=no ubuntu@16.171.9.216 "/home/ubuntu/bot-backend/venv/bin/python3"