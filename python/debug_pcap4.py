import struct, sys, os

pcap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'chat_capture.pcap')

with open(pcap_path, 'rb') as f:
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
    ip_header = pkt[ip_start:]
    ihl = (ip_header[0] & 0x0F) * 4
    protocol = ip_header[9]
    if protocol != 6:
        continue
    tcp_start = ip_start + ihl
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
    packets.append({'dir': direction, 'data': tcp_data})

# Show first 15 server packets
print("=== First 15 S->C raw TCP payloads ===")
count = 0
for p in packets:
    if p['dir'] != 'S->C':
        continue
    count += 1
    if count > 15:
        break
    d = p['data']
    print("S %3d: len=%3d first10=%s" % (count, len(d), d[:10].hex()))

# Show first 5 C->S raw TCP payloads
print("\n=== First 5 C->S raw TCP payloads ===")
count = 0
for p in packets:
    if p['dir'] != 'C->S':
        continue
    count += 1
    if count > 5:
        break
    d = p['data']
    print("C %3d: len=%3d first10=%s" % (count, len(d), d[:10].hex()))

# Concatenate ALL S->C data and ALL C->S data
server_raw = b''
client_raw = b''
for p in packets:
    if p['dir'] == 'S->C':
        server_raw += p['data']
    else:
        client_raw += p['data']

print("\nServer raw total: %d bytes" % len(server_raw))
print("Client raw total: %d bytes" % len(client_raw))

# The wire format is [2-byte big-endian length][payload]
# Let's manually parse the server stream
print("\n=== Parsing server stream with [2-byte length][payload] format ===")
pos = 0
frame_num = 0
while pos < len(server_raw) and frame_num < 20:
    if pos + 2 > len(server_raw):
        print("  Truncated at pos %d" % pos)
        break
    length = (server_raw[pos] << 8) | server_raw[pos+1]
    if length == 0:
        print("  Zero length at pos %d: %s" % (pos, server_raw[pos:pos+10].hex()))
        break
    total = 2 + length
    if pos + total > len(server_raw):
        print("  Frame %d: len=%d but only %d bytes remain" % (frame_num, length, len(server_raw)-pos))
        break
    payload = server_raw[pos+2:pos+total]
    print("Frame %d: len=%d payload_hex=%s" % (frame_num, length, payload[:40].hex()))
    pos += total
    frame_num += 1
