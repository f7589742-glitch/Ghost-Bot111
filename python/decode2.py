import sys, os, json, asyncio, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, build_minimal_login
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("decode2")

async def decode():
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

    login_payload = build_minimal_login({
        "player_id": profile["app_uid"],
        "access_token": profile["access_token"],
        "app_uid": profile["app_uid"],
    })
    encrypted = crypto_tx.encrypt(login_payload)
    writer.write(FrameParser.build_frame(encrypted))
    await writer.drain()

    for i in range(30):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            opcode = pf.get(1, 0)
            data = pf.get(2, b"")
            
            logger.info("Frame %d: opcode=%d data_len=%d", i+1, opcode, len(data) if isinstance(data, bytes) else 0)
            
            if isinstance(data, bytes) and len(data) > 0:
                try:
                    inner = ProtobufCodec.decode_message(data)
                    for k, v in sorted(inner.items()):
                        if isinstance(v, bytes):
                            try:
                                s = v.decode("utf-8", errors="strict")
                                if len(s) > 2:
                                    logger.info("  F%d (str): %s", k, s)
                            except:
                                pass
                        elif isinstance(v, int):
                            logger.info("  F%d: %d", k, v)
                        elif isinstance(v, dict):
                            logger.info("  F%d: %s", k, v)
                except:
                    pass
        except asyncio.TimeoutError:
            break

    writer.close()

asyncio.run(decode())
