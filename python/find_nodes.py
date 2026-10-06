import struct, sys, os, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec

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
    if struct.unpack('>H', pkt[0:2])[0] != 0x0800:
        continue
    ip_start = 20
    if ip_start + 20 > len(pkt):
        continue
    ip_header = pkt[ip_start:]
    ihl = (ip_header[0] & 0x0F) * 4
    if ip_header[9] != 6:
        continue
    tcp_start = ip_start + ihl
    if tcp_start + 20 > len(pkt):
        continue
    tcp_header = pkt[tcp_start:]
    src_port = struct.unpack('>H', tcp_header[0:2])[0]
    dst_port = struct.unpack('>H', tcp_header[2:4])[0]
    doff = ((tcp_header[12] >> 4) & 0xF) * 4
    tcp_data = tcp_header[doff:]
    if len(tcp_data) == 0 or (src_port != 3101 and dst_port != 3101):
        continue
    packets.append({
        'dir': 'S->C' if src_port == 3101 else 'C->S',
        'cport': dst_port if src_port == 3101 else src_port,
        'data': tcp_data,
    })

crypto_rx = RokCrypto(851565604)
s2c_data = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'S->C':
        s2c_data += p['data']

# Collect ALL 9999 zlib payloads
spos = 19
sframe = 0
zlibs = []
while spos + 2 <= len(s2c_data):
    fl = (s2c_data[spos] << 8) | s2c_data[spos+1]
    if fl == 0 or spos + 2 + fl > len(s2c_data):
        break
    payload = s2c_data[spos+2:spos+2+fl]
    spos += 2 + fl
    sframe += 1
    try:
        dec = crypto_rx.decrypt(payload)
        pf = ProtobufCodec.decode_message(dec)
        op = pf.get(1, 0)
        if op != 9999:
            continue
        dataf = pf.get(2, b'')
        try:
            outer = ProtobufCodec.decode_message(dataf)
            dc = zlib.decompress(outer[2])
            zlibs.append((sframe, dc))
        except:
            pass
    except:
        pass

print("Total 9999 zlib payloads: %d" % len(zlibs))
for sframe, dc in zlibs:
    print("  S f%-4d %dB" % (sframe, len(dc)))

# Search each for entity type 1027 (varint: 0x83 0x08 = 1027)
print("\n=== searching entity type 1027 (node) ===")
for sframe, dc in zlibs:
    # 1027 = 0x0803? varint: 1027 = 0b10000000011 -> 0x83 0x08
    idx = dc.find(b'\x08\x83\x08')
    if idx >= 0:
        print("S f%d: FOUND 1027 marker at %d" % (sframe, idx))
        print("  ctx: %s" % dc[max(0,idx-60):idx+60].hex())

# Search march type 1023 = 0x08 0xFF 0x07
print("\n=== searching entity type 1023 (march) ===")
for sframe, dc in zlibs:
    idx = dc.find(b'\x08\xff\x07')
    if idx >= 0:
        print("S f%d: FOUND 1023 marker at %d" % (sframe, idx))

# Look at login batch (S f31, 10178B) - structure overview
print("\n=== LOGIN BATCH (S f31) top-level ===")
sframe, dc = zlibs[1]
inner = ProtobufCodec.decode_message(dc)
for k, v in sorted(inner.items()):
    if isinstance(v, bytes):
        print("  f%d: %dB" % (k, len(v)))
    elif isinstance(v, list):
        print("  f%d: list[%d]" % (k, len(v)))
    else:
        print("  f%d: %s" % (k, v))

# Check what the login batch f1 (list) entries contain
if 1 in inner and isinstance(inner[1], list):
    entries = inner[1]
    print("\nLogin batch f1 entries: %d" % len(entries))
    for e in entries[:15]:
        try:
            ie = ProtobufCodec.decode_message(e)
            t = ie.get(1, '?')
            if isinstance(t, int):
                print("  entry type=%d rest=%s" % (t, str({k: (len(v) if isinstance(v, bytes) else v) for k, v in ie.items() if k != 1})[:150]))
            else:
                print("  entry ??? %s" % e.hex()[:80])
        except:
            print("  entry raw %s" % e.hex()[:80])
