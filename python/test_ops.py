import sys, os, json, asyncio, logging, time, struct, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("t")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'active.json')) as f:
    profile = json.load(f)

async def main():
    reader, writer = await asyncio.open_connection(profile["auth_server"], profile["auth_port"])
    hdr = await reader.readexactly(2)
    glen = (hdr[0] << 8) | hdr[1]
    gpayload = await reader.readexactly(glen)
    gfields = ProtobufCodec.decode_message(gpayload)
    f2 = gfields.get(2, b"")
    sub = ProtobufCodec.decode_message(f2)
    sub1, sub2 = sub.get(1, 0), sub.get(2, 0)
    seed1, seed2 = derive_seed(sub1, sub2)
    tx, rx = RokCrypto(seed1), RokCrypto(seed2)

    login = {1: 14, 2: ProtobufCodec.encode_message({
        1: 1, 9: 1,
        4: ProtobufCodec.encode_message({6: profile["app_uid"].encode()}),
        7: ProtobufCodec.encode_message({
            1: profile["app_uid"].encode(),
            2: profile["access_token"].encode(),
            3: profile["server_id"],
            4: b"android", 5: 1,
        }),
    })}
    writer.write(FrameParser.build_frame(tx.encrypt(ProtobufCodec.encode_message(login))))
    await writer.drain()

    for i in range(25):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
            rx.decrypt(rd)
        except:
            break

    logger.info("Connected. Testing commands...")

    async def send(opcode, payload=b"", wait=4):
        msg = {1: opcode}
        if payload:
            msg[2] = payload
        writer.write(FrameParser.build_frame(tx.encrypt(ProtobufCodec.encode_message(msg))))
        await writer.drain()
        
        resps = []
        end = time.time() + wait
        while time.time() < end:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=1.5)
                rl = (rh[0] << 8) | rh[1]
                rd = await asyncio.wait_for(reader.readexactly(rl), timeout=2.0)
                pf = ProtobufCodec.decode_message(rx.decrypt(rd))
                op = pf.get(1, 0)
                data = pf.get(2, b"")
                if op == 8003:
                    continue
                resps.append((op, data))
                if isinstance(data, bytes) and len(data) > 0:
                    try:
                        inner = ProtobufCodec.decode_message(data)
                        info = {k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()}
                    except:
                        info = data.hex()[:60]
                else:
                    info = {}
                logger.info("  C->%d  S<-%d %s", opcode, op, info)
            except:
                break
        return resps

    # Test known working commands first
    logger.info("--- OP925 (player state) ---")
    await send(925, ProtobufCodec.encode_message({1: 1}))

    logger.info("--- OP120 (status query) ---")
    await send(120, ProtobufCodec.encode_message({1: "66"}))

    logger.info("--- OP306 (timer) ---")
    await send(306, ProtobufCodec.encode_message({1: "74"}))

    logger.info("--- OP9 (keepalive) ---")
    await send(9, ProtobufCodec.encode_message({1: 1}))

    # Now try training variations
    logger.info("\n=== TRAINING ATTEMPTS ===")

    logger.info("--- OP102 v1: {2:{1:1,2:'50',3:68,4:1}} ---")
    await send(102, ProtobufCodec.encode_message({2: ProtobufCodec.encode_message({1: 1, 2: "50", 3: 68, 4: 1})}))

    logger.info("--- OP102 v2: {2:{1:1,2:267,3:5}} ---")
    await send(102, ProtobufCodec.encode_message({2: ProtobufCodec.encode_message({1: 1, 2: 267, 3: 5})}))

    logger.info("--- OP102 v3: {2:{1:1,2:1,3:267,4:5}} ---")
    await send(102, ProtobufCodec.encode_message({2: ProtobufCodec.encode_message({1: 1, 2: 1, 3: 267, 4: 5})}))

    logger.info("--- OP102 v4: {1:1,2:267,3:5} ---")
    await send(102, ProtobufCodec.encode_message({1: 1, 2: 267, 3: 5}))

    logger.info("--- OP102 v5: {2:{1:1,2:1,3:267,4:5,5:1}} ---")
    await send(102, ProtobufCodec.encode_message({2: ProtobufCodec.encode_message({1: 1, 2: 1, 3: 267, 4: 5, 5: 1})}))

    # Try troop recall / dismiss
    logger.info("\n=== OTHER TROOP COMMANDS ===")

    logger.info("--- OP2101: {1:1} ---")
    await send(2101, ProtobufCodec.encode_message({1: 1}))

    logger.info("--- OP2104: {1:1} ---")
    await send(2104, ProtobufCodec.encode_message({1: 1}))

    logger.info("--- OP1161: troop management ---")
    await send(1161, ProtobufCodec.encode_message({
        1: ProtobufCodec.encode_message({1: 0, 2: 0}),
        2: 1,
    }))

    logger.info("--- OP1205: alliance help ---")
    await send(1205, b"")

    logger.info("--- OP9453: {1:1, 2:target} ---")
    await send(9453, ProtobufCodec.encode_message({1: 1, 2: 1}))

    writer.close()
    await writer.wait_closed()

asyncio.run(main())
