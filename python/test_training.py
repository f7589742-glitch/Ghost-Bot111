import sys, os, json, asyncio, logging, time, struct, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'active.json')) as f:
    profile = json.load(f)

async def connect():
    reader, writer = await asyncio.open_connection(profile["auth_server"], profile["auth_port"])
    hdr = await reader.readexactly(2)
    glen = (hdr[0] << 8) | hdr[1]
    gpayload = await reader.readexactly(glen)
    gfields = ProtobufCodec.decode_message(gpayload)
    f2 = gfields.get(2, b"")
    sub = ProtobufCodec.decode_message(f2)
    sub1, sub2 = sub.get(1, 0), sub.get(2, 0)
    seed1, seed2 = derive_seed(sub1, sub2)
    crypto_tx, crypto_rx = RokCrypto(seed1), RokCrypto(seed2)

    login = {
        1: 14, 2: ProtobufCodec.encode_message({
            1: 1, 9: 1,
            4: ProtobufCodec.encode_message({6: profile["app_uid"].encode()}),
            7: ProtobufCodec.encode_message({
                1: profile["app_uid"].encode(),
                2: profile["access_token"].encode(),
                3: profile["server_id"],
                4: b"android",
                5: 1,
            }),
        })
    }
    enc = crypto_tx.encrypt(ProtobufCodec.encode_message(login))
    writer.write(FrameParser.build_frame(enc))
    await writer.drain()

    for i in range(25):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
            dec = crypto_rx.decrypt(rd)
        except:
            break

    return reader, writer, crypto_tx, crypto_rx

async def send_and_read(writer, crypto_tx, crypto_rx, opcode, payload, label):
    msg = {1: opcode}
    if payload:
        msg[2] = payload
    enc = crypto_tx.encrypt(ProtobufCodec.encode_message(msg))
    writer.write(FrameParser.build_frame(enc))
    await writer.drain()

    responses = []
    deadline = time.time() + 4
    while time.time() < deadline:
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=1.5)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=2.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            data = pf.get(2, b"")
            if op == 8003:
                continue
            info = ""
            if isinstance(data, bytes) and len(data) > 0:
                try:
                    inner = ProtobufCodec.decode_message(data)
                    info = str({k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})[:150]
                except:
                    info = "hex=%s" % data.hex()[:80]
            responses.append((op, data))
            logger.info("  [%s] opcode=%d%s", label, op, info)
        except asyncio.TimeoutError:
            break
        except:
            break
    return responses

async def main():
    reader, writer, crypto_tx, crypto_rx = await connect()

    # Try all variations of opcode 102
    logger.info("=== Testing OP102 variations (training) ===")

    # v1: nested F2 with F1=1, F2="50", F3=68, F4=1
    p = ProtobufCodec.encode_message({2: ProtobufCodec.encode_message({1: 1, 2: "50", 3: 68, 4: 1})})
    await send_and_read(writer, crypto_tx, crypto_rx, 102, p, "102v1")

    # v2: direct fields F1=1, F2="50", F3=68, F4=1
    p = ProtobufCodec.encode_message({1: 1, 2: "50", 3: 68, 4: 1})
    await send_and_read(writer, crypto_tx, crypto_rx, 102, p, "102v2")

    # v3: F2 with F1=troop_type, F2=count
    p = ProtobufCodec.encode_message({2: ProtobufCodec.encode_message({1: 267, 2: 5})})
    await send_and_read(writer, crypto_tx, crypto_rx, 102, p, "102v3_troop267")

    # v4: direct F1=troop, F2=count
    p = ProtobufCodec.encode_message({1: 267, 2: 5})
    await send_and_read(writer, crypto_tx, crypto_rx, 102, p, "102v4_direct")

    # v5: F2 with building + troop
    p = ProtobufCodec.encode_message({2: ProtobufCodec.encode_message({1: 1, 2: 1, 3: 267, 4: 5})})
    await send_and_read(writer, crypto_tx, crypto_rx, 102, p, "102v5_bldg")

    # v6: F2={F1=building_type, F2=troop_type, F3=count}
    p = ProtobufCodec.encode_message({2: ProtobufCodec.encode_message({1: 1, 2: 267, 3: 5})})
    await send_and_read(writer, crypto_tx, crypto_rx, 102, p, "102v6_btg")

    logger.info("\n=== Testing OP11 (entity data request) ===")
    # From v224: opcode 11 is "entity data request" with f11{f2{f1=type,f2=id,f3,f4}}
    p = ProtobufCodec.encode_message({11: ProtobufCodec.encode_message({2: ProtobufCodec.encode_message({1: 2, 2: 1})})})
    await send_and_read(writer, crypto_tx, crypto_rx, 11, p, "op11_ent")

    logger.info("\n=== Testing OP2 (position update) ===")
    p = ProtobufCodec.encode_message({6: json.dumps({"y": 473, "t": 1, "x": 712}).encode()})
    await send_and_read(writer, crypto_tx, crypto_rx, 2, p, "op2_pos")

    logger.info("\n=== Testing OP6 (keepalive) ===")
    p = ProtobufCodec.encode_message({7: ProtobufCodec.encode_message({2: int(profile["app_uid"])})})
    await send_and_read(writer, crypto_tx, crypto_rx, 6, p, "op6_keepalive")

    logger.info("\n=== Testing OP8 (encrypted command) ===")
    p = ProtobufCodec.encode_message({1: 1, 2: 1})
    await send_and_read(writer, crypto_tx, crypto_rx, 8, p, "op8_enc")

    logger.info("\n=== Testing OP110 (player query) ===")
    p = ProtobufCodec.encode_message({1: int(profile["app_uid"]), 3: 1})
    await send_and_read(writer, crypto_tx, crypto_rx, 110, p, "op110_query")

    writer.close()
    await writer.wait_closed()

asyncio.run(main())
