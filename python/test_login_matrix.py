import sys, os, json, asyncio, logging, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, LOGIN_PAYLOAD
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test")

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
with open(profile_path) as f:
    profile = json.load(f)

app_uid = profile["app_uid"]      # 220296728
role_id = profile.get("role_id", "193185268")  # character ID
token = profile["access_token"]
server_id = profile["server_id"]  # 2104267

def build_full_android_login():
    inner = {1: 1, 9: 1}
    inner[4] = ProtobufCodec.encode_message({6: app_uid.encode()})
    auth = {
        1: app_uid.encode(),
        2: token.encode(),
        3: server_id,
        4: b"android",
        5: 1,
    }
    inner[7] = ProtobufCodec.encode_message(auth)
    top = {1: 14, 2: ProtobufCodec.encode_message(inner)}
    return ProtobufCodec.encode_message(top)

def build_full_pc_login():
    inner = {1: 1, 9: 1}
    inner[4] = ProtobufCodec.encode_message({6: app_uid.encode()})
    auth = {
        1: app_uid.encode(),
        2: token.encode(),
        3: server_id,
        4: b"pc",
        5: 1,
    }
    inner[7] = ProtobufCodec.encode_message(auth)
    top = {1: 14, 2: ProtobufCodec.encode_message(inner)}
    return ProtobufCodec.encode_message(top)

def build_minimal_android():
    inner = {1: 1, 9: 1}
    inner[4] = ProtobufCodec.encode_message({6: app_uid.encode()})
    auth = {
        1: app_uid.encode(),
        2: token.encode(),
        3: server_id,
        4: b"android",
        5: 1,
    }
    inner[7] = ProtobufCodec.encode_message(auth)
    top = {1: 14, 2: ProtobufCodec.encode_message(inner)}
    return ProtobufCodec.encode_message(top)

def build_template_login():
    tokens = {"player_id": app_uid, "access_token": token, "app_uid": app_uid}
    top = ProtobufCodec.decode_message(LOGIN_PAYLOAD)
    inner = ProtobufCodec.decode_message(top[2])
    inner[4] = app_uid
    if 7 in inner:
        f7 = ProtobufCodec.decode_message(inner[7])
        f7[1] = app_uid.encode()
        f7[2] = token.encode()
        inner[7] = ProtobufCodec.encode_message(f7)
    top[2] = ProtobufCodec.encode_message(inner)
    return ProtobufCodec.encode_message(top)

TESTS = [
    ("minimal_android", build_full_android_login),
    ("template_full", build_template_login),
]

async def try_login(name, payload_builder):
    try:
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

        login = payload_builder()
        encrypted = crypto_tx.encrypt(login)
        writer.write(FrameParser.build_frame(encrypted))
        await writer.drain()

        frames = []
        for i in range(20):
            try:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
                rl = (rh[0] << 8) | rh[1]
                rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
                dec = crypto_rx.decrypt(rd)
                pf = ProtobufCodec.decode_message(dec)
                opcode = pf.get(1, 0)
                data = pf.get(2, b"")
                frames.append((opcode, data))
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                break

        writer.close()
        await writer.wait_closed()

        opcodes = [f[0] for f in frames]
        logger.info("[%s] %d bytes sent, %d frames recv: %s", name, len(login), len(frames), opcodes)
        if len(frames) > 2:
            for i, (op, data) in enumerate(frames[:10]):
                info = ""
                if isinstance(data, bytes) and len(data) > 0:
                    try:
                        inner = ProtobufCodec.decode_message(data)
                        info = str({k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})[:100]
                    except:
                        info = data.hex()[:60]
                logger.info("  #%d opcode=%d %s", i, op, info)
        return len(frames)
    except Exception as e:
        logger.error("[%s] ERROR: %s", name, e)
        return 0

async def main():
    best = 0
    best_name = ""
    for name, builder in TESTS:
        logger.info("=== Testing %s ===", name)
        n = await try_login(name, builder)
        if n > best:
            best = n
            best_name = name
        logger.info("")

    logger.info("=== BEST: %s with %d frames ===", best_name, best)

asyncio.run(main())
