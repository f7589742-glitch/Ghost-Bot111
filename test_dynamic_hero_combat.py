import sys
import asyncio
import json

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.services.combat_engine import safe_decompress, unpack_frames, CombatEngine
from app.services.protocol.hero_parser import (
    parse_heroes_from_1201,
    parse_roster_from_1157,
    merge_rosters,
    parse_wall_garrison_from_1002,
    parse_unlocked_barb_level_from_1002,
    persist_roster_to_db,
)
from app.services.lilith_cloud import LilithCloudService
from cloud_role_switcher import switch_cloud_active_role


async def main():
    role_id = 222157544  # NUCROSHOP
    kingdom_id = 3057

    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)
    acc = next(a for a in fleet if any(str(c.get('role_id')) == str(role_id) for c in a.get('characters', [])))

    sw = switch_cloud_active_role(
        role_id=int(role_id), server_id=kingdom_id,
        app_uid=str(acc['app_uid']), app_token=str(acc['access_token']),
        udid=str(acc['device_udid']), app_id=2104267,
    )
    print('[SWITCH]', sw, flush=True)

    login_bytes = resolve_login_bytes({
        'role_id': int(role_id), 'app_token': acc['access_token'],
        'app_uid': acc['app_uid'], 'udid': acc['device_udid'], 'kingdom_id': kingdom_id,
    })
    gate_host, gate_port = LilithCloudService.resolve_gateway(
        str(acc['app_uid']), str(acc['access_token']), str(acc['device_udid']), kingdom_id,
    )

    reader, writer = await open_game_connection(gate_host, gate_port)
    try:
        # 1. Greeting handshake
        hdr = await asyncio.wait_for(reader.readexactly(2), timeout=6.0)
        gp = await reader.readexactly((hdr[0] << 8) | hdr[1])
        sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(gp).get(2, b''))
        tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
        c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)

        # 2. Login + FULL role assertion (203 is REQUIRED for Opcode 1201 roster dispatch)
        writer.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: ProtobufCodec.encode_message({1: int(role_id)})}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b''}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: ProtobufCodec.encode_message({1: int(role_id), 2: int(kingdom_id), 3: int(role_id)})}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b''}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 6404, 2: ProtobufCodec.encode_message({1: int(kingdom_id)})}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b''}))))
        await writer.drain()

        # 3. Ingest login stream: 1201 + 1157 + 1002 (dynamic hero discovery)
        parsed_1201, parsed_1157 = [], []
        garrison = set()
        barb_lvl = None
        opcodes_seen = set()
        big_payloads = {}
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.5)
                raw = await asyncio.wait_for(reader.readexactly((rh[0] << 8) | rh[1]), timeout=0.5)
                dec = c_rx.decrypt(raw)
                decomp = safe_decompress(dec)
                m = ProtobufCodec.decode_message(decomp)
                for it in unpack_frames(m):
                    op = it.get(1)
                    opcodes_seen.add(op)
                    p2 = it.get(2)
                    if op == 1201 and isinstance(p2, bytes):
                        parsed_1201 = parse_heroes_from_1201(p2)
                        print(f'[DISCOVERY] Opcode 1201 intercepted: {len(parsed_1201)} hero entries', flush=True)
                    elif op == 1157 and isinstance(p2, bytes):
                        parsed_1157 = parse_roster_from_1157(p2)
                        print(f'[DISCOVERY] Opcode 1157 intercepted: {len(parsed_1157)} entries', flush=True)
                    elif op == 1002 and isinstance(p2, bytes):
                        garrison |= parse_wall_garrison_from_1002(p2)
                        lvl = parse_unlocked_barb_level_from_1002(p2)
                        if lvl is not None:
                            barb_lvl = lvl
                    if isinstance(p2, bytes) and len(p2) > 2500:
                        big_payloads[op] = p2
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                continue
            except Exception:
                break

        print('[OPCODES SEEN]', sorted(opcodes_seen), flush=True)

        # Roster probe: scan big packets for hero-shaped lists {1: small_id, 4: level}
        for probe_op, p2 in sorted(big_payloads.items()):
            try:
                pm = ProtobufCodec.decode_message(p2)
            except Exception:
                continue
            for k, v in pm.items():
                items = v if isinstance(v, list) else [v]
                if not items or not all(isinstance(x, (bytes, bytearray)) for x in items):
                    continue
                hero_hits, lvl_hits = 0, 0
                sample = None
                for x in items[:120]:
                    try:
                        sm = ProtobufCodec.decode_message(bytes(x))
                    except Exception:
                        continue
                    hid = sm.get(1)
                    if isinstance(hid, int) and 1 <= hid <= 5000:
                        hero_hits += 1
                        if isinstance(sm.get(4), int) and 1 <= sm.get(4) <= 60:
                            lvl_hits += 1
                        if sample is None:
                            sample = dict(sm)
                if hero_hits >= 5:
                    print(f'[PROBE] Opcode {probe_op} field {k}: {len(items)} items, {hero_hits} hero-shaped IDs, {lvl_hits} with level-like f4 | sample: {sample}', flush=True)

        roster = merge_rosters(parsed_1201, parsed_1157)
        print(f'[ROSTER] merged: {len(roster)} heroes', flush=True)
        for h in roster[:20]:
            print(f'   hero {h["hero_id"]}: L{h["level"]} {h["star"]}* awakened={h["is_awakened"]}', flush=True)
        print('[GARRISON]', sorted(garrison), '| unlocked barb level (1002 Tag15):', barb_lvl, flush=True)

        if roster:
            persist_roster_to_db(role_id, roster, garrison, source='sim1201_live_test')
            print('[DB SYNC] roster persisted (commanders + commanders_meta in fleet file & sqlite)', flush=True)
        else:
            print('[WARN] no roster intercepted -> check opcode list above', flush=True)

        # IMPORTANT: close the discovery connection BEFORE the hunt opens its own
        # (two concurrent sessions for the same role -> gateway resets sockets)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        await asyncio.sleep(1.0)

        # 4. Launch the REAL 4-march hunt with the discovered state (skip persistence inside engine)
        combat_state = {
            'roster': roster,
            'garrison': garrison,
            'server_unlocked_barb_level': barb_lvl,
        }
        result = await CombatEngine.execute_barbarian_hunt(
            target_role_id=int(role_id),
            kingdom_id=kingdom_id,
            gate_host=gate_host,
            gate_port=gate_port,
            app_uid=str(acc['app_uid']),
            app_token=str(acc['access_token']),
            udid=str(acc['device_udid']),
            login_bytes=login_bytes,
            target_level=8,
            highest_barb_level='L8',
            skip_barbs_below='None',
            primary_commander='Auto',
            secondary_commander='None',
            combat_rounds=1,
            dispatch_all_marches=True,
            max_marches=4,
            heal_troops=True,
            log_callback=lambda msg: print(f'[LOG] {msg}', flush=True),
            _hero_discovery_state=combat_state,
        )
        print('=' * 65)
        print('FINAL 4-MARCH RESULT:', json.dumps(result, default=str), flush=True)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


if __name__ == '__main__':
    asyncio.run(main())
