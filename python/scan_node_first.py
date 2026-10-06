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
    if offset + 16 > len(data):
        break
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

crypto_rx = RokCrypto(851565604)
s2c_data = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'S->C':
        s2c_data += p['data']

NODE_ID = 4138906
NODE_VARINT = b'\x9a\xcf\xfc\x01'

spos = 19
sframe = 0
first_seen = None
type_hist = {}
while spos + 2 <= len(s2c_data):
    fl = (s2c_data[spos] << 8) | s2c_data[spos+1]
    if fl == 0 or spos + 2 + fl > len(s2c_data):
        break
    payload = s2c_data[spos+2:spos+2+fl]
    spos += 2 + fl
    sframe += 1
    try:
        dec = crypto_rx.decrypt(payload)
    except:
        continue
    if NODE_VARINT in dec:
        if first_seen is None:
            first_seen = sframe
        try:
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            print("S f%d op=%d RAW contains node varint. Raw(len=%d): %s" % (sframe, op, len(dec), dec[:120].hex()))
        except:
            print("S f%d UNDECODABLE contains node varint: %s" % (sframe, dec[:120].hex()))
    # collect 9999 entity types
    try:
        pf = ProtobufCodec.decode_message(dec)
        op = pf.get(1, 0)
        if op != 9999:
            continue
        dataf = pf.get(2, b'')
        if not isinstance(dataf, bytes):
            continue
        outer = ProtobufCodec.decode_message(dataf)
        dc = zlib.decompress(outer.get(2, b''))
        inner = ProtobufCodec.decode_message(dc)
        ents = inner.get(1, [])
        if isinstance(ents, list):
            types = []
            for e in ents:
                try:
                    ie = ProtobufCodec.decode_message(e)
                    types.append(ie.get(1))
                except:
                    types.append('?')
            key = tuple(types)
            type_hist[key] = type_hist.get(key, 0) + 1
    except Exception as ex:
        pass

print("first frame containing node varint: S f%s" % first_seen)
print("9999 entity type tuples (types -> count):")
for k, v in sorted(type_hist.items(), key=lambda kv: -kv[1]):
    print("  %s x%d" % (str(k), v))
