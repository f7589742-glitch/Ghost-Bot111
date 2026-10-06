import sys, os, json, asyncio, struct, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, LOGIN_PAYLOAD, FrameParser, build_login_payload, build_minimal_login
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test3")

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
with open(profile_path) as f:
    profile = json.load(f)

HOST = profile["auth_server"]
PORT = profile["auth_port"]

async def test():
    reader, writer = await asyncio.open_connection(HOST, PORT)

    header = await reader.readexactly(2)
    length = (header[0] << 8) | header[1]
    payload = await reader.readexactly(length)
    greeting = header + payload
    logger.info("Greeting: %d bytes", len(greeting))

    protobuf_data = greeting[2:]
    fields = ProtobufCodec.decode_message(protobuf_data)
    field2 = fields.get(2, b"")
    sub_fields = ProtobufCodec.decode_message(field2)
    sub1 = sub_fields.get(1, 0)
    sub2 = sub_fields.get(2, 0)
    logger.info("sub1=%d sub2=%d", sub1, sub2)

    seed1, seed2 = derive_seed(sub1, sub2)
    crypto_tx = RokCrypto(seed1)
    crypto_rx = RokCrypto(seed2)

    tokens = {
        "player_id": profile.get("player_id", profile["app_uid"]),
        "access_token": profile["access_token"],
        "app_uid": profile["app_uid"],
    }

    # Test 1: Full login payload with tokens injected
    logger.info("=== Test 1: Full login payload ===")
    full_payload = build_login_payload(tokens)
    logger.info("Full payload: %d bytes", len(full_payload))

    encrypted = crypto_tx.encrypt(full_payload)
    frame = FrameParser.build_frame(encrypted)
    writer.write(frame)
    await writer.drain()

    try:
        for i in range(5):
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=3.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=3.0)
            dec = crypto_rx.decrypt(rd)
            logger.info("  resp%d len=%d dec=%s", i+1, rl, dec.hex()[:200])
            try:
                pf = ProtobufCodec.decode_message(dec)
                logger.info("  protobuf: %s", pf)
            except:
                pass
    except asyncio.TimeoutError:
        logger.info("  timeout")

    writer.close()

    # Test 2: Try with platform_token as access_token
    logger.info("\n=== Test 2: Platform token as access_token ===")
    reader2, writer2 = await asyncio.open_connection(HOST, PORT)
    h2 = await reader2.readexactly(2)
    l2 = (h2[0] << 8) | h2[1]
    await reader2.readexactly(l2)

    h22 = await reader2.readexactly(2)
    l22 = (h22[0] << 8) | h22[1]
    p22 = await reader2.readexactly(l22)
    g2 = h22 + p22
    f2 = ProtobufCodec.decode_message(g2[2:])
    sf2 = ProtobufCodec.decode_message(f2.get(2, b""))
    s1_2 = sf2.get(1, 0)
    s2_2 = sf2.get(2, 0)
    sd1_2, sd2_2 = derive_seed(s1_2, s2_2)
    ctx2 = RokCrypto(sd1_2)
    crx2 = RokCrypto(sd2_2)

    tokens2 = {
        "player_id": profile.get("player_id", profile["app_uid"]),
        "access_token": profile["platform_token"],
        "app_uid": profile["app_uid"],
    }
    payload2 = build_minimal_login(tokens2)
    enc2 = ctx2.encrypt(payload2)
    frame2 = FrameParser.build_frame(enc2)
    writer2.write(frame2)
    await writer2.drain()

    try:
        for i in range(5):
            rh = await asyncio.wait_for(reader2.readexactly(2), timeout=3.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader2.readexactly(rl), timeout=3.0)
            dec = crx2.decrypt(rd)
            logger.info("  resp%d len=%d dec=%s", i+1, rl, dec.hex()[:200])
            try:
                pf = ProtobufCodec.decode_message(dec)
                logger.info("  protobuf: %s", pf)
            except:
                pass
    except asyncio.TimeoutError:
        logger.info("  timeout")

    writer2.close()
    logger.info("Done")

asyncio.run(test())
