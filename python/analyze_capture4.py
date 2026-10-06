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
    src_ip = '.'.join(str(b) for b in ip_header[12:16])
    dst_ip = '.'.join(str(b) for b in ip_header[16:20])
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
        'src_ip': src_ip, 'dst_ip': dst_ip,
        'src_port': src_port, 'dst_port': dst_port,
        'dir': 'S->C' if src_port == 3101 else 'C->S',
        'data': tcp_data,
    })

server_stream = b''
client_stream = b''
for p in packets:
    if p['dir'] == 'S->C':
        server_stream += p['data']
    else:
        client_stream += p['data']

print("Server: %d bytes, Client: %d bytes" % (len(server_stream), len(client_stream)))

# Find greeting in server stream
greet_idx = server_stream.find(bytes.fromhex('08f24212'))
print("Greeting at offset %d" % greet_idx)

# Greeting frame: parse length prefix before it
# The frame is [2-byte len][payload]. Find the length prefix
greet_payload_start = greet_idx
# Look backwards 2 bytes for length prefix
prefix = server_stream[greet_idx-2:greet_idx]
glen = (prefix[0] << 8) | prefix[1]
print("Greeting frame length prefix: %d" % glen)

# Parse greeting
greet_payload = server_stream[greet_idx:greet_idx+glen]
gf = ProtobufCodec.decode_message(greet_payload)
print("Greeting fields: %s" % {k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in gf.items()})
f2 = gf.get(2, b'')
sub = ProtobufCodec.decode_message(f2)
sub1, sub2 = sub.get(1, 0), sub.get(2, 0)
seed1, seed2 = derive_seed(sub1, sub2)
print("sub1=%d sub2=%d -> seed1=%d seed2=%d" % (sub1, sub2, seed1, seed2))

crypto_rx = RokCrypto(seed2)
crypto_tx = RokCrypto(seed1)

# The client stream: find greeting response. 
# Client sends login after greeting. Parse client stream frames.
print("\n=== CLIENT FRAMES (C->S) ===")
cpos = 0
cframe = 0
decrypted_clients = []
while cpos + 2 <= len(client_stream):
    fl = (client_stream[cpos] << 8) | client_stream[cpos+1]
    if fl == 0 or cpos + 2 + fl > len(client_stream):
        print("  stream end at pos %d" % cpos)
        break
    payload = client_stream[cpos+2:cpos+2+fl]
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
                info = str({k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})[:150]
            except:
                try:
                    info = data.decode('utf-8')[:100]
                except:
                    info = data.hex()[:60]
        print("C f%-4d op=%-5d len=%-4d %s" % (cframe, op, len(data) if isinstance(data, bytes) else 0, info))
        decrypted_clients.append((cframe, op, payload, data))
    except Exception as e:
        # Maybe it's the login frame (first client frame, encrypted with seed1)
        try:
            dec = crypto_tx.decrypt(payload)
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            print("C f%-4d op=%-5d (decrypted with seed1)" % (cframe, op))
        except:
            print("C f%-4d DECRYPT FAIL: %s" % (cframe, str(e)[:50]))

# Server frames AFTER greeting
print("\n=== SERVER FRAMES (S->C) after greeting ===")
spos = greet_idx + glen
sframe = 0
while spos + 2 <= len(server_stream):
    fl = (server_stream[spos] << 8) | server_stream[spos+1]
    if fl == 0 or spos + 2 + fl > len(server_stream):
        break
    payload = server_stream[spos+2:spos+2+fl]
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
                    info = str({k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in inner.items()})[:100]
                except:
                    info = data.hex()[:60]
        print("S f%-4d op=%-5d len=%-4d %s" % (sframe, op, len(data) if isinstance(data, bytes) else 0, info))
    except Exception as e:
        print("S f%-4d DECRYPT FAIL: %s" % (sframe, str(e)[:50]))
