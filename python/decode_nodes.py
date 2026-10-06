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
    if op in (904, 926, 111, 1051, 424, 1180, 1003):
        print("S f%d op=%d len=%d: %s" % (sframe, op, fl, json.dumps(deep(dataf))[:400]))
    if sframe > 400 and op == 904:
        break

# Where did node 4138906 appear? Search 9999 zlib for 4138906
print("\n=== searching 4138906 in 9999 zlib payloads ===")
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
        pf = ProtobufCodec.decode_message(dec)
        op = pf.get(1, 0)
        if op != 9999:
            continue
        dataf = pf.get(2, b'')
        try:
            outer = ProtobufCodec.decode_message(dataf)
            dc = zlib.decompress(outer.get(2, b''))
        except:
            continue
        # search for 4138906 varint encoding: 9a cf fc 01
        if b'\x9a\xcf\xfc\x01' in dc or b'\x9a\xcf\xfc\x01' in dc:
            print("S f%d: 4138906 FOUND in zlib (%d bytes)" % (sframe, len(dc)))
            idx = dc.find(b'\x9a\xcf\xfc\x01')
            print("  context: %s" % dc[max(0,idx-80):idx+80].hex())
        # Also search raw dataf
        if b'\x9a\xcf\xfc\x01' in dataf:
            print("S f%d: 4138906 FOUND in raw frame" % sframe)
    except:
        pass
