import sys, os, asyncio, json, struct, zlib
sys.path.insert(0, "/home/ubuntu/bot-backend")
sys.path.insert(0, "/home/ubuntu/bot-backend/python")
from fleet_manager import resolve_login_bytes
from app.services.proxy_transport import open_game_connection
from headless_client import ProtobufCodec, FrameParser
from crypto_module import RokCrypto
from derive_seed_from_nonce import derive_seed

async def check():
    with open("/home/ubuntu/bot-backend/accounts_fleet.json") as f:
        fleet = json.load(f)
    acc = next(a for a in fleet if any(str(c.get("role_id")) == "222157544" for c in a.get("characters", [])))
    login_bytes = resolve_login_bytes({"role_id": 222157544, "app_token": acc["access_token"], "app_uid": acc["app_uid"], "udid": acc["device_udid"], "kingdom_id": 3057})
    r, w = await open_game_connection("rocgate.lilithgame.com", 3101)
    hdr = await r.readexactly(2)
    gp = await r.readexactly((hdr[0]<<8)|hdr[1])
    sub_g = ProtobufCodec.decode_message(ProtobufCodec.decode_message(gp).get(2, b""))
    tx, rx = derive_seed(sub_g.get(1, 0), sub_g.get(2, 0))
    c_tx, c_rx = RokCrypto(tx), RokCrypto(rx)
    w.write(FrameParser.build_frame(c_tx.encrypt(login_bytes)))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 104, 2: b""}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 107, 2: b""}))))
    w.write(FrameParser.build_frame(c_tx.encrypt(ProtobufCodec.encode_message({1: 1001, 2: b""}))))
    await w.drain()
    marches = []
    d = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < d:
        try:
            rh = await asyncio.wait_for(r.readexactly(2), timeout=0.3)
            rl = (rh[0]<<8)|rh[1]
            raw = await asyncio.wait_for(r.readexactly(rl), timeout=0.3)
            dec = c_rx.decrypt(raw)
            zi = dec.find(b"\x78\x9c")
            if zi == -1: zi = dec.find(b"\x78\x01")
            decomp = zlib.decompress(dec[zi:]) if zi != -1 else dec
            m = ProtobufCodec.decode_message(decomp)
            chunks = m.get(1, []) if isinstance(m.get(1), list) else [m]
            for c in chunks:
                it = ProtobufCodec.decode_message(c) if isinstance(c, bytes) else c
                if isinstance(it, dict):
                    op = it.get(1)
                    if op in (1005, 1023):
                        p2 = it.get(2)
                        if isinstance(p2, bytes) and b"222157544" in p2:
                            marches.append((op, p2))
        except Exception: break
    print(f"ACTIVE MARCHES DETECTED ON WIRE: {len(marches)}")
    for op, p2 in marches:
        print(f"March op={op} raw={p2[:80]}")
    w.close()

if __name__ == '__main__':
    asyncio.run(check())
