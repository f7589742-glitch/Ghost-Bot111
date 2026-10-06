import sys, os, json, asyncio, logging, time, signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("bot")

PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'active.json')

class GameBot:
    def __init__(self, profile_path=PROFILE_PATH):
        with open(profile_path) as f:
            self.profile = json.load(f)
        self.host = self.profile["auth_server"]
        self.port = self.profile["auth_port"]
        self.app_uid = self.profile["app_uid"]
        self.token = self.profile["access_token"]
        self.server_id = self.profile["server_id"]
        self.platform = self.profile.get("platform", "android").encode()

        self.reader = None
        self.writer = None
        self.crypto_tx = None
        self.crypto_rx = None
        self.running = False
        self.frame_count = 0
        self.connected = False

        self.chat_channels = {}
        self.player_info = {}
        self.server_info = {}

    def _build_login(self):
        inner = {1: 1, 9: 1}
        inner[4] = ProtobufCodec.encode_message({6: self.app_uid.encode()})
        auth = {
            1: self.app_uid.encode(),
            2: self.token.encode(),
            3: self.server_id,
            4: self.platform,
            5: 1,
        }
        inner[7] = ProtobufCodec.encode_message(auth)
        top = {1: 14, 2: ProtobufCodec.encode_message(inner)}
        return ProtobufCodec.encode_message(top)

    async def connect(self):
        logger.info("Connecting to %s:%d ...", self.host, self.port)
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)

        hdr = await self.reader.readexactly(2)
        glen = (hdr[0] << 8) | hdr[1]
        gpayload = await self.reader.readexactly(glen)
        gfields = ProtobufCodec.decode_message(gpayload)
        f2 = gfields.get(2, b"")
        sub = ProtobufCodec.decode_message(f2)
        sub1, sub2 = sub.get(1, 0), sub.get(2, 0)
        seed1, seed2 = derive_seed(sub1, sub2)
        self.crypto_tx = RokCrypto(seed1)
        self.crypto_rx = RokCrypto(seed2)
        logger.info("Greeting OK. Seeds: tx=%d rx=%d", seed1, seed2)

        login = self._build_login()
        enc = self.crypto_tx.encrypt(login)
        self.writer.write(FrameParser.build_frame(enc))
        await self.writer.drain()
        self.connected = True
        logger.info("Login sent (%d bytes, platform=%s)", len(login), self.platform.decode())

    async def send_opcode(self, opcode, payload=b""):
        msg = {1: opcode}
        if payload:
            msg[2] = payload
        enc = self.crypto_tx.encrypt(ProtobufCodec.encode_message(msg))
        self.writer.write(FrameParser.build_frame(enc))
        await self.writer.drain()

    async def keepalive(self):
        await self.send_opcode(9, ProtobufCodec.encode_message({1: 1}))

    async def send_chat(self, text, channel_id=1):
        chat_msg = ProtobufCodec.encode_message({
            1: text.encode("utf-8"),
            2: channel_id,
            3: int(time.time()),
        })
        await self.send_opcode(9911, chat_msg)

    async def read_frame(self):
        try:
            rh = await asyncio.wait_for(self.reader.readexactly(2), timeout=15.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(self.reader.readexactly(rl), timeout=15.0)
            return self.crypto_rx.decrypt(rd)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            return None
        except Exception as e:
            logger.error("Read error: %s", e)
            return None

    def handle_frame(self, opcode, data, full):
        self.frame_count += 1

        if opcode == 8003:
            return  # keepalive echo

        if opcode == 54:
            logger.info("[LOGIN_ACK] Server accepted login!")
            return

        info = ""
        if isinstance(data, bytes) and len(data) > 0:
            try:
                inner = ProtobufCodec.decode_message(data)
                parts = []
                for k, v in sorted(inner.items()):
                    if isinstance(v, str):
                        parts.append("%s=%s" % (k, v[:50]))
                    elif isinstance(v, bytes):
                        try:
                            s = v.decode('utf-8', errors='strict')
                            if len(s) > 1:
                                parts.append("F%d=%s" % (k, s[:50]))
                        except:
                            parts.append("F%d=(%dB)" % (k, len(v)))
                    elif isinstance(v, int):
                        parts.append("F%d=%d" % (k, v))
                info = " " + " ".join(parts[:8])
            except:
                info = " raw=" + data.hex()[:60]

        logger.info("[F#%d] opcode=%d len=%d%s", self.frame_count, opcode,
                     len(data) if isinstance(data, bytes) else 0, info)

    async def run(self):
        await self.connect()

        logger.info("Reading initial game data...")
        for i in range(40):
            dec = await self.read_frame()
            if dec is None:
                break
            try:
                pf = ProtobufCodec.decode_message(dec)
                opcode = pf.get(1, 0)
                data = pf.get(2, b"")
                self.handle_frame(opcode, data, pf)
            except:
                pass

        logger.info("=== INITIAL LOAD COMPLETE: %d frames ===", self.frame_count)
        read_task = asyncio.create_task(self._read_loop())
        keepalive_task = asyncio.create_task(self._keepalive_loop())

        logger.info("Commands: chat <msg> | ka (keepalive) | info | quit")

        loop = asyncio.get_event_loop()
        while self.running:
            try:
                cmd = await loop.run_in_executor(None, input)
                cmd = cmd.strip()
                if cmd.startswith("chat "):
                    await self.send_chat(cmd[5:])
                    logger.info("[CHAT] Sent: %s", cmd[5:])
                elif cmd == "ka":
                    await self.keepalive()
                    logger.info("[KA] Keepalive sent")
                elif cmd == "info":
                    logger.info("[INFO] Frames: %d, Connected: %s", self.frame_count, self.connected)
                elif cmd == "quit":
                    self.running = False
                elif cmd:
                    logger.info("Unknown command: %s", cmd)
            except EOFError:
                await asyncio.sleep(1)
            except KeyboardInterrupt:
                self.running = False

        read_task.cancel()
        keepalive_task.cancel()
        self.writer.close()
        await self.writer.wait_closed()
        logger.info("Bot stopped. Total frames: %d", self.frame_count)

    async def _read_loop(self):
        while self.running:
            dec = await self.read_frame()
            if dec is None:
                logger.warning("Connection lost!")
                self.running = False
                break
            try:
                pf = ProtobufCodec.decode_message(dec)
                opcode = pf.get(1, 0)
                data = pf.get(2, b"")
                self.handle_frame(opcode, data, pf)
            except Exception as e:
                logger.info("Frame %d parse error: %s raw=%s",
                           self.frame_count, str(e)[:40], dec.hex()[:80])

    async def _keepalive_loop(self):
        while self.running:
            await asyncio.sleep(3)
            try:
                await self.keepalive()
            except:
                break


if __name__ == "__main__":
    bot = GameBot()
    bot.running = True
    asyncio.run(bot.run())
