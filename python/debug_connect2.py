import sys, os, json, asyncio, struct, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("debug2")

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
with open(profile_path) as f:
    profile = json.load(f)

HOST = profile["auth_server"]
PORT = profile["auth_port"]

async def debug_connect():
    reader, writer = await asyncio.open_connection(HOST, PORT)
    logger.info("TCP connected to %s:%d", HOST, PORT)

    header = await reader.readexactly(2)
    length = (header[0] << 8) | header[1]
    payload = await reader.readexactly(length)
    greeting = header + payload
    logger.info("Greeting: %d bytes hex=%s", len(greeting), greeting.hex())

    protobuf_data = greeting[2:]
    fields = ProtobufCodec.decode_message(protobuf_data)
    field1 = fields.get(1, 0)
    field2 = fields.get(2, b"")
    logger.info("Field1=%d Field2=%d bytes", field1, len(field2))

    sub_fields = ProtobufCodec.decode_message(field2)
    sub1 = sub_fields.get(1, 0)
    sub2 = sub_fields.get(2, 0)
    logger.info("sub1=%d (0x%08x) sub2=%d (0x%08x)", sub1, sub1, sub2, sub2)

    seed1, seed2 = derive_seed(sub1, sub2)
    logger.info("Seeds: TX=0x%08x RX=0x%08x", seed1, seed2)

    # Try multiple seed combinations
    combos = [
        ("TX=seed1 RX=seed2", seed1, seed2),
        ("TX=seed2 RX=seed1", seed2, seed1),
        ("TX=seed1 RX=seed1", seed1, seed1),
        ("TX=seed2 RX=seed2", seed2, seed2),
        ("TX=sub1 RX=sub2", sub1 & 0x3fffffff, sub2 & 0x3fffffff),
        ("TX=sub2 RX=sub1", sub2 & 0x3fffffff, sub1 & 0x3fffffff),
    ]

    from headless_client import build_minimal_login, FrameParser
    tokens = {
        "player_id": profile.get("player_id", profile["app_uid"]),
        "access_token": profile["access_token"],
        "app_uid": profile["app_uid"],
    }
    login_payload = build_minimal_login(tokens)

    for label, tx_seed, rx_seed in combos:
        writer2 = writer
        reader2 = reader
        # Reconnect for each attempt
        if label != combos[0][0]:
            writer.close()
            reader2, writer2 = await asyncio.open_connection(HOST, PORT)
            h = await reader2.readexactly(2)
            l = (h[0] << 8) | h[1]
            await reader2.readexactly(l)

        crypto_tx = RokCrypto(tx_seed)
        crypto_rx = RokCrypto(rx_seed)

        encrypted = crypto_tx.encrypt(login_payload)
        frame = FrameParser.build_frame(encrypted)
        writer2.write(frame)
        await writer2.drain()

        logger.info("[%s] Sent login, waiting...", label)

        try:
            for i in range(5):
                rh = await asyncio.wait_for(reader2.readexactly(2), timeout=3.0)
                rl = (rh[0] << 8) | rh[1]
                rd = await asyncio.wait_for(reader2.readexactly(rl), timeout=3.0)

                # Try decrypting entire payload (no type byte separation)
                dec_full = crypto_rx.decrypt(rd)
                logger.info("  [%s] frame%d len=%d dec_full=%s", label, i+1, rl, dec_full.hex()[:200])

                # Also try skipping first byte
                dec_skip = crypto_rx.decrypt(rd[1:])
                logger.info("  [%s] frame%d dec_skip1=%s", label, i+1, dec_skip.hex()[:200])

                # Try protobuf decode on full
                try:
                    pf = ProtobufCodec.decode_message(dec_full)
                    logger.info("  [%s] protobuf_full: %s", label, pf)
                except:
                    pass
                try:
                    pf = ProtobufCodec.decode_message(dec_skip)
                    logger.info("  [%s] protobuf_skip: %s", label, pf)
                except:
                    pass

        except asyncio.TimeoutError:
            logger.info("  [%s] timeout after frames", label)

    writer.close()
    logger.info("Done")

asyncio.run(debug_connect())
