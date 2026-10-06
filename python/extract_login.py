import struct, os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec

PCAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'game_capture.pcap')

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
    if src_port != 3101 and dst_port != 3101: continue
    packets.append({'dir': 'S->C' if src_port == 3101 else 'C->S',
                    'cport': dst_port if src_port == 3101 else src_port,
                    'data': tcp_data})

main_c2s = b''
for p in packets:
    if p['cport'] == 37870 and p['dir'] == 'C->S':
        main_c2s += p['data']

crypto_tx = RokCrypto(135717691)
cpos = 0
cframe = 0
while cpos + 2 <= len(main_c2s):
    fl = (main_c2s[cpos] << 8) | main_c2s[cpos+1]
    if fl == 0 or cpos + 2 + fl > len(main_c2s): break
    payload = main_c2s[cpos+2:cpos+2+fl]
    cpos += 2 + fl
    cframe += 1
    try:
        dec = crypto_tx.decrypt(payload)
    except:
        continue
    if cframe != 1:
        continue
    pf = ProtobufCodec.decode_message(dec)
    print("C f%d op=%d total payload %d bytes" % (cframe, pf.get(1), len(dec)))
    inner = ProtobufCodec.decode_message(pf.get(2, b''))
    for k, v in sorted(inner.items()):
        if isinstance(v, bytes):
            try:
                sub = ProtobufCodec.decode_message(v)
                print("  f%d (sub):" % k, {sk: (sv.hex()[:80] if isinstance(sv, bytes) else sv) for sk, sv in sub.items()})
            except:
                try:
                    s = v.decode('utf-8')
                    if all(32 <= ord(c) < 127 for c in s):
                        print("  f%d (str): %s" % (k, s))
                    else:
                        print("  f%d (bytes): %s" % (k, v.hex()[:100]))
                except:
                    print("  f%d (bytes): %s" % (k, v.hex()[:100]))
        else:
            print("  f%d = %s" % (k, v))
    # save full payload hex
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'captured_login_payload.hex'), 'w') as f:
        f.write(dec.hex())
    print("saved full login payload hex to python/captured_login_payload.hex")
    break
