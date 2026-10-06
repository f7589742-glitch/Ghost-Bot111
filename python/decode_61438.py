import struct, sys, os, zlib, json
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
    pf = ProtobufCodec.decode_message(dec)
    op = pf.get(1, 0)
    dataf = pf.get(2, b'')
    if op != 61438:
        continue
    print("S f%d op=61438 len=%d" % (sframe, fl))
    try:
        outer = ProtobufCodec.decode_message(dataf)
    except Exception as e:
        print("  outer decode fail: %s" % e)
        continue
    for k, v in sorted(outer.items()):
        if isinstance(v, bytes):
            print("  f%d: %dB" % (k, len(v)))
            # try zlib
            try:
                dc = zlib.decompress(v)
                print("    zlib OK -> %dB" % len(dc))
                inner = ProtobufCodec.decode_message(dc)
                print("    inner: %s" % str({k2: (len(v2) if isinstance(v2, bytes) else v2) for k2, v2 in inner.items()})[:200])
                for k2, v2 in inner.items():
                    if isinstance(v2, bytes) and len(v2) > 100:
                        try:
                            d2 = zlib.decompress(v2)
                            i2 = ProtobufCodec.decode_message(d2)
                            print("    f%d zlib2 -> %dB: %s" % (k2, len(d2), str({k3: (len(v3) if isinstance(v3, bytes) else v3) for k3, v3 in i2.items()})[:200]))
                        except Exception as e2:
                            print("    f%d zlib2 fail: %s" % (k2, e2))
            except Exception as e:
                print("    not zlib: %s" % str(e)[:50])
                if b'\x9a\xcf\xfc\x01' in v:
                    print("    *** 4138906 found in raw f%d" % k)
                    idx = v.find(b'\x9a\xcf\xfc\x01')
                    print("    ctx: %s" % v[max(0,idx-100):idx+100].hex())
        else:
            print("  f%d: %s" % (k, v))
