import sys, os, json, asyncio, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, LOGIN_PAYLOAD, build_login_payload
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("decode_frames")

async def decode_all_frames():
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

    tokens = {
        "player_id": profile["app_uid"],
        "access_token": profile["access_token"],
        "app_uid": profile["app_uid"],
    }
    full_payload = build_login_payload(tokens)
    encrypted = crypto_tx.encrypt(full_payload)
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
            frames.append((opcode, data))
        except asyncio.TimeoutError:
            break

    writer.close()

    for opcode, data in frames:
        logger.info("=== Opcode %d (%d bytes) ===", opcode, len(data) if isinstance(data, bytes) else 0)
        if isinstance(data, bytes) and len(data) > 0:
            try:
                inner = ProtobufCodec.decode_message(data)
                for k, v in sorted(inner.items()):
                    if isinstance(v, bytes):
                        try:
                            s = v.decode("utf-8", errors="strict")
                            if len(s) > 2 and all(32 <= ord(c) < 127 for c in s):
                                logger.info("  F%d (str): %s", k, s)
                            else:
                                logger.info("  F%d (bytes %d): %s", k, len(v), v.hex()[:100])
                        except:
                            logger.info("  F%d (bytes %d): %s", k, len(v), v.hex()[:100])
                    elif isinstance(v, dict):
                        logger.info("  F%d (msg): %s", k, v)
                    else:
                        logger.info("  F%d: %s", k, v)

                if opcode in (125, 2114, 8600, 9999, 2136, 7922):
                    for k, v in inner.items():
                        if isinstance(v, bytes) and len(v) > 5:
                            try:
                                nested = ProtobufCodec.decode_message(v)
                                for nk, nv in sorted(nested.items()):
                                    if isinstance(nv, bytes):
                                        try:
                                            ns = nv.decode("utf-8", errors="strict")
                                            if len(ns) > 2:
                                                logger.info("    F%d.F%d (str): %s", k, nk, ns)
                                        except:
                                            pass
                                    elif isinstance(nv, int) and nv > 1000:
                                        logger.info("    F%d.F%d: %d", k, nk, nv)
                            except:
                                pass
            except Exception as e:
                logger.info("  raw: %s", data.hex()[:200])

asyncio.run(decode_all_frames())
