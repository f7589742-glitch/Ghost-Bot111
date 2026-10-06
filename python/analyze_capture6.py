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

# Main connection: client port 37870
main_c2s = b''
main_s2c = b''
for p in packets:
    if p['cport'] == 37870:
        if p['dir'] == 'C->S':
            main_c2s += p['data']
        else:
            main_s2c += p['data']

print("Main conn: C2S=%d bytes, S2C=%d bytes" % (len(main_c2s), len(main_s2c)))

# Seeds for main connection
seed1, seed2 = 135717691, 851565604
crypto_tx = RokCrypto(seed1)
crypto_rx = RokCrypto(seed2)

# Decrypt all client frames
print("\n=== CLIENT FRAMES (C->S) - main connection ===")
cpos = 0
cframe = 0
client_results = []
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
        info = ""
        if isinstance(data, bytes) and len(data) > 0:
            try:
                inner = ProtobufCodec.decode_message(data)
                info = str({k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})[:160]
            except:
                try:
                    info = data.decode('utf-8')[:120]
                except:
                    info = data.hex()[:60]
        print("C f%-4d op=%-5d len=%-4d %s" % (cframe, op, len(data) if isinstance(data, bytes) else 0, info))
        client_results.append((cframe, op, data))
    except Exception as e:
        print("C f%-4d FAIL %s payload=%s" % (cframe, str(e)[:30], payload[:40].hex()))

# Decrypt server frames after greeting (offset 19 = 2 + 17)
print("\n=== SERVER FRAMES (S->C) after greeting ===")
spos = 19  # 2-byte len prefix + 17-byte greeting
sframe = 0
server_results = []
while spos + 2 <= len(main_s2c):
    fl = (main_s2c[spos] << 8) | main_s2c[spos+1]
    if fl == 0 or spos + 2 + fl > len(main_s2c):
        break
    payload = main_s2c[spos+2:spos+2+fl]
    spos += 2 + fl
    sframe += 1
    try:
        dec = crypto_rx.decrypt(payload)
        pf = ProtobufCodec.decode_message(dec)
        op = pf.get(1, 0)
        data = pf.get(2, b'')
        if op == 8003:
            continue
        info = ""
        if isinstance(data, bytes) and len(data) > 0:
            if op == 9999:
                try:
                    outer = ProtobufCodec.decode_message(data)
                    if 2 in outer and isinstance(outer[2], bytes) and outer[2][:2] == b'\x78\x9c':
                        dc = zlib.decompress(outer[2])
                        inner = ProtobufCodec.decode_message(dc)
                        info = "ZLIB(%dB)" % len(dc)
                except:
                    info = "raw(%dB)" % len(data)
            else:
                try:
                    inner = ProtobufCodec.decode_message(data)
                    info = str({k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})[:120]
                except:
                    info = data.hex()[:60]
        print("S f%-4d op=%-5d len=%-4d %s" % (sframe, op, len(data) if isinstance(data, bytes) else 0, info))
        server_results.append((sframe, op, data))
    except Exception as e:
        print("S f%-4d FAIL %s" % (sframe, str(e)[:30]))

# Save client opcodes
print("\n=== CLIENT OPCODE SUMMARY ===")
ops = {}
for _, op, _ in client_results:
    ops[op] = ops.get(op, 0) + 1
for op, cnt in sorted(ops.items()):
    print("  op=%-5d count=%d" % (op, cnt))
