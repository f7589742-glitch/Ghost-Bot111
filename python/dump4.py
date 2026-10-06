import sys, os, json, zlib, socket, time

sys.path.insert(0, r"D:\aa\Headless Bot RoK\python")
from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

P = json.load(open(r"D:\aa\Headless Bot RoK\profiles\active.json"))

def _f(v):
    if isinstance(v, bytes):
        try: return {str(k): _f(sv) for k, sv in ProtobufCodec.decode_message(v).items()}
        except:
            try: return v.decode('utf-8')
            except: return "%dB" % len(v)
    return v

sock = socket.create_connection((P["auth_server"], P["auth_port"]), timeout=10)
hdr = b""
while len(hdr) < 2:
    hdr += sock.recv(2 - len(hdr))
gl = (hdr[0] << 8) | hdr[1]
gp = b""
while len(gp) < gl:
    gp += sock.recv(gl - len(gp))
gf = ProtobufCodec.decode_message(gp)
sub = ProtobufCodec.decode_message(gf.get(2, b""))
s1, s2 = sub.get(1, 0), sub.get(2, 0)
sd1, sd2 = derive_seed(s1, s2)
tx, rx = RokCrypto(sd1), RokCrypto(sd2)
print("greeting ok seeds=%d/%d" % (sd1, sd2), flush=True)

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
print("login sent", flush=True)

frames = []
sock.setblocking(False)
end_time = time.time() + 20
buf = b""

while time.time() < end_time and len(frames) < 200:
    try:
        chunk = sock.recv(65536)
        if chunk:
            buf += chunk
    except BlockingIOError:
        time.sleep(0.05)
        continue

    while len(buf) >= 2:
        fl = (buf[0] << 8) | buf[1]
        if len(buf) < 2 + fl:
            break
        frame_data = buf[2:2+fl]
        buf = buf[2+fl:]
        try:
            dec = rx.decrypt(frame_data)
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            data = pf.get(2, b"")
            if op == 8003:
                ka = {1: 9, 2: ProtobufCodec.encode_message({1: 1})}
                sock.sendall(FrameParser.build_frame(tx.encrypt(ProtobufCodec.encode_message(ka))))
                continue
            frames.append((op, data))
            print("  f%d op=%d" % (len(frames), op), flush=True)
        except:
            pass

sock.close()
print("\nGot %d frames" % len(frames), flush=True)

D = []
for idx, (op, data) in enumerate(frames):
    e = {"i": idx, "op": op}
    if isinstance(data, bytes) and len(data) > 0:
        if op == 9999:
            try:
                dc = zlib.decompress(data)
                inner = ProtobufCodec.decode_message(dc)
                e["z"] = len(dc)
                e["d"] = {str(k): _f(v) for k, v in inner.items()}
            except:
                e["r"] = data.hex()
        else:
            try:
                inner = ProtobufCodec.decode_message(data)
                e["d"] = {str(k): _f(v) for k, v in inner.items()}
            except:
                e["r"] = data.hex()[:200]
    D.append(e)

fp = r"D:\aa\Headless Bot RoK\game_dump.json"
with open(fp, 'w') as fo:
    json.dump(D, fo, indent=2, default=str, ensure_ascii=False)
print("SAVED %d frames" % len(D), flush=True)

ops = {}
for op, _ in frames:
    ops[op] = ops.get(op, 0) + 1
for op, cnt in sorted(ops.items()):
    print("  op=%d cnt=%d" % (op, cnt), flush=True)
