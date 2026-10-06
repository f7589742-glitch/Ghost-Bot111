import sys, asyncio, json, zlib, struct, re
sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.services.combat_engine import safe_decompress, unpack_frames

async def check_account(acc, char):
    role_id = char['role_id']
    login_bytes = resolve_login_bytes({
        'role_id': role_id,
        'app_token': acc['access_token'],
        'app_uid': acc['app_uid'],
        'udid': acc['device_udid'],
        'kingdom_id': 3057
    })
    try:
        r, w = await asyncio.wait_for(open_game_connection('rocgate.lilithgame.com', 3101), timeout=4.0)
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

        d = asyncio.get_event_loop().time() + 2.0
        active_marches = set()
        pat = str(role_id).encode() + rb'_\d+_(\d+)'
        while asyncio.get_event_loop().time() < d:
            try:
                rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
                rl = (rh[0] << 8) | rh[1]
                raw = await asyncio.wait_for(r.readexactly(rl), timeout=0.3)
                dec = c_rx.decrypt(raw)
                decomp = safe_decompress(dec)
                m = ProtobufCodec.decode_message(decomp)
                for it in unpack_frames(m):
                    op = it.get(1)
                    if op in (1005, 1023):
                        p2_raw = it.get(2, b'')
                        if isinstance(p2_raw, bytes):
                            for m_f in re.finditer(pat, p2_raw):
                                active_marches.add(m_f.group(0).decode())
            except Exception:
                break
        w.close()
        await w.wait_closed()
        print(f"[{char['name']}] Role {role_id}: {len(active_marches)} active march(es) -> {list(active_marches)}")
        return len(active_marches)
    except Exception as e:
        print(f"[{char['name']}] failed: {e}")
        return -1

async def main():
    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)
    for acc in fleet:
        for c in acc.get('characters', []):
            await check_account(acc, c)
            await asyncio.sleep(0.3)

asyncio.run(main())
