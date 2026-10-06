import sys, os, asyncio, json, struct, zlib
sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.services.combat_engine import CombatEngine, safe_decompress, unpack_frames

async def test():
    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)
    acc = next(a for a in fleet if any(str(c.get('role_id')) == '222157544' for c in a.get('characters', [])))
    login_bytes = resolve_login_bytes({
        'role_id': 222157544,
        'app_token': acc['access_token'],
        'app_uid': acc['app_uid'],
        'udid': acc['device_udid'],
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
    
    city_x, city_y = 4331.4, 4194.6
    f1 = b'\x0d' + struct.pack('<f', city_x) + b'\x15' + struct.pack('<f', city_y)
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1004, 2: ProtobufCodec.encode_message({1: f1, 2: 0, 5: 1})}))))
    await w.drain()

    barbarians = []
    d_map = asyncio.get_event_loop().time() + 3.0
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

    print(f"Found {len(barbarians)} barbarians from 1003:", flush=True)
    for b in barbarians[:5]:
        print(f"  Barbarian #{b['entity_id']} at ({b['x']}, {b['y']}) Level {b['level']} dist={b.get('dist')}km", flush=True)

    if not barbarians:
        print("No barbarians found. Exiting.", flush=True)
        w.close()
        return

    target = barbarians[0]
    teid = target['entity_id']
    tx, ty = target['x'], target['y']

    # 1. Viewport to target
    f1_t = b'\x0d' + struct.pack('<f', tx) + b'\x15' + struct.pack('<f', ty)
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1004, 2: ProtobufCodec.encode_message({1: f1_t, 2: 0, 5: 1})}))))
    await w.drain()
    await asyncio.sleep(0.1)

    # 2. Inspect target (Opcode 1050)
    insp_payload = CombatEngine.build_target_inspect_payload(
        target_entity_id=teid,
        city_x=city_x,
        city_y=city_y,
        target_x=tx,
        target_y=ty,
        alliance_id=8719112
    )
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1050, 2: insp_payload}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex("089d0712020800"))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex("08a70312020800"))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex("08fe4b1200"))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex("08091200"))))
    await w.drain()

    # Wait for 1051
    insp_ok = False
    d_insp = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < d_insp:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            rl = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(r.readexactly(rl), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                if it.get(1) == 1051:
                    insp_ok = True
                    print(f"--> Target #{teid} inspected successfully (Opcode 1051 ACK)!", flush=True)
                    break
            if insp_ok: break
        except Exception: break

    # 3. SendTroopConfirm (Opcode 8)
    w.write(FrameParser.build_frame(c_tx.encrypt(CombatEngine.build_send_troop_confirm())))
    await w.drain()
    await asyncio.sleep(0.05)

    # 4. Now test dispatch variants
    # Let us try Hero 1 (City Keeper), Hero 3 (Sun Tzu), Hero 2 (Cao Cao), Hero 23 (Tomoe/Centurion)
    # With sec_commander = 0, f6=1, with and without f17
    variants = [
        ("Hero 1, sec=0, f6=1, no f17", 1, 0, 1, False),
        ("Hero 3, sec=0, f6=1, no f17", 3, 0, 1, False),
        ("Hero 1, sec=0, f6=1, with f17", 1, 0, 1, True),
        ("Hero 1, sec=0, f6=0, no f17", 1, 0, 0, False),
        ("Hero 23, sec=0, f6=1, no f17", 23, 0, 1, False),
    ]

    for label, cmd_id, sec_id, f6_val, use_f17 in variants:
        print(f"\nTesting variant: {label} against #{teid}...", flush=True)
        f4 = ProtobufCodec.encode_field_varint(4, int(teid))
        f3 = ProtobufCodec.encode_field_bytes(3, bytes.fromhex("15000000000d00000000"))
        it = ProtobufCodec.encode_field_varint(2, 500) + ProtobufCodec.encode_field_varint(1, 1)
        f2_payload = ProtobufCodec.encode_field_bytes(2, it)
        f14 = ProtobufCodec.encode_field_varint(14, 1)
        c1 = (
            ProtobufCodec.encode_field_varint(1, int(cmd_id))
            + ProtobufCodec.encode_field_varint(3, 0)
            + ProtobufCodec.encode_field_varint(2, 1)
        )
        f1_payload = ProtobufCodec.encode_field_bytes(1, c1)
        if sec_id:
            c2 = (
                ProtobufCodec.encode_field_varint(1, int(sec_id))
                + ProtobufCodec.encode_field_varint(3, 0)
                + ProtobufCodec.encode_field_varint(2, 2)
            )
            f1_payload += ProtobufCodec.encode_field_bytes(1, c2)
        f7 = ProtobufCodec.encode_field_varint(7, 0)
        f6 = ProtobufCodec.encode_field_varint(6, f6_val)
        f11 = ProtobufCodec.encode_field_varint(11, 0)
        f18 = ProtobufCodec.encode_field_varint(18, 0)
        f17 = ProtobufCodec.encode_field_varint(17, 1) if use_f17 else b""
        f5 = ProtobufCodec.encode_field_bytes(5, b"dispatch_troop_1")

        body = f4 + f3 + f2_payload + f14 + f1_payload + f7 + f6 + f11 + f18 + f17 + f5
        pkt_1012 = ProtobufCodec.encode_message({1: 1012, 2: body})
        w.write(FrameParser.build_frame(c_tx.encrypt(pkt_1012)))
        await w.drain()

        # Listen for ACK
        confirmed = False
        err_code = None
        d_ack = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < d_ack:
            try:
                rh = await asyncio.wait_for(r.readexactly(2), timeout=0.4)
                rl = (rh[0] << 8) | rh[1]
                raw = await asyncio.wait_for(r.readexactly(rl), timeout=0.4)
                dec = c_rx.decrypt(raw)
                decomp = safe_decompress(dec)
                m = ProtobufCodec.decode_message(decomp)
                for it in unpack_frames(m):
                    op = it.get(1)
                    p2 = it.get(2)
                    p2_dec = ProtobufCodec.decode_message(p2) if isinstance(p2, bytes) else p2
                    if op in (903, 365, 1013, 1005, 1024, 1023):
                        print(f"   [SUCCESS ACK] Opcode {op} -> {p2_dec}", flush=True)
                        confirmed = True
                        break
                    elif op == 1 and isinstance(p2_dec, dict) and p2_dec.get(1) == 1012:
                        err_code = p2_dec.get(2)
                        print(f"   [REJECT] Opcode 1 Error: code={err_code}", flush=True)
                        break
                if confirmed or err_code is not None: break
            except Exception: break

        if confirmed:
            print(f"🎉🎉🎉 VARIANT SUCCESS! {label} WORKED!", flush=True)
            break
        await asyncio.sleep(0.5)

    w.close()
    await w.wait_closed()

if __name__ == '__main__':
    asyncio.run(test())
