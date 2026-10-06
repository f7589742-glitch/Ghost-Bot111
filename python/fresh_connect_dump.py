import sys, os, json, asyncio, struct, logging, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("dump")

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
with open(profile_path) as f:
    profile = json.load(f)

host = profile["auth_server"]
port = profile["auth_port"]

# Build login
app_uid = profile["app_uid"]
token = profile["access_token"]
server_id = profile["server_id"]

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
login_payload = ProtobufCodec.encode_message(top)

logger.info("Connecting to %s:%d ...", host, port)

async def main():
    reader, writer = await asyncio.open_connection(host, port)
    
    # Read greeting
    header = await reader.readexactly(2)
    greeting_len = (header[0] << 8) | header[1]
    greeting_payload = await reader.readexactly(greeting_len)
    
    logger.info("Greeting: %d bytes, hex=%s", greeting_len, greeting_payload.hex())
    
    fields = ProtobufCodec.decode_message(greeting_payload)
    logger.info("Greeting fields: %s", {k: v if not isinstance(v, bytes) else "(%dB) %s" % (len(v), v.hex()[:40]) for k, v in fields.items()})
    
    field2 = fields.get(2, b"")
    sub = ProtobufCodec.decode_message(field2)
    sub1 = sub.get(1, 0)
    sub2 = sub.get(2, 0)
    logger.info("Sub1=%d (0x%08x) Sub2=%d (0x%08x)", sub1, sub1, sub2, sub2)
    
    seed1, seed2 = derive_seed(sub1, sub2)
    logger.info("Seed1=%d Seed2=%d", seed1, seed2)
    
    crypto_tx = RokCrypto(seed1)
    crypto_rx = RokCrypto(seed2)
    
    # Send login
    encrypted_login = crypto_tx.encrypt(login_payload)
    frame = FrameParser.build_frame(encrypted_login)
    writer.write(frame)
    await writer.drain()
    logger.info("Login sent (%d bytes encrypted, %d bytes plaintext)", len(encrypted_login), len(login_payload))
    
    # Read frames
    all_server_frames = []
    all_client_frames = []
    
    for i in range(80):
        try:
            hdr = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
        except asyncio.TimeoutError:
            logger.info("Timeout after frame %d" % i)
            break
        except asyncio.IncompleteReadError:
            logger.info("Connection closed after frame %d" % i)
            break
        
        length = (hdr[0] << 8) | hdr[1]
        payload = await reader.readexactly(length)
        
        try:
            decrypted = crypto_rx.decrypt(payload)
            pf = ProtobufCodec.decode_message(decrypted)
            opcode = pf.get(1, 0)
            data = pf.get(2, b"")
            plen = len(data) if isinstance(data, bytes) else 0
            
            info = ""
            if isinstance(data, bytes) and plen > 0:
                try:
                    inner_pf = ProtobufCodec.decode_message(data)
                    for k, v in sorted(inner_pf.items()):
                        if isinstance(v, str):
                            info += " %s=%s" % (k, v[:60])
                        elif isinstance(v, bytes):
                            try:
                                s = v.decode('utf-8', errors='strict')
                                if len(s) > 1:
                                    info += " F%d=%s" % (k, s[:60])
                            except:
                                info += " F%d=(%dB)" % (k, len(v))
                        elif isinstance(v, int):
                            if k != 1:
                                info += " F%d=%d" % (k, v)
                except:
                    if plen < 40:
                        info += " raw=%s" % data.hex()
            
            logger.info("S #%d opcode=%d len=%d%s", i, opcode, plen, info)
            all_server_frames.append((opcode, data, pf))
            
            # Send keepalive on opcode 8003
            if opcode == 8003:
                ka = ProtobufCodec.encode_message({1: 9})
                enc_ka = crypto_tx.encrypt(ka)
                ka_frame = FrameParser.build_frame(enc_ka)
                writer.write(ka_frame)
                await writer.drain()
                all_client_frames.append((9, ka))
                logger.info("C #%d keepalive sent (opcode 9)", i)
                
        except Exception as e:
            logger.info("S #%d DECRYPT ERROR: %s (raw=%s)", i, str(e)[:60], payload[:20].hex())
    
    # Summary
    logger.info("\n=== SUMMARY ===")
    logger.info("Server frames: %d", len(all_server_frames))
    opcode_counts = {}
    for opcode, _, _ in all_server_frames:
        opcode_counts[opcode] = opcode_counts.get(opcode, 0) + 1
    for opcode, count in sorted(opcode_counts.items()):
        logger.info("  opcode %d: %d frames", opcode, count)
    
    writer.close()
    await writer.wait_closed()

asyncio.run(main())
