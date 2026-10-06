import struct, os, zlib
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

crypto_rx = RokCrypto(851565604)
s2c_data = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'S->C':
        s2c_data += p['data']

spos = 19
sframe = 0
while spos + 2 <= len(s2c_data):
    fl = (s2c_data[spos] << 8) | s2c_data[spos+1]
    if fl == 0 or spos + 2 + fl > len(s2c_data): break
    payload = s2c_data[spos+2:spos+2+fl]
    spos += 2 + fl
    sframe += 1
    if sframe != 326: 
        try:
            crypto_rx.decrypt(payload)
        except:
            pass
        continue
    try:
        dec = crypto_rx.decrypt(payload)
    except Exception as ex:
        print("decrypt fail: %s" % ex)
        break
    pf = ProtobufCodec.decode_message(dec)
    print("S f%d op=%d len=%d" % (sframe, pf.get(1), len(dec)))
    dataf = pf.get(2, b'')
    outer = ProtobufCodec.decode_message(dataf)
    print("outer fields: %s" % {k: (v.hex()[:100] if isinstance(v, bytes) else v) for k, v in outer.items()})
    dc = zlib.decompress(outer.get(2, b''))
    print("zlib decompressed: %d bytes" % len(dc))
    inner = ProtobufCodec.decode_message(dc)
    print("inner fields:")
    for k, v in inner.items():
        if isinstance(v, bytes):
            print("  f%d: bytes len=%d: %s" % (k, len(v), v.hex()[:120]))
        else:
            print("  f%d: %s" % (k, v))
    ents = inner.get(1, [])
    if isinstance(ents, list):
        print("\nentries (%d):" % len(ents))
        for i, e in enumerate(ents[:6]):
            print("  [%d] %s" % (i, e.hex()[:150]))
        if len(ents) > 6:
            print("  [%d] %s" % (6, ents[6].hex()[:150]))
