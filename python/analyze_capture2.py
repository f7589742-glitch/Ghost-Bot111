import struct, sys, os, zlib, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec
from derive_seed_from_nonce import derive_seed

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
    proto_type = struct.unpack('>H', pkt[0:2])[0]
    if proto_type != 0x0800:
        continue
    ip_start = 20
    if ip_start + 20 > len(pkt):
        continue
    ip_header = pkt[ip_start:]
    ihl = (ip_header[0] & 0x0F) * 4
    protocol = ip_header[9]
    if protocol != 6:
        continue
    src_ip = '.'.join(str(b) for b in ip_header[12:16])
    dst_ip = '.'.join(str(b) for b in ip_header[16:20])
    tcp_start = ip_start + ihl
    if tcp_start + 20 > len(pkt):
        continue
    tcp_header = pkt[tcp_start:]
    src_port = struct.unpack('>H', tcp_header[0:2])[0]
    dst_port = struct.unpack('>H', tcp_header[2:4])[0]
    doff = ((tcp_header[12] >> 4) & 0xF) * 4
    tcp_data = tcp_header[doff:]
    if len(tcp_data) == 0:
        continue
    if src_port != 3101 and dst_port != 3101:
        continue
    packets.append({
        'ts': ts_sec + ts_usec/1000000.0,
        'src_ip': src_ip, 'dst_ip': dst_ip,
        'src_port': src_port, 'dst_port': dst_port,
        'dir': 'S->C' if src_port == 3101 else 'C->S',
        'data': tcp_data,
    })

print("Total packets: %d" % len(packets))

# Group by connection (server side = port 3101, find unique server IPs)
conns = {}
for p in packets:
    server_ip = p['src_ip'] if p['src_port'] == 3101 else p['dst_ip']
    key = server_ip
    conns.setdefault(key, {'ip': server_ip, 's2c': b'', 'c2s': b'', 'n': 0})
    if p['dir'] == 'S->C':
        conns[key]['s2c'] += p['data']
    else:
        conns[key]['c2s'] += p['data']
    conns[key]['n'] += 1

for key, c in conns.items():
    print("Server %s: %d packets, S2C=%d bytes, C2S=%d bytes" % (c['ip'], c['n'], len(c['s2c']), len(c['c2s'])))

# Try each connection: find greeting (field1=8562)
for key, c in conns.items():
    stream = c['s2c']
    pos = 0
    frame_num = 0
    while pos + 2 <= len(stream) and frame_num < 30:
        fl = (stream[pos] << 8) | stream[pos+1]
        if fl == 0 or pos + 2 + fl > len(stream):
            break
        payload = stream[pos+2:pos+2+fl]
        pos += 2 + fl
        frame_num += 1
        try:
            fields = ProtobufCodec.decode_message(payload)
            if fields.get(1) == 8562:
                print("\nGREETING found in conn %s frame %d (len=%d): %s" % (c['ip'], frame_num, fl, payload.hex()))
                f2 = fields.get(2, b'')
                sub = ProtobufCodec.decode_message(f2)
                sub1, sub2 = sub.get(1, 0), sub.get(2, 0)
                print("sub1=%d sub2=%d" % (sub1, sub2))
                seed1, seed2 = derive_seed(sub1, sub2)
                print("seed1=%d seed2=%d" % (seed1, seed2))
                c['seed1'] = seed1
                c['seed2'] = seed2
                c['greeting_frame'] = frame_num
                c['greeting_pos'] = 2 + fl  # position after greeting
                break
        except:
            pass
