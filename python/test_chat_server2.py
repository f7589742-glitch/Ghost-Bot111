import socket, sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez8888_56.json')
with open(profile_path) as f:
    profile = json.load(f)

# First, resolve the chat server IPs
import socket
for name in ['rocchat.lilithgame.com', 'rocchat2.lilithgame.com']:
    try:
        ip = socket.gethostbyname(name)
        print("%s -> %s" % (name, ip))
    except:
        print("%s -> DNS failed" % name)

# Check if the chat IP matches any known game server connection
# The game connects to: 43.175.228.94:8080 (WHMP)
# Maybe the chat goes through the same connection?

# Let's try the direct IPs from the config
chat_servers = [
    '34.107.206.111',
    '139.95.8.78',
]

for ip in chat_servers:
    print("\n--- Trying %s:8080 ---" % ip)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect((ip, 8080))
        # Send RokCrypto-style greeting
        greeting = ProtobufCodec.encode_message({
            1: 8562,
            2: ProtobufCodec.encode_message({
                2: 100,
            }),
        })
        frame = greeting
        s.send(frame)
        print("Sent greeting")
        
        time.sleep(2)
        data = s.recv(4096)
        print("Response: %d bytes: %s" % (len(data), data.hex()[:200] if data else "empty"))
    except Exception as e:
        print("Error: %s" % str(e)[:80])
    finally:
        s.close()

# Also try port 8080 on the same game server IP
print("\n--- Trying game server 43.159.112.101:8080 ---")
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(('43.159.112.101', 8080))
    print("Connected!")
    time.sleep(1)
    data = s.recv(4096)
    print("Response: %d bytes" % len(data))
    if data:
        print("Hex: %s" % data.hex()[:200])
except Exception as e:
    print("Error: %s" % str(e)[:80])
finally:
    s.close()

# Maybe the chat goes through the SAME port 3101 but with a different initial message?
# Let me try connecting to 3101 and sending a chat handshake
print("\n--- Full game connection + chat via 3101 ---")
import asyncio
from headless_client import build_minimal_login

async def test():
    reader, writer = await asyncio.open_connection('43.159.112.101', 3101)
    header = await reader.readexactly(2)
    length = (header[0] << 8) | header[1]
    payload = await reader.readexactly(length)
    fields = ProtobufCodec.decode_message(payload)
    field2 = fields.get(2, b'')
    sub_fields = ProtobufCodec.decode_message(field2)
    sub1, sub2 = sub_fields.get(1, 0), sub_fields.get(2, 0)
    seed1, seed2 = derive_seed(sub1, sub2)
    crypto_tx, crypto_rx = RokCrypto(seed1), RokCrypto(seed2)
    
    login = build_minimal_login({
        'player_id': profile['app_uid'],
        'access_token': profile['access_token'],
        'app_uid': profile['app_uid'],
    })
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(login)))
    await writer.drain()
    
    for i in range(25):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            opcode = pf.get(1, 0)
            data = pf.get(2, b'')
            
            # Decode opcode 8703 (chat channel) in detail
            if opcode == 8703 and isinstance(data, bytes) and len(data) > 0:
                inner = ProtobufCodec.decode_message(data)
                print("Chat channel (8703): %s" % inner)
                for k, v in inner.items():
                    if isinstance(v, bytes):
                        try:
                            nested = ProtobufCodec.decode_message(v)
                            print("  F%d nested: %s" % (k, nested))
                        except:
                            print("  F%d raw: %s" % (k, v.hex()))
            
            # Decode opcode 125 (server config?) 
            if opcode == 125 and isinstance(data, bytes) and len(data) > 0:
                inner = ProtobufCodec.decode_message(data)
                print("Config (125): %s" % {k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})
                for k, v in inner.items():
                    if isinstance(v, bytes) and len(v) > 0:
                        try:
                            nested = ProtobufCodec.decode_message(v)
                            print("  F%d nested: %s" % (k, nested))
                        except:
                            print("  F%d raw: %s" % (k, v.hex()[:100]))
        except asyncio.TimeoutError:
            break
    
    writer.close()

asyncio.run(test())
