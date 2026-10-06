import sys, os, json, asyncio, logging, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed
from command_builder import (
    build_train_infantry, build_train_cavalry, build_train_archer, build_train_siege,
    build_gather_resource, build_march_move, build_troop_management,
    build_alliance_help, build_keepalive,
    TROOP_INFANTRY_T4, TROOP_CAVALRY_T4, TROOP_ARCHER_T4, TROOP_SIEGE_T4,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'active.json')) as f:
    profile = json.load(f)

async def test_commands():
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
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            if op != 8003:
                logger.info("INIT opcode=%d", op)
        except:
            break

    async def send_and_wait(opcode, payload, label, wait=3):
        msg = {1: opcode}
        if payload:
            msg[2] = payload
        enc = crypto_tx.encrypt(ProtobufCodec.encode_message(msg))
        writer.write(FrameParser.build_frame(enc))
        await writer.drain()
        logger.info("[SENT] %s opcode=%d payload=%dB", label, opcode, len(payload) if payload else 0)

        responses = []
        deadline = time.time() + wait
        while time.time() < deadline:
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=1.0)
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
                        info = str({k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})[:120]
                    except:
                        info = data.hex()[:60]
                responses.append((op, data))
                logger.info("  [RESP] opcode=%d len=%d %s", op, len(data) if isinstance(data, bytes) else 0, info)
            except asyncio.TimeoutError:
                break
            except:
                break
        return responses

    logger.info("=== Testing TRAIN INFANTRY (opcode 102) ===")
    opcode, payload = build_train_infantry(5)
    await send_and_wait(opcode, payload, "train_infantry_T4x5")

    logger.info("\n=== Testing TRAIN CAVALRY (opcode 102) ===")
    opcode, payload = build_train_cavalry(5)
    await send_and_wait(opcode, payload, "train_cavalry_T4x5")

    logger.info("\n=== Testing TROOP MANAGEMENT (opcode 1161) ===")
    opcode, payload = build_troop_management()
    await send_and_wait(opcode, payload, "troop_management")

    logger.info("\n=== Testing ALLIANCE HELP (opcode 1205) ===")
    opcode, payload = build_alliance_help()
    await send_and_wait(opcode, payload, "alliance_help")

    logger.info("\n=== Testing GATHER RESOURCE (opcode 1012) ===")
    opcode, payload = build_gather_resource(0)
    await send_and_wait(opcode, payload, "gather_resource")

    logger.info("\n=== Testing MARCH MOVE (opcode 1004) ===")
    opcode, payload = build_march_move(100.0, 100.0)
    await send_and_wait(opcode, payload, "march_move")

    writer.close()
    await writer.wait_closed()
    logger.info("Done!")

asyncio.run(test_commands())
