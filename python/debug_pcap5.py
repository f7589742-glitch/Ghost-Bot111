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

# The frame format is [2-byte length][payload]
# But wait - the first byte might be a TYPE byte!
# Look at the patterns:
# 00 = control frames (short)
# 02 = data frames (long)
# This matches the headless_client.py doc: type 0x00 control, 0x02 client data

# Actually let's check: does the "type" byte sit BEFORE or INSIDE the 2-byte length?
# From FrameParser: length = (buffer[0] << 8) | buffer[1]
# So format is [2-byte len][payload]
# But first packet is: 00 da 51 66...
# 00 da = 218 = length, payload starts with 51 66...
# And packet 6 is: 02 59 6f 35...
# 02 59 = 601 = length, payload starts with 6f 35...

# The type IS the first byte of the 2-byte length! That means:
# type 0x00 = high byte 0x00 (length < 256)
# type 0x02 = high byte 0x02 (length >= 256)
# That's just length encoding, not a type!

# OR maybe the format is actually [1-byte type][1-byte length][payload]?
# Let's check: 
# Packet 0: type=0x00, len=0xda=218, payload=51660b19...
# Packet 6: type=0x02, len=0x59=89, payload=6f35585f...
# But packet 6 is 603 bytes long, and if payload is only 89 bytes that doesn't match!

# Actually packet 6 raw is 603 bytes. So [1-byte type][1-byte len] doesn't work for length > 255.

# Let me look at the actual protocol from the game more carefully.
# The debug_connect2.py file shows the greeting handling.
# Let me read it.

print("=== Looking for greeting patterns ===")
# The greeting should start with 0x00 0x85 0x62 (from debug_connect2.py)
# Let's scan ALL server data for this pattern
server_raw = b''
for p in packets:
    if p['dir'] == 'S->C':
        server_raw += p['data']

# Search for 00 85 62 in the raw data (greeting pattern from debug_connect2.py)
greeting_pos = server_raw.find(b'\x00\x85\x62')
if greeting_pos >= 0:
    print("Found greeting pattern at offset %d" % greeting_pos)
    print("Bytes: %s" % server_raw[greeting_pos:greeting_pos+30].hex())
else:
    print("No 00 85 62 pattern found")
    
    # Try to decode frame 0's payload as protobuf
    # Frame 0: len=218, payload starts at offset 2
    payload0 = server_raw[2:2+218]
    print("\nFrame 0 payload (218 bytes): %s" % payload0[:30].hex())
    fields0 = ProtobufCodec.decode_message(payload0)
    print("Frame 0 fields: %s" % fields0)

# Maybe the greeting is in the CLIENT first packet?
# Client pkt 1: len=6, 00046fd09a8d
# [2-byte len=4][4-byte payload]
client_raw = b''
for p in packets:
    if p['dir'] == 'C->S':
        client_raw += p['data']

# First client frame: len=4, payload = 6fd09a8d
print("\nFirst client frame: %s" % client_raw[:6].hex())
payload_c0 = client_raw[2:2+4]
print("Client frame 0 payload: %s" % payload_c0.hex())
fields_c0 = ProtobufCodec.decode_message(payload_c0)
print("Client frame 0 fields: %s" % fields_c0)

# Second client frame starts at offset 6
# Client pkt 2: len=75, 00499fae...
c_len1 = (client_raw[6] << 8) | client_raw[7]
print("\nClient frame 1: len=%d" % c_len1)
c_payload1 = client_raw[8:8+c_len1]
print("Client frame 1 payload (%d bytes): %s" % (len(c_payload1), c_payload1[:40].hex()))
fields_c1 = ProtobufCodec.decode_message(c_payload1)
print("Client frame 1 fields: %s" % {k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in fields_c1.items()})

# Try using known seeds from teez9334 profile (which was used for this capture)
import json
profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
if os.path.exists(profile_path):
    with open(profile_path) as f:
        profile = json.load(f)
    print("\nProfile: %s" % {k: v[:50] if isinstance(v, str) and len(v) > 50 else v for k, v in profile.items()})
