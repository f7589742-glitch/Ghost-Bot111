import sys, os, json, asyncio, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, build_minimal_login
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test_8888")

async def test():
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez8888.json')
    with open(profile_path) as f:
        profile = json.load(f)

    logger.info("Testing teez8888 on %s:%d", profile["server_host"], profile["server_port"])

    reader, writer = await asyncio.open_connection(profile["server_host"], profile["server_port"])
    header = await reader.readexactly(2)
    length = (header[0] << 8) | header[1]
    payload = await reader.readexactly(length)
    fields = ProtobufCodec.decode_message(payload)
    field2 = fields.get(2, b"")
    sub_fields = ProtobufCodec.decode_message(field2)
    sub1, sub2 = sub_fields.get(1, 0), sub_fields.get(2, 0)
    logger.info("Greeting: sub1=%d sub2=%d", sub1, sub2)
    seed1, seed2 = derive_seed(sub1, sub2)
    crypto_tx, crypto_rx = RokCrypto(seed1), RokCrypto(seed2)

    login_payload = build_minimal_login({
        "player_id": profile["app_uid"],
        "access_token": profile["access_token"],
        "app_uid": profile["app_uid"],
    })
    encrypted = crypto_tx.encrypt(login_payload)
    writer.write(FrameParser.build_frame(encrypted))
    await writer.drain()
    logger.info("Login sent (player_id=%s)", profile["app_uid"])

    frame_count = 0
    for i in range(30):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            opcode = pf.get(1, 0)
            data = pf.get(2, b"")
            frame_count += 1
            dlen = len(data) if isinstance(data, bytes) else 0
            extra = ""
            if isinstance(data, bytes) and dlen > 0:
                try:
                    inner = ProtobufCodec.decode_message(data)
                    extra = " " + str({k: v if not isinstance(v, bytes) else f"({len(v)}B)" for k, v in inner.items()})
                except:
                    pass
            logger.info("  Frame %d: opcode=%d len=%d%s", frame_count, opcode, dlen, extra)
        except asyncio.TimeoutError:
            break

    logger.info("TOTAL: %d frames", frame_count)
    writer.close()

asyncio.run(test())
