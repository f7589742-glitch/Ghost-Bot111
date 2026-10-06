import sys, os, json, asyncio, struct, logging, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, LOGIN_PAYLOAD, build_login_payload
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test_full")


async def test_full_login():
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'active.json')
    with open(profile_path, encoding='utf-8') as f:
        profile = json.load(f)
    server = profile.get("server_host") or profile.get("auth_server", "43.159.113.101")
    port = int(profile.get("server_port") or profile.get("auth_port", 3101))
    reader, writer = await asyncio.open_connection(server, port)



    header = await reader.readexactly(2)
    length = (header[0] << 8) | header[1]
    payload = await reader.readexactly(length)
    fields = ProtobufCodec.decode_message(payload)
    field2 = fields.get(2, b"")
    sub_fields = ProtobufCodec.decode_message(field2)
    sub1, sub2 = sub_fields.get(1, 0), sub_fields.get(2, 0)
    seed1, seed2 = derive_seed(sub1, sub2)
    crypto_tx, crypto_rx = RokCrypto(seed1), RokCrypto(seed2)

    logger.info("=== Test 1: Full login payload (553 bytes) with our tokens ===")
    tokens = {
        "player_id": profile["app_uid"],
        "access_token": profile["access_token"],
        "app_uid": profile["app_uid"],
    }
    full_payload = build_login_payload(tokens)
    logger.info("Full payload size: %d bytes", len(full_payload))

    encrypted = crypto_tx.encrypt(full_payload)
    writer.write(FrameParser.build_frame(encrypted))
    await writer.drain()
    logger.info("Full login sent!")

    for i in range(25):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            opcode = pf.get(1, 0)
            data = pf.get(2, b"")
            logger.info("  resp%d opcode=%d data_len=%d", i+1, opcode, len(data) if isinstance(data, bytes) else 0)

            if opcode == 101 and isinstance(data, bytes):
                try:
                    inner = ProtobufCodec.decode_message(data)
                    logger.info("    CHAT/MSG: %s", inner)
                except:
                    pass
        except asyncio.TimeoutError:
            logger.info("  timeout after %d frames", i)
            break

    logger.info("Keeping connection alive for 15s. Check emulator for 'another device' message...")
    for i in range(5):
        await asyncio.sleep(3)
        try:
            msg = {1: 9, 2: ProtobufCodec.encode_message({1: 1})}
            encoded = ProtobufCodec.encode_message(msg)
            encrypted = crypto_tx.encrypt(encoded)
            writer.write(FrameParser.build_frame(encrypted))
            await writer.drain()

            rh = await asyncio.wait_for(reader.readexactly(2), timeout=3.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=3.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            opcode = pf.get(1, 0)
            data = pf.get(2, b"")
            logger.info("  keepalive_resp%d opcode=%d", i+1, opcode)
        except asyncio.TimeoutError:
            logger.info("  keepalive timeout")
        except Exception as e:
            logger.error("  keepalive error: %s", e)
            break

    writer.close()
    logger.info("Connection closed")

asyncio.run(test_full_login())
