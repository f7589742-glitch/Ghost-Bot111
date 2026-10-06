import struct, os
syspath = os.path.join(os.path.dirname(os.path.abspath(__file__)))
import sys; sys.path.insert(0, syspath)

PCAP = os.path.join(syspath, '..', 'game_capture.pcap')
with open(PCAP, 'rb') as f:
    data = f.read()

offset = 24
packets = []
while offset < len(data):
    if offset + 16 > len(data): break
    ts_sec, ts_usec, incl_len, orig_len = struct.unpack('<IIII', data[offset:offset+16])
    offset += 16
    pkt = data[offset:offset+incl_len]
    offset += incl_len
    if len(pkt) < 20: continue
    if struct.unpack('>H', pkt[0:2])[0] != 0x0800: continue
    ip_header = pkt[20:]
    if ip_header[9] != 6: continue
    tcp_start = 20 + (ip_header[0] & 0x0F) * 4
    tcp_header = pkt[tcp_start:]
    src_port = struct.unpack('>H', tcp_header[0:2])[0]
    dst_port = struct.unpack('>H', tcp_header[2:4])[0]
    doff = ((tcp_header[12] >> 4) & 0xF) * 4
    tcp_data = tcp_header[doff:]
    if len(tcp_data) == 0: continue
    packets.append({'dir': 'S->C' if src_port == 3101 else 'C->S',
                    'cport': dst_port if src_port == 3101 else src_port,
                    'data': tcp_data, 'ts': ts_sec + ts_usec / 1e6})

streams = {}
for p in packets:
    key = (p['cport'], p['dir'])
    streams.setdefault(key, b'')
    streams[key] += p['data']

for (cport, d), st in sorted(streams.items()):
    print("port %s %s: %d bytes" % (cport, d, len(st)))
    print("  first: %s" % st[:64].hex())
    print("  last:  %s" % st[-32:].hex())
