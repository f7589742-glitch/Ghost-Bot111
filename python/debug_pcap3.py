import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import FrameParser, ProtobufCodec
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

# Feed all S->C data to FrameParser
server_parser = FrameParser()
for p in packets:
    if p['dir'] == 'S->C':
        server_parser.add_data(p['data'])

# Feed all C->S data to another FrameParser
client_parser = FrameParser()
for p in packets:
    if p['dir'] == 'C->S':
        client_parser.add_data(p['data'])

# Extract all frames
server_frames = []
while True:
    f = server_parser.get_frame()
    if f is None:
        break
    server_frames.append(f)

client_frames = []
while True:
    f = client_parser.get_frame()
    if f is None:
        break
    client_frames.append(f)

print("Server frames: %d" % len(server_frames))
print("Client frames: %d" % len(client_frames))

# Show first 10 server frames
print("\n=== First 15 server frames ===")
for i, (frame_type, payload) in enumerate(server_frames[:15]):
    print("Frame %d: type=0x%02x len=%d hex=%s" % (i, frame_type, len(payload), payload[:40].hex()))
    if frame_type == 0x00 and len(payload) >= 15:
        # This might be the greeting
        fields = ProtobufCodec.decode_message(payload)
        print("  Fields: %s" % {k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in fields.items()})

# Show first 10 client frames
print("\n=== First 10 client frames ===")
for i, (frame_type, payload) in enumerate(client_frames[:10]):
    print("Frame %d: type=0x%02x len=%d hex=%s" % (i, frame_type, len(payload), payload[:40].hex()))
