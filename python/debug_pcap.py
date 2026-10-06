import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec
from derive_seed_from_nonce import derive_seed

pcap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'chat_capture.pcap')

with open(pcap_path, 'rb') as f:
    data = f.read()

# Parse SLL2 packets
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
    direction = 'S->C' if src_port == 3101 else 'C->S'
    packets.append({
        'ts': ts_sec + ts_usec/1000000.0,
        'dir': direction,
        'data': tcp_data,
    })

# Show first 20 packets with their raw bytes
print("=== First 20 packets ===")
for i, p in enumerate(packets[:20]):
    d = p['data']
    print("\nPkt %d [%s] len=%d: %s" % (i, p['dir'], len(d), d[:60].hex()))
    if len(d) > 2:
        # Try different frame interpretations
        # Option 1: [2-byte big-endian length][payload]
        fl1 = (d[0] << 8) | d[1]
        # Option 2: [1-byte type][varint length][payload]
        print("  2-byte-len=%d" % fl1)

# Show first 300 bytes of server stream
print("\n=== First 300 bytes server stream ===")
server_data = b''
for p in packets:
    if p['dir'] == 'S->C':
        server_data += p['data']
        if len(server_data) > 300:
            break

print(server_data[:300].hex())

# Try to find the greeting - it should start with a specific pattern
# From debug_connect2.py: greeting = b'\x00\x85\x62...\x00\x00'
# That starts with 0x00, 0x85 = 133
print("\n=== Looking for greeting pattern ===")
for i in range(min(20, len(packets))):
    d = packets[i]['data']
    if packets[i]['dir'] == 'S->C' and len(d) >= 19:
        # Check if this looks like a greeting (field1=0x00, field2=0x85)
        if d[0] == 0x00 and d[1] == 0x85:
            print("Pkt %d looks like greeting!" % i)
            print("Raw: %s" % d[:30].hex())
            break
    # Also check if it's length-prefixed
    if packets[i]['dir'] == 'S->C' and len(d) > 2:
        fl = (d[0] << 8) | d[1]
        if fl == 19 or fl == 21:
            print("Pkt %d: 2-byte len=%d, payload=%s" % (i, fl, d[2:2+fl].hex()))
