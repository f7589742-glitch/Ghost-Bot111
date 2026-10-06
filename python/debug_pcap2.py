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

# Frame format: [type:1][varint length][encrypted payload]
# type 0x00 = greeting/control, 0x01 = server data, 0x02 = client data
def read_varint(data, offset):
    result = 0
    shift = 0
    while offset < len(data):
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, offset

# First find the greeting - it should be type 0x00
# The greeting is NOT encrypted - it contains the nonce
print("=== Looking for greeting (type 0x00) ===")
greeting_found = False
for i, p in enumerate(packets[:30]):
    if p['dir'] != 'S->C':
        continue
    d = p['data']
    if len(d) < 2:
        continue
    frame_type = d[0]
    payload_len, pos = read_varint(d, 1)
    if frame_type == 0x00 and payload_len > 5:
        print("Pkt %d: type=0x%02x len=%d" % (i, frame_type, payload_len))
        payload = d[pos:pos+payload_len]
        print("Payload (%d bytes): %s" % (len(payload), payload.hex()))
        
        # Parse greeting protobuf
        fields = ProtobufCodec.decode_message(payload)
        print("Greeting fields: %s" % {k: v if not isinstance(v, bytes) else "(%dB) %s" % (len(v), v[:20].hex()) for k, v in fields.items()})
        
        # Extract nonce from field 2
        field2 = fields.get(2, b'')
        if isinstance(field2, bytes) and len(field2) > 0:
            sub = ProtobufCodec.decode_message(field2)
            print("Field2 sub: %s" % sub)
            sub1 = sub.get(1, 0)
            sub2 = sub.get(2, 0)
            print("Sub1=%d sub2=%d" % (sub1, sub2))
            seed1, seed2 = derive_seed(sub1, sub2)
            print("Seed1=%d seed2=%d" % (seed1, seed2))
            greeting_found = True
            greeting_idx = i
            break

if not greeting_found:
    print("No greeting found in first 30 packets!")
    # Show all server frame types
    print("\nAll server frames:")
    for i, p in enumerate(packets[:50]):
        if p['dir'] != 'S->C':
            continue
        d = p['data']
        if len(d) < 2:
            continue
        frame_type = d[0]
        payload_len, pos = read_varint(d, 1)
        print("Pkt %d: type=0x%02x len=%d data=%s" % (i, frame_type, payload_len, d[pos:pos+20].hex()))
