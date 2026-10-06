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

def deep(v, indent=0):
    pad = "  " * indent
    if isinstance(v, bytes):
        try:
            inner = ProtobufCodec.decode_message(v)
            out = {}
            for k, sv in inner.items():
                out[k] = deep(sv, indent+1)
            return out
        except:
            try:
                s = v.decode('utf-8')
                if len(s) > 0 and all(32 <= ord(c) < 127 for c in s):
                    return '"' + s + '"'
            except:
                pass
            if len(v) <= 16:
                return v.hex()
            return "(%dB)" % len(v)
    return v

crypto_tx = RokCrypto(135717691)
crypto_rx = RokCrypto(851565604)

c2s_data = b''
s2c_data = b''
for p in packets:
    if p['cport'] != 37870:
        continue
    if p['dir'] == 'C->S':
        c2s_data += p['data']
    else:
        s2c_data += p['data']

# Client frames 185-192 with full deep decode
print("=== CLIENT FRAMES 183-199 (deep) ===")
cpos = 0
cframe = 0
while cpos + 2 <= len(c2s_data):
    fl = (c2s_data[cpos] << 8) | c2s_data[cpos+1]
    if fl == 0 or cpos + 2 + fl > len(c2s_data):
        break
    payload = c2s_data[cpos+2:cpos+2+fl]
    cpos += 2 + fl
    cframe += 1
    dec = crypto_tx.decrypt(payload)
    pf = ProtobufCodec.decode_message(dec)
    op = pf.get(1, 0)
    dataf = pf.get(2, b'')
    if cframe < 170 or cframe > 186:
        continue
    print("\n--- C f%d op=%d ---" % (cframe, op))
    try:
        inner = ProtobufCodec.decode_message(dataf)
        for k, v in sorted(inner.items()):
            print("  f%d = %s" % (k, json.dumps(deep(v), default=str)[:400]))
    except Exception as e:
        print("  RAW: %s" % dataf.hex()[:300])

# Server frames around gather: 360-380 with deep decode
print("\n=== SERVER FRAMES 360-375 (deep) ===")
spos = 19
sframe = 0
while spos + 2 <= len(s2c_data):
    fl = (s2c_data[spos] << 8) | s2c_data[spos+1]
    if fl == 0 or spos + 2 + fl > len(s2c_data):
        break
    payload = s2c_data[spos+2:spos+2+fl]
    spos += 2 + fl
    sframe += 1
    dec = crypto_rx.decrypt(payload)
    pf = ProtobufCodec.decode_message(dec)
    op = pf.get(1, 0)
    if op in (1083, 8003):
        continue
    dataf = pf.get(2, b'')
    if sframe < 335 or sframe > 365:
        continue
    print("\n--- S f%d op=%d ---" % (sframe, op))
    if op == 9999:
        try:
            outer = ProtobufCodec.decode_message(dataf)
            dc = zlib.decompress(outer.get(2, b''))
            inner = ProtobufCodec.decode_message(dc)
            print("  ZLIB %dB: %s" % (len(dc), str({k: (len(v) if isinstance(v, bytes) else v) for k, v in inner.items()})[:250]))
            if 3 in inner and isinstance(inner[3], bytes):
                try:
                    z3 = zlib.decompress(inner[3])
                    i3 = ProtobufCodec.decode_message(z3)
                    print("  ZLIB3 %dB: %s" % (len(z3), str({k: (len(v) if isinstance(v, bytes) else v) for k, v in i3.items()})[:250]))
                except:
                    pass
        except Exception as e:
            print("  zlib fail: %s" % e)
    else:
        try:
            inner = ProtobufCodec.decode_message(dataf)
            for k, v in sorted(inner.items()):
                print("  f%d = %s" % (k, json.dumps(deep(v), default=str)[:400]))
        except Exception as e:
            print("  RAW: %s" % dataf.hex()[:200])

import json