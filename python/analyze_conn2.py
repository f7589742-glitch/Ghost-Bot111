import struct, sys, os, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec

PCAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'game_capture.pcap')

with open(PCAP, 'rb') as f:
    data = f.read()

offset = 24
packets = []
while offset < len(data):
    if offset + 16 > len(data):
        break
    ts_sec, ts_usec, incl_len, orig_len = struct.unpack('<IIII', data[offset:offset+16])
    offset += 16
    pkt = data[offset:offset+incl_len]
    offset += incl_len
    if len(pkt) < 20:
        continue
    if struct.unpack('>H', pkt[0:2])[0] != 0x0800:
        continue
    ip_start = 20
    if ip_start + 20 > len(pkt):
        continue
    ip_header = pkt[ip_start:]
    ihl = (ip_header[0] & 0x0F) * 4
    if ip_header[9] != 6:
        continue
    tcp_start = ip_start + ihl
    if tcp_start + 20 > len(pkt):
        continue
    tcp_header = pkt[tcp_start:]
    src_port = struct.unpack('>H', tcp_header[0:2])[0]
    dst_port = struct.unpack('>H', tcp_header[2:4])[0]
    doff = ((tcp_header[12] >> 4) & 0xF) * 4
    tcp_data = tcp_header[doff:]
    if len(tcp_data) == 0 or (src_port != 3101 and dst_port != 3101):
        continue
    packets.append({
        'ts': ts_sec + ts_usec / 1e6,
        'dir': 'S->C' if src_port == 3101 else 'C->S',
        'cport': dst_port if src_port == 3101 else src_port,
        'data': tcp_data,
    })

# Decrypt second connection (port 38574)
conn2_c2s = b''
conn2_s2c = b''
for p in packets:
    if p['cport'] == 38574:
        if p['dir'] == 'C->S':
            conn2_c2s += p['data']
        else:
            conn2_s2c += p['data']

print("=== CONNECTION 2 (38574): C2S=%d S2C=%d ===" % (len(conn2_c2s), len(conn2_s2c)))

# Try decryption with the same seeds (they might share seeds)
def try_decrypt(stream, crypto, label):
    pos = 0
    fnum = 0
    results = []
    while pos + 2 <= len(stream):
        fl = (stream[pos] << 8) | stream[pos+1]
        if fl == 0 or pos + 2 + fl > len(stream):
            break
        payload = stream[pos+2:pos+2+fl]
        pos += 2 + fl
        fnum += 1
        try:
            dec = crypto.decrypt(payload)
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            data = pf.get(2, b'')
            info = ""
            if isinstance(data, bytes) and len(data) > 0:
                try:
                    inner = ProtobufCodec.decode_message(data)
                    info = str({k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})[:150]
                except:
                    info = data.hex()[:60]
            results.append((op, info))
        except Exception as e:
            results.append((None, "FAIL:%s" % str(e)[:20]))
    return results

for seed_tx, seed_rx, name in [(135717691, 851565604, "main-seeds"), (851565604, 135717691, "swapped-seeds")]:
    print("\n-- conn2 with %s --" % name)
    c = try_decrypt(conn2_c2s, RokCrypto(seed_tx), "C")
    for i, (op, info) in enumerate(c):
        if op is not None and op != 9:
            print("  C f%d op=%-5d %s" % (i+1, op, info))
        elif op is None:
            print("  C f%d %s" % (i+1, info))
    if len(c) == 0:
        print("  (no C2S frames)")
    s = try_decrypt(conn2_s2c, RokCrypto(seed_rx), "S")
    for i, (op, info) in enumerate(s):
        if op is not None and op not in (8003,):
            print("  S f%d op=%-5d %s" % (i+1, op, info))
        elif op is None:
            print("  S f%d %s" % (i+1, info))
    if len(s) == 0:
        print("  (no S2C frames)")

# Now correlate main connection: server response to each client op
print("\n=== MAIN CONN: server frames with op+1 matching ===")
main_s2c = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'S->C':
        main_s2c += p['data']

# Server frames, skipping greeting (19 bytes) and keepalive
spos = 19
sframe = 0
crypto_rx = RokCrypto(851565604)
server_ops = []
while spos + 2 <= len(main_s2c):
    fl = (main_s2c[spos] << 8) | main_s2c[spos+1]
    if fl == 0 or spos + 2 + fl > len(main_s2c):
        break
    payload = main_s2c[spos+2:spos+2+fl]
    spos += 2 + fl
    sframe += 1
    try:
        dec = crypto_rx.decrypt(payload)
        pf = ProtobufCodec.decode_message(dec)
        op = pf.get(1, 0)
        if op == 8003:
            continue
        data = pf.get(2, b'')
        if op in (105, 106, 301, 302, 1013, 1014, 205, 206, 1005, 1006, 1203, 1204, 102, 103, 1):
            info = ""
            if isinstance(data, bytes) and len(data) > 0:
                try:
                    inner = ProtobufCodec.decode_message(data)
                    info = str({k: (len(v) if isinstance(v, bytes) else v) for k, v in inner.items()})[:180]
                except:
                    info = data.hex()[:80]
            print("S f%-4d op=%-5d len=%-4d %s" % (sframe, op, len(data) if isinstance(data, bytes) else 0, info))
        server_ops.append((sframe, op))
    except:
        pass

# Server opcode frequency
print("\n=== SERVER OPCODE FREQUENCY ===")
from collections import Counter
cnt = Counter(op for _, op in server_ops)
for op, n in sorted(cnt.items()):
    print("  op=%-6d x%d" % (op, n))
