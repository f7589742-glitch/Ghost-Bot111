import sys
import asyncio
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
from app.services.combat_engine import safe_decompress, unpack_frames, CombatEngine
from app.services.smart_gather_search import build_map_request
from cloud_role_switcher import switch_cloud_active_role

async def test_commander_dispatch(cmd_id: int, cmd_name: str, troop_count: int = 500):
    role_id = 222157544 # NUCROSHOP
    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f: fleet = json.load(f)
    acc = next(a for a in fleet if any(str(c.get('role_id')) == str(role_id) for c in a.get('characters', [])))

    switch_cloud_active_role(role_id=int(role_id), server_id=3057, app_uid=str(acc['app_uid']), app_token=str(acc['access_token']), udid=str(acc['device_udid']), app_id=2104267)
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

    city_pos = (4331.19, 4194.54)
    w.write(FrameParser.build_frame(c_tx.encrypt(build_map_request(city_pos))))
    await w.drain()

    barbs = []
    d = asyncio.get_event_loop().time() + 2.5
    while asyncio.get_event_loop().time() < d:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            raw = await asyncio.wait_for(r.readexactly((rh[0]<<8)|rh[1]), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                if it.get(1) == 1003:
                    found = CombatEngine.parse_all_barbarians_from_1003(it.get(2, b''), city_pos[0], city_pos[1])
                    for b in found:
                        if not any(x['entity_id'] == b['entity_id'] for x in barbs):
                            barbs.append(b)
        except Exception: break

    target_barbs = [b for b in barbs if b.get('level', 1) <= 8]
    if not target_barbs:
        print("No target barbs found!")
        w.close()
        return

    t = target_barbs[0]
    teid = t['entity_id']
    tpos = (t['x'], t['y'])
    tlvl = t.get('level')
    print(f"Testing dispatch for Commander #{cmd_id} ({cmd_name}) with {troop_count} troops against Barbarian #{teid} L{tlvl}...")

    # Viewport to target
    w.write(FrameParser.build_frame(c_tx.encrypt(build_map_request(tpos))))
    await w.drain()
    await asyncio.sleep(0.1)

    # Inspect (Opcode 1050)
    insp = CombatEngine.build_target_inspect_payload(teid, city_pos[0], city_pos[1], tpos[0], tpos[1], 8719112)
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1050, 2: insp}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('089d0712020800'))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('08a70312020800'))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('08fe4b1200'))))
    w.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex('08091200'))))
    await w.drain()

    # Wait for 1051
    got_1051 = False
    d = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < d:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            raw = await asyncio.wait_for(r.readexactly((rh[0]<<8)|rh[1]), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                if it.get(1) == 1051:
                    got_1051 = True
                    break
            if got_1051: break
        except Exception: break

    # Confirm 8
    w.write(FrameParser.build_frame(c_tx.encrypt(CombatEngine.build_send_troop_confirm())))
    await w.drain()
    await asyncio.sleep(0.05)

    # Dispatch Opcode 1012
    dispatch_pkt = ProtobufCodec.encode_message({
        1: 1012,
        2: CombatEngine.build_combat_dispatch_payload(
            target_entity_id=int(teid),
            primary_commander_id=int(cmd_id),
            secondary_commander_id=0,
            troops=[(1, troop_count)],
            march_index=1
        )
    })
    w.write(FrameParser.build_frame(c_tx.encrypt(dispatch_pkt)))
    await w.drain()

    # Check response
    dispatch_res = None
    d = asyncio.get_event_loop().time() + 3.0
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
                p2_dec = ProtobufCodec.decode_message(p2) if isinstance(p2, bytes) else p2
                if op in (1013, 1024, 903, 365, 1005, 1023):
                    dispatch_res = f"SUCCESS (Opcode {op})"
                    break
                if op == 1 and isinstance(p2_dec, dict) and p2_dec.get(1) == 1012:
                    dispatch_res = f"ERROR Code: {p2_dec.get(2)}"
                    break
            if dispatch_res: break
        except Exception: break

    print(f">>> Result for Commander #{cmd_id} ({cmd_name}): {dispatch_res}")
    w.close()
    await w.wait_closed()

async def main():
    # Test Lancelot (36), Constance (33), Lohar (6)
    print("--- TESTING LANCELOT (#36) ---")
    await test_commander_dispatch(36, "Lancelot", 500)
    await asyncio.sleep(1.0)
    print("--- TESTING CONSTANCE (#33) ---")
    await test_commander_dispatch(33, "Constance", 500)
    await asyncio.sleep(1.0)
    print("--- TESTING LOHAR (#6) with 500 troops ---")
    await test_commander_dispatch(6, "Lohar", 500)
    await asyncio.sleep(1.0)
    print("--- TESTING LOHAR (#6) with 5000 troops ---")
    await test_commander_dispatch(6, "Lohar", 5000)

if __name__ == '__main__':
    asyncio.run(main())
