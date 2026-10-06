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

def f32(i):
    return struct.unpack('<f', struct.pack('<I', i))[0]

crypto_rx = RokCrypto(851565604)
s2c_data = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'S->C':
        s2c_data += p['data']

spos = 19
sframe = 0
seen_types = {}
while spos + 2 <= len(s2c_data):
    fl = (s2c_data[spos] << 8) | s2c_data[spos+1]
    if fl == 0 or spos + 2 + fl > len(s2c_data): break
    payload = s2c_data[spos+2:spos+2+fl]
    spos += 2 + fl
    sframe += 1
    try:
        dec = crypto_rx.decrypt(payload)
        pf = ProtobufCodec.decode_message(dec)
        op = pf.get(1, 0)
        if op != 9999: continue
        dataf = pf.get(2, b'')
        if not isinstance(dataf, bytes): continue
        outer = ProtobufCodec.decode_message(dataf)
        dc = zlib.decompress(outer.get(2, b''))
        inner = ProtobufCodec.decode_message(dc)
        ents = inner.get(1, [])
        if not isinstance(ents, list): continue
        types = []
        nodes = []
        for e in ents:
            try:
                ie = ProtobufCodec.decode_message(e)
                t = ie.get(1)
                types.append(t)
                if t == 1027:
                    d = ie.get(2, b'')
                    d2 = ProtobufCodec.decode_message(d)
                    f1 = d2.get(1, b'')
                    try:
                        f1d = ProtobufCodec.decode_message(f1)
                        nid = f1d.get(1)
                        p = f1d.get(3)
                        pos = None
                        if isinstance(p, bytes):
                            pp = ProtobufCodec.decode_message(p)
                            pos = (round(f32(pp.get(1, 0)), 1), round(f32(pp.get(2, 0)), 1))
                        nodes.append((nid, pos))
                    except:
                        nodes.append(('?', None))
            except:
                types.append('?')
        if sframe <= 60 or (1027 in types):
            print("S f%d types=%s nodes=%s" % (sframe, str(types)[:100], nodes))
        for t in types:
            seen_types[t] = seen_types.get(t, 0) + 1
    except Exception:
        pass

print("\nAll entity types seen across session:")
for t, c in sorted(seen_types.items(), key=lambda kv: -kv[1]):
    print("  type %s x%d" % (t, c))
