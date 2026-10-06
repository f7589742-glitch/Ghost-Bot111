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

def deep(v):
    if isinstance(v, bytes):
        try:
            inner = ProtobufCodec.decode_message(v)
            out = {}
            for k, sv in inner.items():
                out[k] = deep(sv)
            return out
        except:
            try:
                s = v.decode('utf-8')
                if len(s) > 0 and all(32 <= ord(c) < 127 for c in s):
                    return s
            except:
                pass
            if len(v) <= 16:
                return v.hex()
            return "(%dB)" % len(v)
    return v

crypto_tx = RokCrypto(135717691)
c2c_data = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'C->S':
        c2c_data += p['data']

cpos = 0
cframe = 0
want_c = (171, 181, 182, 186, 191, 192, 194, 195, 199)
while cpos + 2 <= len(c2c_data):
    fl = (c2c_data[cpos] << 8) | c2c_data[cpos+1]
    if fl == 0 or cpos + 2 + fl > len(c2c_data): break
    payload = c2c_data[cpos+2:cpos+2+fl]
    cpos += 2 + fl
    cframe += 1
    try:
        dec = crypto_tx.decrypt(payload)
        pf = ProtobufCodec.decode_message(dec)
        if cframe in want_c:
            op = pf.get(1, 0)
            dataf = pf.get(2, b'')
            print("C f%d op=%d: %s" % (cframe, op, str(deep(dataf))[:300]))
    except:
        pass

crypto_rx = RokCrypto(851565604)
s2c_data = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'S->C':
        s2c_data += p['data']

spos = 19
sframe = 0
want_s = (344, 345, 347, 350, 352, 354, 356, 358, 359, 360, 361, 363, 370, 372, 375, 376, 377, 379, 381, 382, 386, 387, 389, 390, 392, 396, 397, 399, 400, 401, 403, 404, 406, 408, 409)
while spos + 2 <= len(s2c_data):
    fl = (s2c_data[spos] << 8) | s2c_data[spos+1]
    if fl == 0 or spos + 2 + fl > len(s2c_data): break
    payload = s2c_data[spos+2:spos+2+fl]
    spos += 2 + fl
    sframe += 1
    try:
        dec = crypto_rx.decrypt(payload)
        pf = ProtobufCodec.decode_message(dec)
        if sframe in want_s:
            op = pf.get(1, 0)
            dataf = pf.get(2, b'')
            if op == 9999:
                print("S f%d op=9999 len=%d" % (sframe, len(dec)))
            else:
                print("S f%d op=%d: %s" % (sframe, op, str(deep(dataf))[:300]))
    except:
        pass
