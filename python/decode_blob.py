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

# Get the first 61438 blob
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
    except:
        continue
    pf = ProtobufCodec.decode_message(dec)
    op = pf.get(1, 0)
    if op != 61438:
        continue
    dataf = pf.get(2, b'')
    outer = ProtobufCodec.decode_message(dataf)
    dc = zlib.decompress(outer[2])
    inner = ProtobufCodec.decode_message(dc)
    blob = inner[2]
    blobs.append((sframe, blob))

# Examine blob structure
sframe, blob = blobs[0]
print("Blob from S f%d: %d bytes" % (sframe, len(blob)))
print("First 64 bytes: %s" % blob[:64].hex())
print("Last 32 bytes: %s" % blob[-32:].hex())

# Check byte frequency / entropy
from collections import Counter
c = Counter(blob)
print("Distinct byte values: %d" % len(c))
print("Most common: %s" % c.most_common(8))

# Try RokCrypto decrypt of blob (both seeds)
for name, seed in [("rx", 851565604), ("tx", 135717691)]:
    try:
        cr = RokCrypto(seed)
        d = cr.decrypt(blob)
        print("%s decrypt -> %d bytes, first 32: %s" % (name, len(d), d[:32].hex()))
    except Exception as e:
        print("%s decrypt fail: %s" % (name, e))

# Search for known entity id 232018498 (player) varint: c2 a4 d1 6e
print("\nplayer id 232018498 (c2a4d16e) in blob: %s" % (b'\xc2\xa4\xd1\x6e' in blob))
# node 4138906 = 9a cf fc 01
print("node 4138906 (9acffc01) in blob: %s" % (b'\x9a\xcf\xfc\x01' in blob))
# check if blob has 0x78 0x9c (zlib) or 0x1f 0x8b (gzip) or 0x9c (raw deflate)
print("zlib header: %s, gzip: %s" % (b'\x78\x9c' in blob[:50], b'\x1f\x8b' in blob[:50]))
# Check for repeated structure: count occurrences of 08 22 (field1=34 varint?)
print("\noccurrences of '1002' (field2=1): %d" % blob.count(b'\x10\x02'))

# Try to find "map" structure: look for string markers
for s in [b'map', b'entity', b'node', b'resource', b'1,', b'|']:
    print("'%s' count: %d" % (s, blob.count(s)))

# dump a section around any occurrence of 9acffc01 (node id)
idx = blob.find(b'\x9a\xcf\xfc\x01')
if idx >= 0:
    print("node context: %s" % blob[max(0,idx-120):idx+120].hex())
