import struct, os
syspath = os.path.join(os.path.dirname(os.path.abspath(__file__)))
import sys; sys.path.insert(0, syspath)
from crypto_module import RokCrypto
from headless_client import ProtobufCodec

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
                    'data': tcp_data})

def parse_frames(stream, start):
    frames = []
    spos = start
    while spos + 2 <= len(stream):
        fl = (stream[spos] << 8) | stream[spos+1]
        if fl == 0 or spos + 2 + fl > len(stream): break
        frames.append(stream[spos+2:spos+2+fl])
        spos += 2 + fl
    return frames

# main conn first client frame
main_c2s = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'C->S':
        main_c2s += p['data']
mf = parse_frames(main_c2s, 0)
print("main conn client frames: %d total, first len=%d" % (len(mf), len(mf[0])))
first = mf[0]
print("first frame hex: %s" % first[:100].hex())
# try decrypt with tx seed
try:
    dec = RokCrypto(135717691).decrypt(first)
    try:
        pf = ProtobufCodec.decode_message(dec)
        print("decrypted main C f0 op=%s fields=%s" % (pf.get(1), {k: (v.hex()[:60] if isinstance(v, bytes) else v) for k, v in pf.items()}))
    except Exception as e:
        print("decrypt ok but not protobuf: %s" % dec[:80].hex())
except Exception as e:
    print("decrypt failed: %s" % e)

# second conn
s2c2 = b''
c2s2 = b''
for p in packets:
    if p['cport'] == 38574:
        if p['dir'] == 'S->C': s2c2 += p['data']
        else: c2s2 += p['data']
sf2 = parse_frames(s2c2, 0)
cf2 = parse_frames(c2s2, 0)
print("\nsecond conn: %d server frames, %d client frames" % (len(sf2), len(cf2)))

for seed_name, seed in [('tx=135717691', 135717691), ('rx=851565604', 851565604)]:
    cr = RokCrypto(seed)
    print("\n--- try %s on second conn server f1 (len=%d) ---" % (seed_name, len(sf2[1])))
    try:
        dec = cr.decrypt(sf2[1])
        try:
            pf = ProtobufCodec.decode_message(dec)
            print("  op=%s first fields: %s" % (pf.get(1), {k: (v.hex()[:80] if isinstance(v, bytes) else v) for k, v in list(pf.items())[:4]}))
        except:
            print("  not protobuf: %s" % dec[:80].hex())
    except Exception as e:
        print("  fail: %s" % e)

# maybe second conn server frames need decryption from f0 with rx seed
cr = RokCrypto(851565604)
print("\n--- second conn server frames decrypted with rx seed (sequential) ---")
for i in range(min(8, len(sf2))):
    try:
        dec = cr.decrypt(sf2[i])
        try:
            pf = ProtobufCodec.decode_message(dec)
            print("  S2 f%d: op=%s len=%d" % (i, pf.get(1), len(dec)))
        except:
            print("  S2 f%d: NOT protobuf: %s" % (i, dec[:40].hex()))
    except Exception as e:
        print("  S2 f%d: fail %s" % (i, e))

ct = RokCrypto(135717691)
print("\n--- second conn client frames decrypted with tx seed (sequential) ---")
for i in range(min(8, len(cf2))):
    try:
        dec = ct.decrypt(cf2[i])
        try:
            pf = ProtobufCodec.decode_message(dec)
            print("  C2 f%d: op=%s len=%d" % (i, pf.get(1), len(dec)))
        except:
            print("  C2 f%d: NOT protobuf: %s" % (i, dec[:40].hex()))
    except Exception as e:
        print("  C2 f%d: fail %s" % (i, e))
