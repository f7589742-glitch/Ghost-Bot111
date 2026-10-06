import struct, sys, os, zlib, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec
from derive_seed_from_nonce import derive_seed

PCAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'game_capture.pcap')

with open(PCAP, 'rb') as f:
    data = f.read()

# Parse pcap global header
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
    ip_start = 20  # SLL2 header is 20 bytes
    if ip_start + 20 > len(pkt):
        continue
    ip_header = pkt[ip_start:]
    ihl = (ip_header[0] & 0x0F) * 4
    protocol = ip_header[9]
    if protocol != 6:  # TCP only
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
    direction = 'S->C' if src_port == 3101 else 'C->S'
    packets.append({'ts': ts_sec + ts_usec/1000000.0, 'dir': direction, 'data': tcp_data})

print("Total packets (port 3101): %d" % len(packets))
c2s_total = sum(len(p['data']) for p in packets if p['dir'] == 'C->S')
s2c_total = sum(len(p['data']) for p in packets if p['dir'] == 'S->C')
print("C->S bytes: %d, S->C bytes: %d" % (c2s_total, s2c_total))

# Reassemble streams
server_stream = b''
client_stream = b''
for p in packets:
    if p['dir'] == 'S->C':
        server_stream += p['data']
    else:
        client_stream += p['data']

# Find greeting: first unencrypted frame in server stream with field1=8562
greeting_found = False
pos = 0
frame_num = 0
while pos + 2 <= len(server_stream) and frame_num < 50:
    fl = (server_stream[pos] << 8) | server_stream[pos+1]
    if fl == 0 or pos + 2 + fl > len(server_stream):
        break
    payload = server_stream[pos+2:pos+2+fl]
    pos += 2 + fl
    frame_num += 1
    try:
        fields = ProtobufCodec.decode_message(payload)
        if fields.get(1) == 8562:
            print("GREETING found at frame %d (len=%d): %s" % (frame_num, fl, payload.hex()))
            f2 = fields.get(2, b'')
            sub = ProtobufCodec.decode_message(f2)
            sub1, sub2 = sub.get(1, 0), sub.get(2, 0)
            print("sub1=%d sub2=%d" % (sub1, sub2))
            seed1, seed2 = derive_seed(sub1, sub2)
            print("seed1=%d seed2=%d" % (seed1, seed2))
            crypto_rx = RokCrypto(seed2)
            crypto_tx = RokCrypto(seed1)
            greeting_found = True
            break
    except:
        pass

if not greeting_found:
    print("NO GREETING FOUND - trying other frames...")
    pos = 0
    while pos + 2 <= len(server_stream):
        fl = (server_stream[pos] << 8) | server_stream[pos+1]
        if fl == 0 or pos + 2 + fl > len(server_stream):
            break
        payload = server_stream[pos+2:pos+2+fl]
        try:
            fields = ProtobufCodec.decode_message(payload)
            if len(fields) > 0:
                print("Frame len=%d fields=%s" % (fl, {k: type(v).__name__ for k, v in fields.items()}))
        except:
            pass
        pos += 2 + fl
else:
    # Decrypt all server frames after greeting
    print("\n=== SERVER FRAMES (S->C) ===")
    frame_num = 0
    pos = 0
    while pos + 2 <= len(server_stream):
        fl = (server_stream[pos] << 8) | server_stream[pos+1]
        if fl == 0 or pos + 2 + fl > len(server_stream):
            break
        payload = server_stream[pos+2:pos+2+fl]
        pos += 2 + fl
        frame_num += 1
        if frame_num == 1 and payload[:2] != b'\x08\xf2':
            continue
        try:
            fields = ProtobufCodec.decode_message(payload)
            if fields.get(1) == 8562:
                continue  # greeting already handled
        except:
            pass
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
                            info = "ZLIB(%dB) %s" % (len(dc), {k: type(v).__name__ for k, v in inner.items()})
                    except:
                        info = "raw(%dB)" % len(data)
                else:
                    try:
                        inner = ProtobufCodec.decode_message(data)
                        info = str({k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})[:100]
                    except:
                        info = data.hex()[:60]
            print("S f%d op=%-5d %s" % (frame_num, op, info))
        except Exception as e:
            print("S f%d DECRYPT FAIL: %s" % (frame_num, str(e)[:40]))

    # Decrypt all client frames
    print("\n=== CLIENT FRAMES (C->S) ===")
    frame_num = 0
    pos = 0
    while pos + 2 <= len(client_stream):
        fl = (client_stream[pos] << 8) | client_stream[pos+1]
        if fl == 0 or pos + 2 + fl > len(client_stream):
            break
        payload = client_stream[pos+2:pos+2+fl]
        pos += 2 + fl
        frame_num += 1
        try:
            dec = crypto_tx.decrypt(payload)
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            data = pf.get(2, b'')
            if op == 9:  # keepalive
                continue
            info = ""
            if isinstance(data, bytes) and len(data) > 0:
                try:
                    inner = ProtobufCodec.decode_message(data)
                    info = str({k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})[:120]
                except:
                    try:
                        info = data.decode('utf-8')[:100]
                    except:
                        info = data.hex()[:60]
            print("C f%d op=%-5d len=%d %s" % (frame_num, op, len(data) if isinstance(data, bytes) else 0, info))
        except Exception as e:
            print("C f%d DECRYPT FAIL: %s raw=%s" % (frame_num, str(e)[:40], payload[:30].hex()))
