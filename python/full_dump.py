import asyncio, sys, os, json, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed
from _thread import exit as thread_exit

P = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'active.json')))

def _f(v):
    if isinstance(v, bytes):
        try:
            return {str(k): _f(sv) for k, sv in ProtobufCodec.decode_message(v).items()}
        except:
            try:
                return v.decode('utf-8')
            except:
                return "%dB" % len(v)
    return v

async def m():
    r, w = await asyncio.wait_for(asyncio.open_connection(P["auth_server"], P["auth_port"]), 10)
    h = await r.readexactly(2)
    gl = (h[0] << 8) | h[1]
    gp = await r.readexactly(gl)
    gf = ProtobufCodec.decode_message(gp)
    sub = ProtobufCodec.decode_message(gf.get(2, b""))
    s1, s2 = sub.get(1, 0), sub.get(2, 0)
    sd1, sd2 = derive_seed(s1, s2)
    tx, rx = RokCrypto(sd1), RokCrypto(sd2)

    w.write(FrameParser.build_frame(tx.encrypt(ProtobufCodec.encode_message({
        1: 14, 2: ProtobufCodec.encode_message({
            1: 1, 9: 1,
            4: ProtobufCodec.encode_message({6: P["app_uid"].encode()}),
            7: ProtobufCodec.encode_message({
                1: P["app_uid"].encode(),
                2: P["access_token"].encode(),
                3: P["server_id"],
                4: b"android", 5: 1,
            }),
        })
    }))))
    await w.drain()

    f = []
    for i in range(150):
        try:
            rh = await asyncio.wait_for(r.readexactly(2), 4)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(r.readexactly(rl), 4)
            pf = ProtobufCodec.decode_message(rx.decrypt(rd))
            op = pf.get(1, 0)
            data = pf.get(2, b"")
            if op == 8003:
                w.write(FrameParser.build_frame(tx.encrypt(ProtobufCodec.encode_message({
                    1: 9, 2: ProtobufCodec.encode_message({1: 1})
                }))))
                await w.drain()
                continue
            f.append((op, data))
        except:
            break

    try:
        w.close()
    except:
        pass

    D = []
    for idx, (op, data) in enumerate(f):
        e = {"i": idx, "op": op}
        if isinstance(data, bytes) and len(data) > 0:
            if op == 9999:
                try:
                    dc = zlib.decompress(data)
                    inner = ProtobufCodec.decode_message(dc)
                    e["z"] = len(dc)
                    e["d"] = {str(k): _f(v) for k, v in inner.items()}
                except:
                    e["r"] = data.hex()
            else:
                try:
                    inner = ProtobufCodec.decode_message(data)
                    e["d"] = {str(k): _f(v) for k, v in inner.items()}
                except:
                    e["r"] = data.hex()[:200]
        D.append(e)

    fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'game_dump.json')
    with open(fp, 'w') as fo:
        json.dump(D, fo, indent=2, default=str, ensure_ascii=False)
    print("DONE:%d frames" % len(D))
    ops = {}
    for op, _ in f:
        ops[op] = ops.get(op, 0) + 1
    for op, cnt in sorted(ops.items()):
        print(" op=%d cnt=%d" % (op, cnt))

asyncio.run(m())
os._exit(0)
