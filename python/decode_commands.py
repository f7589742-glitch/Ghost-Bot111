import struct, sys, os, zlib, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec
from derive_seed_from_nonce import derive_seed

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
    proto_type = struct.unpack('>H', pkt[0:2])[0]
    if proto_type != 0x0800:
        continue
    ip_start = 20
    if ip_start + 20 > len(pkt):
        continue
    ip_header = pkt[ip_start:]
    ihl = (ip_header[0] & 0x0F) * 4
    protocol = ip_header[9]
    if protocol != 6:
        continue
    tcp_start = ip_start + ihl
    if tcp_start + 20 > len(pkt):
        continue
    tcp_header = pkt[tcp_start:]
    src_port = struct.unpack('>H', tcp_header[0:2])[0]
    dst_port = struct.unpack('>H', tcp_header[2:4])[0]
    doff = ((tcp_header[12] >> 4) & 0xF) * 4
    tcp_data = tcp_header[doff:]
    if len(tcp_data) == 0:
        continue
    if src_port != 3101 and dst_port != 3101:
        continue
    packets.append({
        'dir': 'S->C' if src_port == 3101 else 'C->S',
        'cport': dst_port if src_port == 3101 else src_port,
        'data': tcp_data,
    })

main_c2s = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'C->S':
        main_c2s += p['data']

crypto_tx = RokCrypto(135717691)

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
                    return s
            except:
                pass
            if len(v) <= 16:
                return v.hex()
            return "(%dB)" % len(v)
    return v

cpos = 0
cframe = 0
while cpos + 2 <= len(main_c2s):
    fl = (main_c2s[cpos] << 8) | main_c2s[cpos+1]
    if fl == 0 or cpos + 2 + fl > len(main_c2s):
        break
    payload = main_c2s[cpos+2:cpos+2+fl]
    cpos += 2 + fl
    cframe += 1
    try:
        dec = crypto_tx.decrypt(payload)
        pf = ProtobufCodec.decode_message(dec)
        op = pf.get(1, 0)
        data = pf.get(2, b'')
        if op == 9:
            continue
        # Focus on important commands
        if op in [1012, 1004, 5, 8, 300, 6, 1050, 102, 205]:
            print("\n=== C f%d op=%d len=%d ===" % (cframe, op, len(data) if isinstance(data, bytes) else 0))
            try:
                inner = ProtobufCodec.decode_message(data)
                for k, v in sorted(inner.items()):
                    print("  f%d = %s" % (k, json.dumps(deep(v), default=str)[:300]))
            except Exception as e:
                print("  RAW: %s" % data.hex()[:200])
                print("  err: %s" % e)
    except:
        pass
