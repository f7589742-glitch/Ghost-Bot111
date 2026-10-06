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

def deep(v):
    if isinstance(v, bytes):
        try:
            inner = ProtobufCodec.decode_message(v)
            return {k: deep(sv) for k, sv in inner.items()}
        except:
            if len(v) <= 24:
                return v.hex()
            return "(%dB)" % len(v)
    if isinstance(v, list):
        return [deep(i) for i in v]
    return v

# Decode 1083 payloads (first few distinct sizes)
spos = 19
sframe = 0
seen = set()
count = 0
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
    if op == 1083:
        count += 1
        key = fl
        if key not in seen and len(seen) < 3:
            seen.add(key)
            print("\n=== S f%d op=1083 len=%d (frame %d of 1083) ===" % (sframe, fl, count))
            print(json.dumps(deep(dataf), indent=1)[:2500])
    elif op == 1003 and not any(k == 1 for k in seen):
        pass

print("\nTotal op=1083 frames: %d" % count)

# Also check what client sent to discover entities: 925, 1001, 110
print("\n=== frame 33-35 (1001 context) & 45 (110) ===")
crypto_tx = RokCrypto(135717691)
c2s_data = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'C->S':
        c2s_data += p['data']
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
    if cframe in (33, 34, 35, 45, 47, 70, 71) or op in (1001, 110, 925, 1041):
        print("C f%d op=%d: %s" % (cframe, op, dataf.hex() if isinstance(dataf, bytes) else dataf))
