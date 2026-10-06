import sys
import asyncio
import json
import os

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.services.combat_engine import safe_decompress, unpack_frames

ROLE_ID = 222157544
KINGDOM = 3057
OUTDIR = '/tmp/roster_probe'


async def main():
    os.makedirs(OUTDIR, exist_ok=True)
    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)
    acc = next(a for a in fleet if any(str(c.get('role_id')) == str(ROLE_ID) for c in a.get('characters', [])))

    login_bytes = resolve_login_bytes({
        'role_id': int(ROLE_ID), 'app_token': acc['access_token'],
        'app_uid': acc['app_uid'], 'udid': acc['device_udid'], 'kingdom_id': KINGDOM,
    })

    reader, writer = await open_game_connection('rocgate.lilithgame.com', 3101)
    try:
        hdr = await asyncio.wait_for(reader.readexactly(2), timeout=6.0)
        gp = await reader.readexactly((hdr[0] << 8) | hdr[1])
        sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(gp).get(2, b''))
        tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
        c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)

        writer.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 203, 2: ProtobufCodec.encode_message({1: int(ROLE_ID)})}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b''}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 110, 2: ProtobufCodec.encode_message({1: int(ROLE_ID), 2: int(KINGDOM), 3: int(ROLE_ID)})}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b''}))))
        writer.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b''}))))
        await writer.drain()

        saved = {}
        deadline = asyncio.get_event_loop().time() + 6.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=0.5)
                raw = await asyncio.wait_for(reader.readexactly((rh[0] << 8) | rh[1]), timeout=0.5)
                dec = c_rx.decrypt(raw)
                decomp = safe_decompress(dec)
                m = ProtobufCodec.decode_message(decomp)
                for it in unpack_frames(m):
                    op = it.get(1)
                    p2 = it.get(2)
                    if isinstance(p2, bytes) and len(p2) > 400:
                        path = os.path.join(OUTDIR, f'op{op}.bin')
                        with open(path, 'wb') as pf:
                            pf.write(p2)
                        saved[op] = len(p2)
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                continue
            except Exception:
                break
        print('[SAVED]', json.dumps(saved, sort_keys=True), flush=True)

        # Quick candidate scan: any field whose items decode with small-int field1
        for op in sorted(saved):
            with open(os.path.join(OUTDIR, f'op{op}.bin'), 'rb') as pf:
                p2 = pf.read()
            try:
                pm = ProtobufCodec.decode_message(p2)
            except Exception:
                continue
            for k, v in pm.items():
                items = v if isinstance(v, list) else [v]
                if not items or not all(isinstance(x, (bytes, bytearray)) for x in items):
                    continue
                hits = 0
                for x in items[:80]:
                    try:
                        sm = ProtobufCodec.decode_message(bytes(x))
                    except Exception:
                        continue
                    hid = sm.get(1)
                    if isinstance(hid, int) and 1 <= hid <= 5000:
                        hits += 1
                if hits >= 3:
                    print(f'[CANDIDATE] op {op} field {k}: {len(items)} items, {hits} small-id entries', flush=True)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


if __name__ == '__main__':
    asyncio.run(main())
