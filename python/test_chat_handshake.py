import socket, sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez8888_56.json')
with open(profile_path) as f:
    profile = json.load(f)

host = 'rocchat.lilithgame.com'
port = 8080

print("Connecting to %s:%d" % (host, port))
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(10)
s.connect((host, port))
print("Connected!")

# Try sending raw protobuf greeting (like the game does)
# The game sends a greeting to port 3101, maybe chat expects similar
greeting = ProtobufCodec.encode_message({
    1: 8562,  # greeting field
    2: ProtobufCodec.encode_message({
        2: 100,
    }),
})
print("Sending greeting: %d bytes" % len(greeting))
s.send(greeting)

time.sleep(2)
data = s.recv(4096)
print("Response: %d bytes" % len(data))
if data:
    print("Hex: %s" % data.hex()[:200])
else:
    print("No data")

# Try WebSocket upgrade
print("\n--- Trying WebSocket upgrade ---")
s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s2.settimeout(10)
s2.connect((host, port))
ws_upgrade = (
    "GET / HTTP/1.1\r\n"
    "Host: %s:%d\r\n"
    "Upgrade: websocket\r\n"
    "Connection: Upgrade\r\n"
    "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
    "Sec-WebSocket-Version: 13\r\n"
    "\r\n" % (host, port)
)
s2.send(ws_upgrade.encode())
time.sleep(2)
data2 = s2.recv(4096)
print("WS Response: %d bytes" % len(data2))
if data2:
    print("Text: %s" % data2.decode('utf-8', errors='replace')[:500])
s2.close()

s.close()
