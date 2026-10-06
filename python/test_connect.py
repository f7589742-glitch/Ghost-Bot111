import sys, os, json, asyncio, struct, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import (
    FrameParser, FrameType, ClientState,
    build_minimal_login, ProtobufCodec, parse_greeting
)
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test_connect")

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
with open(profile_path) as f:
    profile = json.load(f)

HOST = profile["auth_server"]
PORT = profile["auth_port"]
APP_UID = profile["app_uid"]
PLAYER_ID = profile.get("player_id", APP_UID)
ACCESS_TOKEN = profile["access_token"]

logger.info("Connecting to %s:%d", HOST, PORT)
logger.info("app_uid=%s player_id=%s token=%s...", APP_UID, PLAYER_ID, ACCESS_TOKEN[:20])

async def test_connect():
    try:
        reader, writer = await asyncio.open_connection(HOST, PORT)
        logger.info("TCP connected")

        header = await reader.readexactly(2)
        length = (header[0] << 8) | header[1]
        payload = await reader.readexactly(length)
        greeting_raw = header + payload
        logger.info("Greeting: %d bytes, hex=%s", length, greeting_raw.hex())

        greeting = parse_greeting(greeting_raw)
        logger.info("Greeting parsed: nonce8=%s sub1=%d sub2=%d",
                     greeting.nonce_8.hex(), greeting.sub1, greeting.sub2)

        mapped = derive_seed(greeting.sub1, greeting.sub2)
        seed1, seed2 = mapped[0], mapped[1]
        logger.info("Seeds: seed1=0x%08x seed2=0x%08x", seed1, seed2)

        crypto_tx = RokCrypto(seed1)
        crypto_rx = RokCrypto(seed2)

        login_tokens = {
            "player_id": PLAYER_ID,
            "access_token": ACCESS_TOKEN,
            "app_uid": APP_UID,
        }
        login_payload = build_minimal_login(login_tokens)
        logger.info("Login payload: %d bytes", len(login_payload))

        encrypted = crypto_tx.encrypt(login_payload)
        frame_wire = FrameParser.build_frame(encrypted)
        writer.write(frame_wire)
        await writer.drain()
        logger.info("Login sent")

        received = 0
        while received < 20:
            try:
                hdr = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
                flen = (hdr[0] << 8) | hdr[1]
                fdata = await reader.readexactly(flen)
                received += 1

                if len(fdata) >= 1:
                    ftype = fdata[0]
                    enc_payload = fdata[1:]
                    dec = crypto_rx.decrypt(enc_payload)
                    logger.info("Frame %d: type=0x%02x len=%d dec_hex=%s",
                                received, ftype, len(enc_payload), dec.hex()[:200])
            except asyncio.TimeoutError:
                logger.info("No more data after 5s (received %d frames)", received)
                break

        logger.info("Done. Total frames: %d", received)
        writer.close()

    except Exception as e:
        logger.error("Connection failed: %s", e)
        import traceback
        traceback.print_exc()

asyncio.run(test_connect())
