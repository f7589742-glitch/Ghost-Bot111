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
        'src_ip': src_ip, 'dst_ip': dst_ip,
        'src_port': src_port, 'dst_port': dst_port,
        'dir': 'S->C' if src_port == 3101 else 'C->S',
        'data': tcp_data,
    })

# Group by full 4-tuple (normalize: server side always port 3101)
conns = {}
for p in packets:
    if p['src_port'] == 3101:
        key = (p['src_ip'], p['src_port'], p['dst_ip'], p['dst_port'])
        s2c = True
    else:
        key = (p['dst_ip'], p['dst_port'], p['src_ip'], p['src_port'])
        s2c = False
    conn = conns.setdefault(key, {'key': key, 's2c': b'', 'c2s': b'', 'n': 0})
    if s2c:
        conn['s2c'] += p['data']
    else:
        conn['c2s'] += p['data']
    conn['n'] += 1

print("Connections found:")
for key, c in sorted(conns.items(), key=lambda x: -len(x[1]['s2c'])):
    print("  %s:%d -> %s:%d  S2C=%d C2S=%d packets=%d" % (key[0], key[1], key[2], key[3], len(c['s2c']), len(c['c2s']), c['n']))

# Find greeting in each connection
for key, c in conns.items():
    stream = c['s2c']
    greet_idx = stream.find(bytes.fromhex('08f24212'))
    if greet_idx >= 0:
        print("\n=== Connection %s:%d -> %s:%d has greeting at %d ===" % (key[0], key[1], key[2], key[3], greet_idx))
        # Check if greeting is at the START of stream (offset 0 or 2)
        if greet_idx <= 4:
            print("  Greeting is at the START of this connection!")
        prefix = stream[greet_idx-2:greet_idx]
        glen = (prefix[0] << 8) | prefix[1] if len(prefix) == 2 else 0
        print("  Frame length: %d" % glen)
        greet_payload = stream[greet_idx:greet_idx+glen]
        gf = ProtobufCodec.decode_message(greet_payload)
        f2 = gf.get(2, b'')
        sub = ProtobufCodec.decode_message(f2)
        sub1, sub2 = sub.get(1, 0), sub.get(2, 0)
        seed1, seed2 = derive_seed(sub1, sub2)
        c['seed1'], c['seed2'] = seed1, seed2
        c['greet_idx'] = greet_idx
        print("  seeds: tx=%d rx=%d" % (seed1, seed2))
