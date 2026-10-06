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

def entity_type_entries(dc):
    """Parse top-level: f1 = list of {1: type, 2: payload}"""
    types = []
    try:
        inner = ProtobufCodec.decode_message(dc)
        if 1 in inner and isinstance(inner[1], list):
            for e in inner[1]:
                try:
                    ie = ProtobufCodec.decode_message(e)
                    t = ie.get(1)
                    d = ie.get(2, b'')
                    types.append((t, len(d) if isinstance(d, bytes) else 0))
                except:
                    types.append(('?', 0))
    except:
        pass
    return types

for sframe, dc in zlibs:
    types = entity_type_entries(dc)
    if types:
        print("S f%-4d (%5dB): %s" % (sframe, len(dc), " ".join("%s:%d" % (t, l) for t, l in types)))
    else:
        print("S f%-4d (%5dB): no f1 list" % (sframe, len(dc)))
