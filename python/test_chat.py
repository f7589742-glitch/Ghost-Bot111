import sys, os, json, asyncio, struct, logging, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test_chat")


def build_login(app_uid, access_token, server_id):
    pid = app_uid
    inner = {1: 1, 9: 1}
    inner[4] = ProtobufCodec.encode_message({6: pid.encode()})
    auth = {
        1: pid.encode(),
        2: access_token.encode(),
        3: server_id,
        4: b"android",
        5: 1,
    }
    inner[7] = ProtobufCodec.encode_message(auth)
    top = {1: 14, 2: ProtobufCodec.encode_message(inner)}
    return ProtobufCodec.encode_message(top)


async def test_chat():
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
    with open(profile_path) as f:
        profile = json.load(f)

    reader, writer = await asyncio.open_connection(profile["auth_server"], profile["auth_port"])

    header = await reader.readexactly(2)
    length = (header[0] << 8) | header[1]
    payload = await reader.readexactly(length)
    fields = ProtobufCodec.decode_message(payload)
    field2 = fields.get(2, b"")
    sub_fields = ProtobufCodec.decode_message(field2)
    sub1, sub2 = sub_fields.get(1, 0), sub_fields.get(2, 0)
    seed1, seed2 = derive_seed(sub1, sub2)
    crypto_tx, crypto_rx = RokCrypto(seed1), RokCrypto(seed2)

    login = build_login(profile["app_uid"], profile["access_token"], profile["server_id"])
    encrypted = crypto_tx.encrypt(login)
    writer.write(FrameParser.build_frame(encrypted))
    await writer.drain()

    for i in range(22):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            opcode = pf.get(1, 0)
            data = pf.get(2, b"")
            if opcode == 8703:
                logger.info("CHAT_CHANNEL: %s", data)
            elif opcode != 8003 and opcode != 125:
                logger.info("opcode=%d data_len=%d", opcode, len(data) if isinstance(data, bytes) else 0)
        except asyncio.TimeoutError:
            break

    logger.info("=== Sending chat message ===")
    chat_json = json.dumps({
        "msg_nonce": int(time.time() * 1000),
        "content_type": 1,
        "sender_type": 1,
        "target_type": 2,
        "msg_type": 2,
        "msg_content": "Hello from bot!"
    })
    inner = {1: chat_json.encode()}
    payload = ProtobufCodec.encode_message(inner)
    msg = {1: 9911, 2: payload}
    encoded = ProtobufCodec.encode_message(msg)
    encrypted = crypto_tx.encrypt(encoded)
    writer.write(FrameParser.build_frame(encrypted))
    await writer.drain()
    logger.info("Chat sent! Waiting for response...")

    for i in range(10):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            opcode = pf.get(1, 0)
            data = pf.get(2, b"")
            logger.info("Response: opcode=%d data=%s", opcode, data.hex()[:100] if isinstance(data, bytes) else data)
            if opcode == 101:
                try:
                    chat_pf = ProtobufCodec.decode_message(data)
                    logger.info("  Chat msg: %s", chat_pf)
                except:
                    pass
        except asyncio.TimeoutError:
            break

    writer.close()
    logger.info("Done")

asyncio.run(test_chat())
