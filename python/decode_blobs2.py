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
        'dir': 'S->C' if src_port == 3101 else 'C->S',
        'cport': dst_port if src_port == 3101 else src_port,
        'data': tcp_data,
    })

crypto_rx = RokCrypto(851565604)
s2c_data = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'S->C':
        s2c_data += p['data']

spos = 19
sframe = 0
blobs = []
while spos + 2 <= len(s2c_data):
    fl = (s2c_data[spos] << 8) | s2c_data[spos+1]
    if fl == 0 or spos + 2 + fl > len(s2c_data):
        break
    payload = s2c_data[spos+2:spos+2+fl]
    spos += 2 + fl
    sframe += 1
    try:
        dec = crypto_rx.decrypt(payload)
        pf = ProtobufCodec.decode_message(dec)
        op = pf.get(1, 0)
        if op != 61438:
            continue
        dataf = pf.get(2, b'')
        outer = ProtobufCodec.decode_message(dataf)
        dc = zlib.decompress(outer[2])
        inner = ProtobufCodec.decode_message(dc)
        blobs.append((sframe, inner[2]))
    except Exception as e:
        pass

print("Blobs: %d" % len(blobs))
for sframe, blob in blobs:
    # parse top-level entries: field 1 repeated
    entries = []
    pos = 0
    try:
        inner = ProtobufCodec.decode_message(blob)
    except:
        continue
    if 1 not in inner or not isinstance(inner[1], list):
        print("S f%-4d blob %6dB: top-level f1=%s f2=%s" % (sframe, len(blob), type(inner.get(1)).__name__, type(inner.get(2)).__name__))
        continue
    for e in inner[1]:
        try:
            ie = ProtobufCodec.decode_message(e)
            first_str = None
            for k in sorted(ie.keys()):
                v = ie[k]
                if isinstance(v, bytes):
                    try:
                        s = v.decode('ascii')
                        if all(32 <= ord(c) < 127 for c in s):
                            first_str = (k, s[:30])
                            break
                    except:
                        pass
            entries.append((sorted(ie.keys()), first_str))
        except:
            entries.append(('?', None))
    print("S f%-4d blob %6dB: %d entries: %s" % (sframe, len(blob), len(entries), "; ".join("f%s%s" % (k, "=" + str(fs) if fs else "") for k, fs in entries[:20])))

# Deep-dive S f148 (map movement blob): check for float32 positions
sframe, blob = blobs[3]
print("\n=== S f%d blob detailed ===" % sframe)
inner = ProtobufCodec.decode_message(blob)
for k, v in sorted(inner.items()):
    if isinstance(v, list):
        print("f%d: list[%d]" % (k, len(v)))
        for i, e in enumerate(v[:3]):
            try:
                ie = ProtobufCodec.decode_message(e)
                print("  [%d] %s" % (i, str({kk: (vv.hex() if isinstance(vv, bytes) and len(vv) <= 60 else (len(vv) if isinstance(vv, bytes) else vv)) for kk, vv in sorted(ie.items())})[:300]))
            except:
                print("  [%d] raw %s" % (i, e.hex()[:120]))
    elif isinstance(v, bytes):
        print("f%d: %dB" % (k, len(v)))
    else:
        print("f%d: %s" % (k, v))
