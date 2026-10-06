import struct, sys, os, zlib
from collections import Counter
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

sframe, blob = blobs[3]
inner = ProtobufCodec.decode_message(blob)
entries = inner[1]

types = Counter()
samples = {}
for e in entries:
    try:
        ie = ProtobufCodec.decode_message(e)
        t = ie.get(3)
        types[t] += 1
        if t not in samples:
            samples[t] = e.hex()
    except:
        pass

print("S f%d: %d entries" % (sframe, len(entries)))
for t, cnt in sorted(types.items(), key=lambda kv: (kv[0] is None, kv[0])):
    print("  type=%-6s x%-5d sample: %s" % (t, cnt, samples[t][:70]))

# node position bytes: 0d ca 64 dd 45 15 a8 1f f7 43
pos_bytes = bytes.fromhex('0dca64dd4515a81ff743')
print("\nnode pos (0dca64dd4515a81ff743) found: %s" % (pos_bytes in blob))
# node id 4138906 varint: 9a cf fc 01
print("node id varint found: %s" % (b'\x9a\xcf\xfc\x01' in blob))

# Where is the player's city? Search the OTHER blobs for player id
# city position from profile: f13 {1: "0-0-0"...} no. Use march positions:
# player city ~ (1172130217, 1140721555) = 0x45dda949 = 7092.4, 0x43d57e0d = 427.5?
x = struct.unpack('<f', struct.pack('<I', 1172130217))[0]
y = struct.unpack('<f', struct.pack('<I', 1140721555))[0]
print("\nplayer city float pos: (%.1f, %.1f)" % (x, y))

# search all blobs for city pos
for sf, blob in blobs:
    for pb in [bytes.fromhex('0da949dd4515'), bytes.fromhex('0dca64dd4515')]:
        if pb in blob:
            print("S f%d: pos prefix %s found" % (sf, pb.hex()))
