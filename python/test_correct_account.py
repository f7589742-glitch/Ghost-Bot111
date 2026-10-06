import sys, os, json, asyncio, logging, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test")

# The ACTUAL account logged into the game
APP_UID = "260167657"
ROLE_ID = "231922221"
TOKEN = "A-CFzNBA6nVnt6rwN1PruGYnoabZqC-P"
SERVER_ID = 2104267

HOST = "43.159.112.101"
PORT = 3101

TESTS = [
    ("app_uid_android", APP_UID, b"android"),
    ("app_uid_pc", APP_UID, b"pc"),
    ("role_id_android", ROLE_ID, b"android"),
    ("role_id_pc", ROLE_ID, b"pc"),
]

async def try_login(name, pid, platform):
    try:
        reader, writer = await asyncio.open_connection(HOST, PORT)

        hdr = await reader.readexactly(2)
        glen = (hdr[0] << 8) | hdr[1]
        gpayload = await reader.readexactly(glen)
        gfields = ProtobufCodec.decode_message(gpayload)
        f2 = gfields.get(2, b"")
        sub = ProtobufCodec.decode_message(f2)
        sub1, sub2 = sub.get(1, 0), sub.get(2, 0)
        seed1, seed2 = derive_seed(sub1, sub2)
        crypto_tx, crypto_rx = RokCrypto(seed1), RokCrypto(seed2)

        inner = {1: 1, 9: 1}
        inner[4] = ProtobufCodec.encode_message({6: pid.encode()})
        auth = {
            1: pid.encode(),
            2: TOKEN.encode(),
            3: SERVER_ID,
            4: platform,
            5: 1,
        }
        inner[7] = ProtobufCodec.encode_message(auth)
        top = {1: 14, 2: ProtobufCodec.encode_message(inner)}
        login = ProtobufCodec.encode_message(top)

        encrypted = crypto_tx.encrypt(login)
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
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                break

        writer.close()
        await writer.wait_closed()

        opcodes = [f[0] for f in frames]
        logger.info("[%s] pid=%s plat=%s login=%dB => %d frames: %s",
                    name, pid, platform.decode(), len(login), len(frames), opcodes)

        if len(frames) > 2:
            for i, (op, data) in enumerate(frames[:15]):
                info = ""
                if isinstance(data, bytes) and len(data) > 0:
                    try:
                        inner_pf = ProtobufCodec.decode_message(data)
                        for k, v in sorted(inner_pf.items()):
                            if isinstance(v, str):
                                info += " %s=%s" % (k, v[:40])
                            elif isinstance(v, bytes):
                                try:
                                    s = v.decode('utf-8', errors='strict')
                                    if len(s) > 1:
                                        info += " F%d=%s" % (k, s[:40])
                                except:
                                    info += " F%d=(%dB)" % (k, len(v))
                            elif isinstance(v, int):
                                if k != 1:
                                    info += " F%d=%d" % (k, v)
                    except:
                        info = data.hex()[:60]
                logger.info("  #%d opcode=%d%s", i, op, info)

        return len(frames)
    except Exception as e:
        logger.error("[%s] ERROR: %s", name, e)
        return 0

async def main():
    best = 0
    best_name = ""
    for name, pid, plat in TESTS:
        n = await try_login(name, pid, plat)
        if n > best:
            best = n
            best_name = name
        logger.info("")

    logger.info("=== RESULT: %s got %d frames ===", best_name, best)

asyncio.run(main())
