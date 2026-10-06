import sys, os, json, asyncio, logging, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'active.json')) as f:
    profile = json.load(f)

async def test():
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
            data = pf.get(2, b"")
            if op == 9999 and isinstance(data, bytes) and len(data) > 4:
                import zlib
                try:
                    decompressed = zlib.decompress(data)
                    inner = ProtobufCodec.decode_message(decompressed)
                    logger.info("INIT[9999] decompressed=%dB fields=%s", len(decompressed),
                               {k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})
                    for k, v in inner.items():
                        if isinstance(v, bytes) and len(v) > 20:
                            try:
                                sub_inner = ProtobufCodec.decode_message(v)
                                logger.info("  9999.f%d = %s", k, {sk: sv if not isinstance(sv, bytes) else "(%dB)" % len(sv) for sk, sv in sub_inner.items()})
                            except:
                                pass
                except:
                    logger.info("INIT[9999] raw=%dB hex=%s", len(data), data[:40].hex())
            elif op == 8703 and isinstance(data, bytes):
                inner = ProtobufCodec.decode_message(data)
                logger.info("INIT[8703] CHAT channel: %s", inner)
            elif op != 8003:
                logger.info("INIT opcode=%d len=%d", op, len(data) if isinstance(data, bytes) else 0)
        except:
            break

    async def send_cmd(opcode, payload, label):
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
                    if op == 9999:
                        import zlib
                        try:
                            dc = zlib.decompress(data)
                            inner = ProtobufCodec.decode_message(dc)
                            info = " ZLIB(%dB) %s" % (len(dc), {k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in list(inner.items())[:5]})
                        except:
                            info = " raw=%s" % data.hex()[:60]
                    else:
                        try:
                            inner = ProtobufCodec.decode_message(data)
                            info = " %s" % {k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in list(inner.items())[:6]}
                        except:
                            info = " hex=%s" % data.hex()[:60]
                responses.append((op, data))
                logger.info("  [%s] RESP opcode=%d%s", label, op, info)
            except asyncio.TimeoutError:
                break
            except:
                break
        return responses

    logger.info("=== 1. Opcode 102 (captured format) ===")
    payload_102 = ProtobufCodec.encode_message({
        2: ProtobufCodec.encode_message({1: 1, 2: "50", 3: 68, 4: 1})
    })
    await send_cmd(102, payload_102, "op102")

    logger.info("\n=== 2. Opcode 102 simple ===")
    payload_102b = ProtobufCodec.encode_message({1: 1, 2: "50", 3: 68, 4: 1})
    await send_cmd(102, payload_102b, "op102b")

    logger.info("\n=== 3. Opcode 925 (player state) ===")
    await send_cmd(925, ProtobufCodec.encode_message({1: 1}), "op925")

    logger.info("\n=== 4. Opcode 120 (status update) ===")
    await send_cmd(120, ProtobufCodec.encode_message({1: "66"}), "op120")

    logger.info("\n=== 5. Opcode 1004 (march) ===")
    import struct
    x_bytes = struct.pack('<f', 100.0)
    y_bytes = struct.pack('<f', 100.0)
    payload_1004 = ProtobufCodec.encode_message({
        1: ProtobufCodec.encode_message({1: x_bytes, 2: y_bytes}),
        5: 1,
    })
    await send_cmd(1004, payload_1004, "op1004")

    logger.info("\n=== 6. Opcode 300 (timer request) ===")
    await send_cmd(300, ProtobufCodec.encode_message({1: "74", 3: 1200}), "op300")

    logger.info("\n=== 7. Opcode 306 (timer) ===")
    await send_cmd(306, ProtobufCodec.encode_message({1: "74"}), "op306")

    logger.info("\n=== 8. Opcode 8 (unknown) ===")
    await send_cmd(8, ProtobufCodec.encode_message({1: 1, 2: 1}), "op8")

    logger.info("\n=== 9. Opcode 5 (large command) ===")
    await send_cmd(5, ProtobufCodec.encode_message({1: 1}), "op5")

    writer.close()
    await writer.wait_closed()

asyncio.run(test())
