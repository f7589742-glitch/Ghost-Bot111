import struct, sys, os, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec
from derive_seed_from_nonce import derive_seed

pcap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'chat_capture.pcap')

with open(pcap_path, 'rb') as f:
    data = f.read()

# Parse SLL2 packets
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
    direction = 'S->C' if src_port == 3101 else 'C->S'
    packets.append({
        'ts': ts_sec + ts_usec/1000000.0,
        'dir': direction,
        'data': tcp_data,
    })

# Merge TCP segments into streams
server_stream = b''
client_stream = b''
for p in packets:
    if p['dir'] == 'S->C':
        server_stream += p['data']
    else:
        client_stream += p['data']

# Find greeting in server stream (starts with 00 XX 00...)
# The greeting should be the first server data
print("Server stream total: %d bytes" % len(server_stream))
print("Client stream total: %d bytes" % len(client_stream))
print("First 40 bytes S: %s" % server_stream[:40].hex())
print("First 40 bytes C: %s" % client_stream[:40].hex())

# The greeting format: [2-byte length] [protobuf payload]
# Find first complete frame in server stream
if len(server_stream) >= 2:
    frame_len = (server_stream[0] << 8) | server_stream[1]
    print("\nFirst frame length: %d" % frame_len)
    if frame_len + 2 <= len(server_stream):
        greeting = server_stream[2:2+frame_len]
        fields = ProtobufCodec.decode_message(greeting)
        print("Greeting fields: %s" % {k: v if not isinstance(v, bytes) else "(%dB)" % len(v) for k, v in fields.items()})
        
        field2 = fields.get(2, b'')
        if isinstance(field2, bytes) and len(field2) > 0:
            sub = ProtobufCodec.decode_message(field2)
            sub1 = sub.get(1, 0)
            sub2 = sub.get(2, 0)
            print("Sub1=%d sub2=%d" % (sub1, sub2))
            seed1, seed2 = derive_seed(sub1, sub2)
            print("Seed1=%d seed2=%d" % (seed1, seed2))
            
            crypto_rx = RokCrypto(seed2)
            crypto_tx = RokCrypto(seed1)
            
            # Now decrypt all server frames after greeting
            pos = 2 + frame_len
            frame_num = 0
            while pos < len(server_stream) and frame_num < 80:
                if pos + 2 > len(server_stream):
                    break
                fl = (server_stream[pos] << 8) | server_stream[pos+1]
                if fl == 0 or fl > 20000:
                    break
                if pos + 2 + fl > len(server_stream):
                    break
                encrypted = server_stream[pos+2:pos+2+fl]
                pos += 2 + fl
                frame_num += 1
                
                try:
                    decrypted = crypto_rx.decrypt(encrypted)
                    pf = ProtobufCodec.decode_message(decrypted)
                    opcode = pf.get(1, 0)
                    payload = pf.get(2, b'')
                    
                    if opcode == 8003:
                        continue
                    
                    plen = len(payload) if isinstance(payload, bytes) else 0
                    
                    info = ""
                    if isinstance(payload, bytes) and plen > 0:
                        try:
                            inner = ProtobufCodec.decode_message(payload)
                            # Show key info
                            for k, v in sorted(inner.items()):
                                if isinstance(v, str):
                                    info += " %s=%s" % (k, v[:50])
                                elif isinstance(v, bytes):
                                    try:
                                        s = v.decode('utf-8', errors='strict')
                                        if len(s) > 1:
                                            info += " F%d=%s" % (k, s[:50])
                                    except:
                                        if len(v) < 30:
                                            info += " F%d=(%dB)" % (k, len(v))
                                elif isinstance(v, int):
                                    if k != 1:
                                        info += " F%d=%d" % (k, v)
                        except:
                            pass
                    
                    print("S opcode=%d len=%d%s" % (opcode, plen, info))
                except Exception as e:
                    print("S frame%d decrypt error: %s" % (frame_num, str(e)[:40]))
            
            # Now decrypt client frames
            print("\n--- Client frames ---")
            cpos = 0
            cframe_num = 0
            while cpos < len(client_stream) and cframe_num < 50:
                if cpos + 2 > len(client_stream):
                    break
                fl = (client_stream[cpos] << 8) | client_stream[cpos+1]
                if fl == 0 or fl > 20000:
                    break
                if cpos + 2 + fl > len(client_stream):
                    break
                encrypted = client_stream[cpos+2:cpos+2+fl]
                cpos += 2 + fl
                cframe_num += 1
                
                try:
                    decrypted = crypto_tx.decrypt(encrypted)
                    pf = ProtobufCodec.decode_message(decrypted)
                    opcode = pf.get(1, 0)
                    payload = pf.get(2, b'')
                    
                    plen = len(payload) if isinstance(payload, bytes) else 0
                    info = ""
                    if isinstance(payload, bytes) and plen > 0:
                        try:
                            inner = ProtobufCodec.decode_message(payload)
                            for k, v in sorted(inner.items()):
                                if isinstance(v, str):
                                    info += " %s=%s" % (k, v[:80])
                                elif isinstance(v, bytes):
                                    try:
                                        s = v.decode('utf-8', errors='strict')
                                        if len(s) > 1:
                                            info += " F%d=%s" % (k, s[:80])
                                    except:
                                        if len(v) < 30:
                                            info += " F%d=(%dB)" % (k, len(v))
                                elif isinstance(v, int):
                                    if k != 1:
                                        info += " F%d=%d" % (k, v)
                        except:
                            pass
                    
                    print("C opcode=%d len=%d%s" % (opcode, plen, info))
                except Exception as e:
                    print("C frame%d decrypt error: %s" % (cframe_num, str(e)[:40]))
