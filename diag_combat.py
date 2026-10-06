import sys, os, asyncio, json, struct, zlib, math
sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from cloud_role_switcher import switch_cloud_active_role
from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.services.combat_engine import CombatEngine

def safe_decompress(b: bytes) -> bytes:
    idx = b.find(b"\x78\x9c")
    if idx == -1: idx = b.find(b"\x78\x01")
    if idx != -1:
        try:
            return zlib.decompress(b[idx:])
        except Exception:
            pass
    return b

def unpack_frames(m: dict):
    if not isinstance(m, dict): return []
    chunks = m.get(1, [])
    if not isinstance(chunks, list): chunks = [chunks]
    res = []
    for c in chunks:
        it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
        if isinstance(it, dict): res.append(it)
    return res

async def main():
    print("=== STARTING DIAGNOSTIC COMBAT ON NUCROSHOP ===", flush=True)
    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)
    
    target_acc = None
    for acc in fleet:
        for c in acc.get('characters', []):
            if str(c.get('role_id')) == '222157544':
                target_acc = acc
                break
        if target_acc: break

    sw = switch_cloud_active_role(
        role_id=222157544,
        server_id=3057,
        app_uid=str(target_acc['app_uid']),
        app_token=str(target_acc['access_token']),
        udid=str(target_acc['device_udid']),
        app_id=2104267
    )
    print("Switch role result:", sw, flush=True)

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
    writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 6404, 2: ProtobufCodec.encode_message({1: 3057})}))))
    await writer.drain()
    await asyncio.sleep(0.3)
    writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b''}))))
    await writer.drain()

    city_coords = None
    unlocked_heroes = []
    troops = {}

    d_init = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < d_init:
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
                if op == 1002 and isinstance(p2, bytes):
                    sub = ProtobufCodec.decode_message(p2)
                    for tag in (12, 9):
                        v = sub.get(tag)
                        if isinstance(v, bytes):
                            sv = ProtobufCodec.decode_message(v)
                            hl = sv.get(5) or sv.get(4) or []
                            if not isinstance(hl, list): hl = [hl]
                            for hb in hl:
                                if isinstance(hb, bytes):
                                    hid = ProtobufCodec.decode_message(hb).get(1)
                                    if hid and hid not in unlocked_heroes:
                                        unlocked_heroes.append(hid)
                    tag19 = sub.get(19)
                    if isinstance(tag19, bytes):
                        inn = ProtobufCodec.decode_message(tag19)
                        for item in inn.get(1, []):
                            if isinstance(item, bytes):
                                it2 = ProtobufCodec.decode_message(item)
                                ut = it2.get(1)
                                cnt = it2.get(3) or it2.get(2) or 0
                                if ut and cnt: troops[ut] = cnt
                    f1 = sub.get(1)
                    if isinstance(f1, bytes):
                        sub_f1 = ProtobufCodec.decode_message(f1)
                        cb = sub_f1.get(3)
                        if isinstance(cb, bytes) and len(cb) >= 10:
                            v1 = struct.unpack("<f", cb[1:5])[0]
                            v2 = struct.unpack("<f", cb[6:10])[0]
                            if cb[0] == 0x0d:
                                city_coords = (round(v1, 2), round(v2, 2))
                            else:
                                city_coords = (round(v2, 2), round(v1, 2))
                elif op == 125 and isinstance(p2, bytes):
                    p = ProtobufCodec.decode_message(p2)
                    for item in p.get(1, []):
                        if isinstance(item, bytes):
                            sub2 = ProtobufCodec.decode_message(ProtobufCodec.decode_message(item).get(2, b''))
                            ut = sub2.get(1, 0)
                            cnt = sub2.get(2, 0)
                            if ut and cnt: troops[ut] = cnt
        except Exception:
            break

    print(f"Handshake complete. City Coords: {city_coords}, Unlocked heroes: {unlocked_heroes}, Troops: {troops}", flush=True)

    if not city_coords:
        city_coords = (4331.4, 4194.6)

    # 1. Search Barbarian Level 10 down to 1
    target_barb = None
    for lvl in [10, 8, 6, 5, 4, 3, 2, 1]:
        print(f"Sending Opcode 1178 Search Barbarian L{lvl}...", flush=True)
        p1178 = bytes([0x18, 0x01, 0x10, lvl, 0x08, 0x01, 0x20, 0x01])
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1178, 2: p1178}))))
        await writer.drain()

        d_search = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < d_search:
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
                    if op == 1179 and isinstance(p2, bytes):
                        resps = CombatEngine.parse_all_barbarian_search_resps(p2)
                        if resps:
                            target_barb = resps[0]
                            print(f"*** FOUND TARGET VIA 1179 for L{lvl}: {target_barb} ***", flush=True)
                            break
                    elif op == 1:
                        p2_dec = ProtobufCodec.decode_message(p2) if isinstance(p2, bytes) else p2
                        print(f"Opcode 1 Reject: {p2_dec}", flush=True)
                if target_barb: break
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
        if target_barb: break
        await asyncio.sleep(0.3)

    if not target_barb:
        print("Failed to get target barb from server! Exiting.", flush=True)
        writer.close()
        return

    # 2. Viewport to Target
    print(f"Moving viewport to Barbarian #{target_barb['entity_id']} at ({target_barb['x']}, {target_barb['y']})...", flush=True)
    f1_vp = b'\x0d' + struct.pack('<f', float(target_barb['x'])) + b'\x15' + struct.pack('<f', float(target_barb['y']))
    vp_pkt = ProtobufCodec.encode_message({1: 1004, 2: ProtobufCodec.encode_message({1: f1_vp, 2: 0, 5: 1})})
    writer.write(FrameParser.build_frame(c_tx.encrypt(vp_pkt)))
    await writer.drain()
    await asyncio.sleep(0.1)

    # 3. Inspect Opcode 1050
    print("Sending Opcode 1050 Inspect...", flush=True)
    insp_body = CombatEngine.build_target_inspect_payload(
        target_entity_id=int(target_barb['entity_id']),
        city_x=city_coords[0],
        city_y=city_coords[1],
        target_x=target_barb['x'],
        target_y=target_barb['y'],
        alliance_id=8719112
    )
    writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1050, 2: insp_body}))))
    writer.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex("089d0712020800"))))
    writer.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex("08a70312020800"))))
    writer.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex("08fe4b1200"))))
    writer.write(FrameParser.build_frame(c_tx.encrypt(bytes.fromhex("08091200"))))
    await writer.drain()

    insp_ok = False
    d_insp = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < d_insp:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.3)
            rl = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.3)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                op = it.get(1)
                if op == 1051:
                    insp_ok = True
                    print("--> Opcode 1051 Inspect ACK Received!", flush=True)
                    break
                elif op == 1:
                    print(f"--> Opcode 1 Error during inspect: {it.get(2)}", flush=True)
            if insp_ok: break
        except Exception: pass

    # 4. SendTroopConfirm (Opcode 8)
    print("Sending SendTroopConfirm (Opcode 8)...", flush=True)
    writer.write(FrameParser.build_frame(c_tx.encrypt(CombatEngine.build_send_troop_confirm())))
    await writer.drain()
    await asyncio.sleep(0.05)

    # 5. Dispatch March Opcode 1012
    hero_to_use = unlocked_heroes[0] if unlocked_heroes else 1
    print(f"Testing Opcode 1012 Dispatch against #{target_barb['entity_id']} with Commander #{hero_to_use}...", flush=True)

    # Test with 500 T1 Infantry
    avail_troop_type = next(iter(troops.keys())) if troops else 1
    march_troops = [(avail_troop_type, 500)]

    dispatch_body = CombatEngine.build_combat_dispatch_payload(
        target_entity_id=int(target_barb['entity_id']),
        primary_commander_id=hero_to_use,
        secondary_commander_id=0,
        troops=march_troops,
        march_index=1
    )
    pkt_1012 = ProtobufCodec.encode_message({1: 1012, 2: dispatch_body})
    writer.write(FrameParser.build_frame(c_tx.encrypt(pkt_1012)))
    await writer.drain()

    # Listen for 1012 ACK
    d_ack = asyncio.get_event_loop().time() + 4.0
    while asyncio.get_event_loop().time() < d_ack:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.4)
            rl = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(reader.readexactly(rl), timeout=0.4)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                op = it.get(1)
                p2 = it.get(2)
                p2_dec = ProtobufCodec.decode_message(p2) if isinstance(p2, bytes) else p2
                print(f"--> [DISPATCH RESPONSE] Opcode {op} -> {p2_dec}", flush=True)
        except Exception:
            break

    writer.close()
    await writer.wait_closed()
    print("=== TEST FINISHED ===", flush=True)

if __name__ == '__main__':
    asyncio.run(main())
