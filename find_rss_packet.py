import asyncio
import json
import sys
import os

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed
from app.services.combat_engine import safe_decompress, unpack_frames

def recursive_search(obj, path=""):
    """Search for numbers matching ~7.6M (7.0M - 8.5M), ~4.8M (4.0M - 5.5M), ~7.3M (6.5M - 8.0M), ~694K (600K - 800K)"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            recursive_search(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            recursive_search(item, f"{path}[{idx}]")
    elif isinstance(obj, (bytes, bytearray)):
        try:
            decoded = ProtobufCodec.decode_message(bytes(obj))
            if isinstance(decoded, dict) and len(decoded) > 0:
                recursive_search(decoded, f"{path}(decoded)")
        except Exception:
            pass
    elif isinstance(obj, int):
        # Check if matches any of the 4 resources
        # Food: ~7.6M -> 7,000,000 to 8,200,000
        # Wood: ~4.8M -> 4,200,000 to 5,500,000
        # Stone: ~7.3M -> 6,800,000 to 8,000,000
        # Gold: ~694K -> 600,000 to 800,000
        if 7_000_000 <= obj <= 8_500_000:
            print(f"[*] POTENTIAL FOOD / STONE MATCH: {obj} at {path}")
        elif 4_200_000 <= obj <= 5_500_000:
            print(f"[*] POTENTIAL WOOD MATCH: {obj} at {path}")
        elif 600_000 <= obj <= 800_000:
            print(f"[*] POTENTIAL GOLD MATCH: {obj} at {path}")
        elif 50_000 <= obj <= 80_000:
            print(f"[-] small match (like 57k): {obj} at {path}")

async def test_rss_kd1():
    role_id = 232812223 # RSS KD1
    with open('/home/ubuntu/bot-backend/accounts_fleet.json') as f:
        fleet = json.load(f)
    acc = next(a for a in fleet if any(str(c.get('role_id')) == str(role_id) for c in a.get('characters', [])))
    login_bytes = resolve_login_bytes({'role_id': role_id, 'app_token': acc['access_token'], 'app_uid': acc['app_uid'], 'udid': acc['device_udid'], 'kingdom_id': 3159})
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
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1050, 2: b''}))))
    await w.drain()

    print(f"Connected and sent login for {role_id} (RSS KD1)... listening to packets...")
    deadline = asyncio.get_event_loop().time() + 6.0
    packets_received = []

    while asyncio.get_event_loop().time() < deadline:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.5)
            length = (rh[0] << 8) | rh[1]
            raw = await asyncio.wait_for(r.readexactly(length), timeout=0.5)
            dec = c_rx.decrypt(raw)
            decomp = safe_decompress(dec)
            m = ProtobufCodec.decode_message(decomp)
            for it in unpack_frames(m):
                op = it.get(1)
                p = it.get(2)
                print(f"[OPCODE RECV] Opcode: {op}, payload size: {len(p) if isinstance(p, bytes) else 0}")
                if isinstance(p, bytes):
                    try:
                        dec_p = ProtobufCodec.decode_message(p)
                        print(f"   Decoded Opcode {op} top keys: {list(dec_p.keys()) if isinstance(dec_p, dict) else type(dec_p)}")
                        recursive_search(dec_p, f"op_{op}")
                    except Exception as ex:
                        print(f"   Failed to decode op {op}: {ex}")
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            print("Loop err:", e)
            break
    w.close()

if __name__ == '__main__':
    asyncio.run(test_rss_kd1())
