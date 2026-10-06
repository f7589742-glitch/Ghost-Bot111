import sys, os, json, asyncio, struct, logging, time, random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("rok_bot")


class RokBot:
    def __init__(self, profile_path):
        with open(profile_path) as f:
            self.profile = json.load(f)

        self.host = self.profile["auth_server"]
        self.port = self.profile["auth_port"]
        self.app_uid = self.profile["app_uid"]
        self.access_token = self.profile["access_token"]

        self.reader = None
        self.writer = None
        self.crypto_tx = None
        self.crypto_rx = None
        self.connected = False
        self.running = False
        self.frame_count = 0
        self.game_data = {}
        self.chat_channels = []
        self.msg_counter = 1

    def _build_login(self):
        pid = self.app_uid
        inner = {1: 1, 9: 1}
        inner[4] = ProtobufCodec.encode_message({6: pid.encode()})
        auth = {
            1: pid.encode(),
            2: self.access_token.encode(),
            3: self.profile["server_id"],
            4: b"android",
            5: 1,
        }
        inner[7] = ProtobufCodec.encode_message(auth)
        top = {1: 14, 2: ProtobufCodec.encode_message(inner)}
        return ProtobufCodec.encode_message(top)

    async def connect(self):
        logger.info("Connecting to %s:%d ...", self.host, self.port)
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)

        header = await self.reader.readexactly(2)
        length = (header[0] << 8) | header[1]
        payload = await self.reader.readexactly(length)

        fields = ProtobufCodec.decode_message(payload)
        field2 = fields.get(2, b"")
        sub_fields = ProtobufCodec.decode_message(field2)
        sub1 = sub_fields.get(1, 0)
        sub2 = sub_fields.get(2, 0)

        seed1, seed2 = derive_seed(sub1, sub2)
        self.crypto_tx = RokCrypto(seed1)
        self.crypto_rx = RokCrypto(seed2)

        login_payload = self._build_login()
        encrypted = self.crypto_tx.encrypt(login_payload)
        frame = FrameParser.build_frame(encrypted)
        self.writer.write(frame)
        await self.writer.drain()

        self.connected = True
        self.running = True
        logger.info("Login sent (%d bytes)", len(login_payload))

        for i in range(30):
            dec = await self._read_frame()
            if dec is None:
                break
            self.frame_count += 1
            try:
                pf = ProtobufCodec.decode_message(dec)
                opcode = pf.get(1, 0)
                data = pf.get(2, b"")
                self._handle_frame(opcode, data, pf)
            except Exception as e:
                logger.info("Frame %d: raw=%s", self.frame_count, dec.hex()[:80])

        return True

    def _handle_frame(self, opcode, data, full):
        if opcode == 8703:
            logger.info("[CHAT_CHANNEL] opcode=%d data=%s", opcode, data.hex() if isinstance(data, bytes) else data)
            if isinstance(data, bytes):
                try:
                    ch = ProtobufCodec.decode_message(data)
                    logger.info("  channels: %s", ch)
                except:
                    pass
        elif opcode == 8003:
            pass  # keepalive echo, skip
        elif opcode == 125:
            pass  # unknown, skip
        else:
            logger.info("[GAME] opcode=%d data_len=%d", opcode, len(data) if isinstance(data, bytes) else 0)

    async def _read_frame(self):
        try:
            rh = await asyncio.wait_for(self.reader.readexactly(2), timeout=15.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(self.reader.readexactly(rl), timeout=15.0)
            return self.crypto_rx.decrypt(rd)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error("Read error: %s", e)
            return None

    async def send_raw(self, opcode, payload=b""):
        msg = {1: opcode}
        if payload:
            msg[2] = payload
        encoded = ProtobufCodec.encode_message(msg)
        encrypted = self.crypto_tx.encrypt(encoded)
        frame = FrameParser.build_frame(encrypted)
        self.writer.write(frame)
        await self.writer.drain()

    async def keepalive(self):
        await self.send_raw(9, ProtobufCodec.encode_message({1: 1}))

    async def send_chat(self, text, channel="chat"):
        json_str = json.dumps({
            "msg_nonce": int(time.time() * 1000),
            "content_type": 1,
            "sender_type": 1,
            "target_type": 2,
            "msg_type": 2,
            "msg_content": text,
        })
        inner = {
            1: json_str.encode(),
        }
        await self.send_raw(9911, ProtobufCodec.encode_message(inner))
        logger.info("[CHAT] Sent to %s: %s", channel, text)

    async def _read_loop(self):
        while self.running:
            dec = await self._read_frame()
            if dec is None:
                logger.warning("Connection lost")
                self.running = False
                break

            self.frame_count += 1
            try:
                pf = ProtobufCodec.decode_message(dec)
                opcode = pf.get(1, 0)
                data = pf.get(2, b"")
                self._handle_frame(opcode, data, pf)
            except Exception as e:
                logger.info("Frame %d: raw=%s", self.frame_count, dec.hex()[:80])

    async def _keepalive_loop(self):
        while self.running:
            await asyncio.sleep(3)
            try:
                await self.keepalive()
            except:
                break

    async def run(self):
        await self.connect()
        read_task = asyncio.create_task(self._read_loop())
        keepalive_task = asyncio.create_task(self._keepalive_loop())

        logger.info("Bot is running! Commands: chat <msg>, quit")
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                cmd = await loop.run_in_executor(None, input)
                cmd = cmd.strip()
                if cmd.startswith("chat "):
                    await self.send_chat(cmd[5:])
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
        logger.info("Bot stopped. %d frames received.", self.frame_count)


if __name__ == "__main__":
    profile = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
    bot = RokBot(profile)
    asyncio.run(bot.run())
