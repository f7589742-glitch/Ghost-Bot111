import sys, os, json, zlib, socket, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

P = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'active.json')))

def _f(v):
    if isinstance(v, bytes):
        try: return {str(k): _f(sv) for k, sv in ProtobufCodec.decode_message(v).items()}
        except:
            try: return v.decode('utf-8')
            except: return "(%dB)" % len(v)
    return v

def recv_loop(sock, tx, rx, frames, buf, deadline):
    while time.time() < deadline:
        try:
            chunk = sock.recv(65536)
            if chunk:
                buf += chunk
        except:
            time.sleep(0.05)
            continue
        while len(buf) >= 2:
            fl = (buf[0] << 8) | buf[1]
            if len(buf) < 2 + fl:
                break
            fd = buf[2:2+fl]
            buf = buf[2+fl:]
            try:
                dec = rx.decrypt(fd)
                pf = ProtobufCodec.decode_message(dec)
                op = pf.get(1, 0)
                data = pf.get(2, b"")
                if op == 8003:
                    ka = {1: 9, 2: ProtobufCodec.encode_message({1: 1})}
                    sock.sendall(FrameParser.build_frame(tx.encrypt(ProtobufCodec.encode_message(ka))))
                    continue
                frames.append((op, data, time.time()))
            except:
                pass
    return buf

def send_cmd(sock, tx, opcode, payload=b""):
    msg = {1: opcode}
    if payload:
        msg[2] = payload
    sock.sendall(FrameParser.build_frame(tx.encrypt(ProtobufCodec.encode_message(msg))))

def decode_frames(frames):
    D = []
    for idx, (op, data, ts) in enumerate(frames):
        e = {"i": idx, "op": op, "t": "%.1f" % ts}
        if isinstance(data, bytes) and len(data) > 0:
            if op == 9999:
                try:
                    outer = ProtobufCodec.decode_message(data)
                    if 2 in outer and isinstance(outer[2], bytes) and outer[2][:2] == b'\x78\x9c':
                        dc = zlib.decompress(outer[2])
                        inner = ProtobufCodec.decode_message(dc)
                        e["z"] = len(dc)
                        e["d"] = {str(k): _f(v) for k, v in inner.items()}
                    else:
                        e["d"] = {str(k): _f(v) for k, v in outer.items()}
                except:
                    e["r"] = data.hex()[:200]
            else:
                try:
                    inner = ProtobufCodec.decode_message(data)
                    e["d"] = {str(k): _f(v) for k, v in inner.items()}
                except:
                    e["r"] = data.hex()[:200]
        D.append(e)
    return D

# Connect
sock = socket.create_connection((P["auth_server"], P["auth_port"]), timeout=10)
hdr = b""
while len(hdr) < 2: hdr += sock.recv(2 - len(hdr))
gl = (hdr[0] << 8) | hdr[1]
gp = b""
while len(gp) < gl: gp += sock.recv(gl - len(gp))
gf = ProtobufCodec.decode_message(gp)
sub = ProtobufCodec.decode_message(gf.get(2, b""))
s1, s2 = sub.get(1, 0), sub.get(2, 0)
sd1, sd2 = derive_seed(s1, s2)
tx, rx = RokCrypto(sd1), RokCrypto(sd2)

login = {1: 14, 2: ProtobufCodec.encode_message({
    1: 1, 9: 1,
    4: ProtobufCodec.encode_message({6: P["app_uid"].encode()}),
    7: ProtobufCodec.encode_message({
        1: P["app_uid"].encode(),
        2: P["access_token"].encode(),
        3: P["server_id"],
        4: b"android", 5: 1,
    }),
})}
sock.sendall(FrameParser.build_frame(tx.encrypt(ProtobufCodec.encode_message(login))))
sock.setblocking(False)

# Phase 1: Initial data
frames = []
buf = b""
buf = recv_loop(sock, tx, rx, frames, buf, time.time() + 15)
print("Phase 1: %d frames" % len(frames))

# Phase 2: Request entity data
print("Phase 2: Requesting entity data...")

# Request player info (opcode 11 - entity query)
for ent_type in [1, 2, 3, 4, 5, 10, 66, 125]:
    for eid in range(1, 20):
        send_cmd(sock, tx, 11, ProtobufCodec.encode_message({
            2: ProtobufCodec.encode_message({1: ent_type, 2: eid})
        }))
        time.sleep(0.02)

# Request resources (opcode 120)
send_cmd(sock, tx, 120, ProtobufCodec.encode_message({1: "66"}))

# Player state
send_cmd(sock, tx, 925, ProtobufCodec.encode_message({1: 1}))

# Timers
send_cmd(sock, tx, 306, ProtobufCodec.encode_message({1: "74"}))
send_cmd(sock, tx, 300, ProtobufCodec.encode_message({1: "74", 3: 1200}))

# Status
send_cmd(sock, tx, 120, ProtobufCodec.encode_message({1: "66"}))

buf = recv_loop(sock, tx, rx, frames, buf, time.time() + 15)
print("Phase 2: %d total frames" % len(frames))

sock.close()

# Decode and save
D = decode_frames(frames)
fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'game_dump.json')
with open(fp, 'w') as f:
    json.dump(D, f, indent=2, default=str, ensure_ascii=False)
print("SAVED %d frames" % len(D))

ops = {}
for op, _, _ in frames:
    ops[op] = ops.get(op, 0) + 1
for op, cnt in sorted(ops.items()):
    print("  op=%d cnt=%d" % (op, cnt))
