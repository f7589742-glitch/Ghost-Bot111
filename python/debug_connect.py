import sys, os, json, asyncio, struct, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("debug")

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
with open(profile_path) as f:
    profile = json.load(f)

HOST = profile["auth_server"]
PORT = profile["auth_port"]

async def debug_connect():
    reader, writer = await asyncio.open_connection(HOST, PORT)
    logger.info("TCP connected to %s:%d", HOST, PORT)

    # Read greeting: [length:2-BE][payload]
    header = await reader.readexactly(2)
    length = (header[0] << 8) | header[1]
    payload = await reader.readexactly(length)
    greeting = header + payload
    logger.info("Raw greeting: %d bytes total (2 header + %d payload)", len(greeting), length)
    logger.info("Greeting hex: %s", greeting.hex())

    # Parse protobuf
    protobuf_data = greeting[2:]
    logger.info("Protobuf data (%d bytes): %s", len(protobuf_data), protobuf_data.hex())

    fields = ProtobufCodec.decode_message(protobuf_data)
    logger.info("Top-level fields: %s", fields)

    field1 = fields.get(1, 0)
    field2 = fields.get(2, b"")
    logger.info("Field 1 (varint): %d (0x%x)", field1, field1)
    logger.info("Field 2 (bytes, %d bytes): %s", len(field2), field2.hex() if isinstance(field2, bytes) else repr(field2))

    if isinstance(field2, (bytes, bytearray)) and len(field2) >= 2:
        sub_fields = ProtobufCodec.decode_message(field2)
        logger.info("Nested fields: %s", sub_fields)
        sub1 = sub_fields.get(1, 0)
        sub2 = sub_fields.get(2, 0)
        logger.info("sub1=%d (0x%08x) sub2=%d (0x%08x)", sub1, sub1, sub2, sub2)

        from derive_seed_from_nonce import derive_seed
        seed1, seed2 = derive_seed(sub1, sub2)
        logger.info("Derived seeds: seed1=0x%08x seed2=0x%08x", seed1, seed2)

        # Init crypto
        crypto_tx = RokCrypto(seed1)
        crypto_rx = RokCrypto(seed2)

        # Build login
        from headless_client import build_minimal_login
        tokens = {
            "player_id": profile.get("player_id", profile["app_uid"]),
            "access_token": profile["access_token"],
            "app_uid": profile["app_uid"],
        }
        login_payload = build_minimal_login(tokens)
        logger.info("Login payload (%d bytes): %s", len(login_payload), login_payload.hex())

        # Encrypt and send
        encrypted = crypto_tx.encrypt(login_payload)
        logger.info("Encrypted payload (%d bytes): %s", len(encrypted), encrypted.hex())

        # Build frame: [length:2-BE][encrypted]
        frame = len(encrypted).to_bytes(2, 'big') + encrypted
        logger.info("Wire frame (%d bytes): %s", len(frame), frame.hex())
        writer.write(frame)
        await writer.drain()
        logger.info("Login sent, waiting for response...")

        # Read response frames
        for i in range(30):
            try:
                resp_header = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
                resp_len = (resp_header[0] << 8) | resp_header[1]
                resp_data = await asyncio.wait_for(reader.readexactly(resp_len), timeout=5.0)
                logger.info("Response frame %d: len=%d wire_hex=%s", i+1, resp_len, resp_data.hex()[:200])

                # Try decrypt first byte as type
                first_byte = resp_data[0]
                enc_part = resp_data[1:]
                dec = crypto_rx.decrypt(enc_part)
                logger.info("  first_byte=0x%02x enc_len=%d dec_hex=%s", first_byte, len(enc_part), dec.hex()[:200])

                # Try decoding as protobuf
                try:
                    pf = ProtobufCodec.decode_message(dec)
                    logger.info("  protobuf: %s", pf)
                except:
                    logger.info("  not valid protobuf")
            except asyncio.TimeoutError:
                logger.info("Timeout after frame %d", i)
                break

    writer.close()
    logger.info("Done")

asyncio.run(debug_connect())
