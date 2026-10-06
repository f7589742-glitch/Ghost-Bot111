import sys, os, json, zlib, socket, struct, threading

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

def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf

def main():
    sock = socket.create_connection((P["auth_server"], P["auth_port"]), timeout=10)
    print("connected", flush=True)

    hdr = recv_exact(sock, 2)
    glen = (hdr[0] << 8) | hdr[1]
    gp = recv_exact(sock, glen)
    gf = ProtobufCodec.decode_message(gp)
    sub = ProtobufCodec.decode_message(gf.get(2, b""))
    s1, s2 = sub.get(1, 0), sub.get(2, 0)
    sd1, sd2 = derive_seed(s1, s2)
    tx, rx = RokCrypto(sd1), RokCrypto(sd2)
    print("greeting seeds=%d/%d" % (sd1, sd2), flush=True)

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
    enc_login = tx.encrypt(ProtobufCodec.encode_message(login))
    sock.sendall(FrameParser.build_frame(enc_login))
    print("login sent", flush=True)

    frames = []
    sock.settimeout(10.0)
    stall = 0
    while len(frames) < 200:
        try:
            hdr2 = recv_exact(sock, 2)
            rl = (hdr2[0] << 8) | hdr2[1]
            rd = recv_exact(sock, rl)
            dec = rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            data = pf.get(2, b"")
            if op == 8003:
                ka = {1: 9, 2: ProtobufCodec.encode_message({1: 1})}
                enc_ka = tx.encrypt(ProtobufCodec.encode_message(ka))
                sock.sendall(FrameParser.build_frame(enc_ka))
                stall = 0
                continue
            frames.append((op, data))
            stall = 0
            print("  f%d op=%d" % (len(frames), op), flush=True)
        except socket.timeout:
            stall += 1
            if stall >= 1:
                break
            continue
        except Exception as e:
            print("  stop: %s" % e, flush=True)
            break

    sock.close()
    print("got %d frames" % len(frames), flush=True)
    if len(frames) == 0:
        print("NO FRAMES!", flush=True)
        return

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
    print("SAVED %d frames to game_dump.json" % len(D), flush=True)

    ops = {}
    for op, _ in frames:
        ops[op] = ops.get(op, 0) + 1
    for op, cnt in sorted(ops.items()):
        print("  op=%d cnt=%d" % (op, cnt), flush=True)

main()
