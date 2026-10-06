import struct, os, zlib
syspath = os.path.join(os.path.dirname(os.path.abspath(__file__)))
import sys; sys.path.insert(0, syspath)
from crypto_module import RokCrypto
from headless_client import ProtobufCodec
from derive_seed_from_nonce import derive_seed

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

# Second connection (38574) - extract per-direction streams
s2c2 = b''
c2s2 = b''
for p in packets:
    if p['cport'] == 38574:
        if p['dir'] == 'S->C':
            s2c2 += p['data']
        else:
            c2s2 += p['data']

print("second conn: S2C=%d bytes, C2S=%d bytes" % (len(s2c2), len(c2s2)))
print("S2C first 40 bytes: %s" % s2c2[:40].hex())
print("C2S first 40 bytes: %s" % c2s2[:40].hex())

# parse first server frame (greeting)
def parse_frames(stream, start):
    spos = start
    n = 0
    frames = []
    while spos + 2 <= len(stream):
        fl = (stream[spos] << 8) | stream[spos+1]
        if fl == 0 or spos + 2 + fl > len(stream):
            break
        frames.append(stream[spos+2:spos+2+fl])
        spos += 2 + fl
        n += 1
        if n >= 20:
            break
    return frames

sf2 = parse_frames(s2c2, 0)
print("second conn server frames (first 20):")
for i, fr in enumerate(sf2):
    print("  f%d len=%d: %s" % (i, len(fr), fr.hex()[:80]))

cf2 = parse_frames(c2s2, 0)
print("second conn client frames (first 20):")
for i, fr in enumerate(cf2):
    print("  f%d len=%d: %s" % (i, len(fr), fr.hex()[:80]))
