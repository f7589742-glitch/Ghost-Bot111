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
                    'data': tcp_data, 'ts': ts_sec + ts_usec / 1e6})

def f32(i):
    return struct.unpack('<f', struct.pack('<I', i))[0]

def deep_decode(data, depth=0):
    try:
        d = ProtobufCodec.decode_message(data)
    except:
        return {'raw': data.hex()[:60]}
    out = {}
    for k, v in d.items():
        if isinstance(v, bytes) and len(v) > 2:
            sub = deep_decode(v, depth+1)
            out[k] = sub
        else:
            out[k] = v
    return out

crypto_tx = RokCrypto(135717691)
c2c_data = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'C->S':
        c2c_data += p['data']

cpos = 0
cframe = 0
while cpos + 2 <= len(c2c_data):
    fl = (c2c_data[cpos] << 8) | c2c_data[cpos+1]
    if fl == 0 or cpos + 2 + fl > len(c2c_data): break
    payload = c2c_data[cpos+2:cpos+2+fl]
    cpos += 2 + fl
    cframe += 1
    try:
        dec = crypto_tx.decrypt(payload)
    except:
        continue
    if cframe in (170, 178, 184, 185, 188):
        try:
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            dataf = pf.get(2, b'')
            dd = deep_decode(dataf) if isinstance(dataf, bytes) else dataf
            print("C f%d op=%d len=%d: %s" % (cframe, op, len(dec), str(dd)[:400]))
        except Exception as ex:
            print("C f%d FAIL: %s" % (cframe, ex))

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
    try:
        dec = crypto_rx.decrypt(payload)
    except:
        continue
    if sframe < 290 or sframe > 411: continue
    try:
        pf = ProtobufCodec.decode_message(dec)
        op = pf.get(1, 0)
        dataf = pf.get(2, b'')
        if op == 9999:
            outer = ProtobufCodec.decode_message(dataf)
            try:
                dc = zlib.decompress(outer.get(2, b''))
                inner = ProtobufCodec.decode_message(dc)
                ents = inner.get(1, [])
                types = []
                for e in ents:
                    try:
                        ie = ProtobufCodec.decode_message(e)
                        types.append(ie.get(1))
                    except:
                        types.append('?')
                print("S f%d op=9999 types=%s" % (sframe, types))
            except:
                print("S f%d op=9999 (zlib fail)" % sframe)
        elif op in (1003, 1083, 1005, 1027, 1180, 1051, 904, 121, 122, 301, 903, 365, 364, 312, 111, 105):
            dd = deep_decode(dataf) if isinstance(dataf, bytes) else dataf
            print("S f%d op=%d len=%d: %s" % (sframe, op, len(dec), str(dd)[:250]))
        elif op == 61438:
            print("S f%d op=61438 (map blob)" % sframe)
        else:
            pass
    except Exception as ex:
        pass
