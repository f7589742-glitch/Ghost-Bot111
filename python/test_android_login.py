import sys, os, json, asyncio, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, LOGIN_PAYLOAD, build_login_payload
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test4")

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
with open(profile_path) as f:
    profile = json.load(f)

HOST = profile["auth_server"]
PORT = profile["auth_port"]

def build_android_login(tokens):
    top = ProtobufCodec.decode_message(LOGIN_PAYLOAD)
    inner = ProtobufCodec.decode_message(top[2])

    pid = str(tokens.get("player_id", tokens["app_uid"]))
    inner[4] = pid.encode()

    inner[23] = b"rocgate.lilithgame.com:3101"
    inner[11] = b"1.1.9.19"
    inner[12] = b"613027"
    inner[15] = b"1"

    if 7 in inner:
        auth = ProtobufCodec.decode_message(inner[7])
        auth[1] = pid.encode()
        auth[2] = tokens["access_token"].encode()
        auth[3] = 2104267
        auth[4] = b"android"
        auth[5] = 1
        inner[7] = ProtobufCodec.encode_message(auth)

    top[2] = ProtobufCodec.encode_message(inner)
    return ProtobufCodec.encode_message(top)


def build_android_minimal(tokens):
    pid = str(tokens.get("player_id", tokens["app_uid"]))
    inner = {1: 1, 9: 1}
    inner[4] = ProtobufCodec.encode_message({6: pid.encode()})
    auth = {
        1: pid.encode(),
        2: tokens['access_token'].encode(),
        3: 2104267,
        4: b'android',
        5: 1,
    }
    inner[7] = ProtobufCodec.encode_message(auth)
    top = {1: 14, 2: ProtobufCodec.encode_message(inner)}
    return ProtobufCodec.encode_message(top)


async def try_login(label, login_fn, tokens):
    logger.info("=== %s ===", label)
    reader, writer = await asyncio.open_connection(HOST, PORT)

    header = await reader.readexactly(2)
    length = (header[0] << 8) | header[1]
    payload = await reader.readexactly(length)
    protobuf_data = payload

    fields = ProtobufCodec.decode_message(protobuf_data)
    field2 = fields.get(2, b"")
    sub_fields = ProtobufCodec.decode_message(field2)
    sub1 = sub_fields.get(1, 0)
    sub2 = sub_fields.get(2, 0)

    seed1, seed2 = derive_seed(sub1, sub2)
    crypto_tx = RokCrypto(seed1)
    crypto_rx = RokCrypto(seed2)

    login_payload = login_fn(tokens)
    logger.info("  Payload: %d bytes", len(login_payload))

    encrypted = crypto_tx.encrypt(login_payload)
    frame = FrameParser.build_frame(encrypted)
    writer.write(frame)
    await writer.drain()

    frames = []
    try:
        for i in range(10):
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=4.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=4.0)
            dec = crypto_rx.decrypt(rd)
            frames.append(dec)
            try:
                pf = ProtobufCodec.decode_message(dec)
                logger.info("  resp%d len=%d protobuf=%s", i+1, rl, pf)
            except:
                logger.info("  resp%d len=%d hex=%s", i+1, rl, dec.hex()[:100])
    except asyncio.TimeoutError:
        pass

    writer.close()
    return frames


async def main():
    tokens = {
        "player_id": profile.get("player_id", profile["app_uid"]),
        "access_token": profile["access_token"],
        "app_uid": profile["app_uid"],
    }

    await try_login("Full login (platform=android)", build_android_login, tokens)
    await try_login("Minimal login (platform=android)", build_android_minimal, tokens)

    tokens2 = {
        "player_id": profile["app_uid"],
        "access_token": profile["access_token"],
        "app_uid": profile["app_uid"],
    }
    await try_login("Minimal (player_id=app_uid)", build_android_minimal, tokens2)

asyncio.run(main())
