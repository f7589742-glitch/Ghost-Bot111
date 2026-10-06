import sys, os, json, asyncio, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, build_minimal_login
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test_quick_chat")

async def test():
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
    with open(profile_path) as f:
        profile = json.load(f)

    quick_token = "A-aJhV1Rggx3kCqZR50XixvoYSOVp6-P"
    quick_uid = 260172399

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

    login_payload = build_minimal_login({
        "player_id": quick_uid,
        "access_token": quick_token,
        "app_uid": quick_uid,
    })
    encrypted = crypto_tx.encrypt(login_payload)
    writer.write(FrameParser.build_frame(encrypted))
    await writer.drain()

    logger.info("Login sent with quick_uid=%d", quick_uid)

    # Read all frames first
    all_frames = []
    for i in range(50):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            opcode = pf.get(1, 0)
            data = pf.get(2, b"")
            all_frames.append((opcode, data))
        except asyncio.TimeoutError:
            break

    logger.info("Received %d frames total", len(all_frames))

    # List all opcodes
    for i, (opcode, data) in enumerate(all_frames):
        dlen = len(data) if isinstance(data, bytes) else 0
        extra = ""
        if isinstance(data, bytes) and dlen > 0:
            try:
                inner = ProtobufCodec.decode_message(data)
                extra = " " + str({k: v if not isinstance(v, bytes) else f"({len(v)}B)" for k, v in inner.items()})
            except:
                pass
        logger.info("  [%d] opcode=%d len=%d%s", i, opcode, dlen, extra)

    # Now send chat
    chat_msg = "bot test from teez9334"
    chat_protobuf = ProtobufCodec.encode_message({
        1: chat_msg.encode("utf-8"),
        3: 1,
    })
    chat_inner = ProtobufCodec.encode_message({
        1: chat_protobuf,
        3: 2,
    })
    chat_frame_data = ProtobufCodec.encode_message({
        1: 9911,
        2: chat_inner,
    })
    encrypted_chat = crypto_tx.encrypt(chat_frame_data)
    writer.write(FrameParser.build_frame(encrypted_chat))
    await writer.drain()
    logger.info("Chat sent: '%s' (opcode 9911)", chat_msg)

    # Keepalive + read more
    keepalive = ProtobufCodec.encode_message({1: 9})
    enc_ka = crypto_tx.encrypt(keepalive)
    for _ in range(5):
        writer.write(FrameParser.build_frame(enc_ka))
        await writer.drain()
        await asyncio.sleep(1)
        try:
            while True:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=2.0)
                rl = (rh[0] << 8) | rh[1]
                rd = await asyncio.wait_for(reader.readexactly(rl), timeout=2.0)
                dec = crypto_rx.decrypt(rd)
                pf = ProtobufCodec.decode_message(dec)
                opcode = pf.get(1, 0)
                data = pf.get(2, b"")
                dlen = len(data) if isinstance(data, bytes) else 0
                extra = ""
                if opcode != 8003 and isinstance(data, bytes) and dlen > 0:
                    try:
                        inner = ProtobufCodec.decode_message(data)
                        extra = " " + str(inner)
                    except:
                        pass
                if opcode != 8003:
                    logger.info("  response: opcode=%d len=%d%s", opcode, dlen, extra)
                else:
                    logger.info("  keepalive echo")
        except asyncio.TimeoutError:
            pass

    writer.close()

asyncio.run(test())
