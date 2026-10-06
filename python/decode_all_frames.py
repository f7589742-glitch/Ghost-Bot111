import sys, os, json, asyncio, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, build_minimal_login
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("decode_all")

async def decode():
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

    frames = []
    for i in range(30):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            opcode = pf.get(1, 0)
            data = pf.get(2, b"")
            if opcode == 8003:
                continue
            frames.append((opcode, data))
        except asyncio.TimeoutError:
            break

    writer.close()

    for opcode, data in frames:
        logger.info("=== Opcode %d (%d bytes) ===", opcode, len(data) if isinstance(data, bytes) else 0)
        if not isinstance(data, bytes) or len(data) == 0:
            continue

        try:
            inner = ProtobufCodec.decode_message(data)
            _print_fields(inner, "", opcode)
        except Exception as e:
            logger.info("  raw hex: %s", data.hex()[:200])

def _print_fields(msg, prefix, opcode):
    for k in sorted(msg.keys()):
        v = msg[k]
        if isinstance(v, bytes):
            if len(v) == 0:
                logger.info("  %sF%d: (empty)", prefix, k)
                continue
            try:
                s = v.decode("utf-8", errors="strict")
                if len(s) > 1:
                    logger.info("  %sF%d (str): %s", prefix, k, s)
                    continue
            except:
                pass

            try:
                nested = ProtobufCodec.decode_message(v)
                if nested:
                    logger.info("  %sF%d (msg %d fields):", prefix, k, len(nested))
                    _print_fields(nested, prefix + "  ", opcode)
                else:
                    logger.info("  %sF%d (bytes %d): %s", prefix, k, len(v), v.hex()[:100])
            except:
                logger.info("  %sF%d (bytes %d): %s", prefix, k, len(v), v.hex()[:100])
        elif isinstance(v, dict):
            logger.info("  %sF%d (msg):", prefix, k)
            _print_fields(v, prefix + "  ", opcode)
        else:
            if k != 1 or opcode != 1:
                logger.info("  %sF%d: %s", prefix, k, v)

asyncio.run(decode())
