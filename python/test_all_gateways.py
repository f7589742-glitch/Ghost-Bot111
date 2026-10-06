import sys, os, json, asyncio, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, build_minimal_login
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test_all")

async def test_combo(server, port, player_id, token, label):
    try:
        reader, writer = await asyncio.open_connection(server, port)
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
            "player_id": player_id,
            "access_token": token,
            "app_uid": player_id,
        })
        encrypted = crypto_tx.encrypt(login_payload)
        writer.write(FrameParser.build_frame(encrypted))
        await writer.drain()

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
                
                if frame_count <= 3:
                    if isinstance(data, bytes) and len(data) > 0:
                        try:
                            inner = ProtobufCodec.decode_message(data)
                            inner_str = ", ".join(f"{k}={v}" for k, v in sorted(inner.items()))
                            logger.info("[%s] Frame %d: opcode=%d data={%s}", label, frame_count, opcode, inner_str)
                        except:
                            logger.info("[%s] Frame %d: opcode=%d data_len=%d", label, frame_count, opcode, len(data))
                    else:
                        logger.info("[%s] Frame %d: opcode=%d data_len=0", label, frame_count, opcode)
            except asyncio.TimeoutError:
                break

        writer.close()
        logger.info("[%s] TOTAL FRAMES: %d", label, frame_count)
        return frame_count
    except Exception as e:
        logger.info("[%s] ERROR: %s", label, str(e)[:100])
        return 0

async def run_all_tests():
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
    with open(profile_path) as f:
        profile = json.load(f)

    lilith_token = profile["access_token"]
    lilith_uid = profile["app_uid"]
    quick_token = "A-aJhV1Rggx3kCqZR50XixvoYSOVp6-P"
    quick_uid = 260172399

    tasks = [
        test_combo("43.159.113.101", 3101, lilith_uid, lilith_token, "GW2+lilith"),
        test_combo("34.54.22.150", 3101, lilith_uid, lilith_token, "GW3+lilith"),
        test_combo("43.159.112.101", 3101, quick_uid, quick_token, "GW1+quick"),
        test_combo("43.159.113.101", 3101, quick_uid, quick_token, "GW2+quick"),
        test_combo("34.54.22.150", 3101, quick_uid, quick_token, "GW3+quick"),
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.info("Task %d exception: %s", i, str(r)[:100])

asyncio.run(run_all_tests())
