import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import FrameParser, ProtobufCodec
from derive_seed_from_nonce import derive_seed

pcap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'chat_capture.pcap')

with open(pcap_path, 'rb') as f:
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
    ip_header = pkt[ip_start:]
    ihl = (ip_header[0] & 0x0F) * 4
    protocol = ip_header[9]
    if protocol != 6:
        continue
    tcp_start = ip_start + ihl
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

server_parser = FrameParser()
for p in packets:
    if p['dir'] == 'S->C':
        server_parser.feed(p['data'])

client_parser = FrameParser()
for p in packets:
    if p['dir'] == 'C->S':
        client_parser.feed(p['data'])

# Now extract frames properly
server_frames = []
while True:
    f = server_parser._try_parse()
    if f[0] is None:
        break
    frame_obj, consumed = f
    server_frames.append(frame_obj)
    del server_parser._buffer[:consumed]

client_frames = []
while True:
    f = client_parser._try_parse()
    if f[0] is None:
        break
    frame_obj, consumed = f
    client_frames.append(frame_obj)
    del client_parser._buffer[:consumed]

print("Server frames: %d" % len(server_frames))
print("Client frames: %d" % len(client_frames))

# The greeting should be the first server frame
# It's unencrypted - contains the nonce
if server_frames:
    greeting = server_frames[0]
    print("\n=== Greeting (frame 0) ===")
    print("Raw (%d bytes): %s" % (len(greeting.raw), greeting.raw.hex()))
    print("Payload (%d bytes): %s" % (len(greeting.payload), greeting.payload.hex()))
    
    fields = ProtobufCodec.decode_message(greeting.payload)
    print("Fields: %s" % {k: v if not isinstance(v, bytes) else "(%dB) %s" % (len(v), v.hex()) for k, v in fields.items()})
    
    # Extract nonce
    field2 = fields.get(2, b'')
    if isinstance(field2, bytes) and len(field2) > 0:
        sub = ProtobufCodec.decode_message(field2)
        sub1 = sub.get(1, 0)
        sub2 = sub.get(2, 0)
        print("Sub1=%d (0x%08x) sub2=%d (0x%08x)" % (sub1, sub1, sub2, sub2))
        seed1, seed2 = derive_seed(sub1, sub2)
        print("Seed1=%d seed2=%d" % (seed1, seed2))
        
        crypto_rx = RokCrypto(seed2)
        crypto_tx = RokCrypto(seed1)
        
        # Decrypt server frames after greeting
        print("\n=== Server frames (decrypted) ===")
        for i, frame in enumerate(server_frames[1:], 1):
            if i > 80:
                break
            try:
                decrypted = crypto_rx.decrypt(frame.payload)
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
                                info += " %s=%s" % (k, v[:60])
                            elif isinstance(v, bytes):
                                try:
                                    s = v.decode('utf-8', errors='strict')
                                    if len(s) > 1:
                                        info += " F%d=%s" % (k, s[:60])
                                except:
                                    info += " F%d=(%dB)" % (k, len(v))
                            elif isinstance(v, int):
                                if k != 1:
                                    info += " F%d=%d" % (k, v)
                    except:
                        pass
                
                print("S #%d opcode=%d len=%d%s" % (i, opcode, plen, info))
            except Exception as e:
                print("S #%d DECRYPT ERROR: %s" % (i, str(e)[:60]))
        
        # Decrypt client frames
        print("\n=== Client frames (decrypted) ===")
        for i, frame in enumerate(client_frames[:50]):
            try:
                decrypted = crypto_tx.decrypt(frame.payload)
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
                                info += " %s=%s" % (k, v[:60])
                            elif isinstance(v, bytes):
                                try:
                                    s = v.decode('utf-8', errors='strict')
                                    if len(s) > 1:
                                        info += " F%d=%s" % (k, s[:60])
                                except:
                                    info += " F%d=(%dB)" % (k, len(v))
                            elif isinstance(v, int):
                                if k != 1:
                                    info += " F%d=%d" % (k, v)
                    except:
                        pass
                
                print("C #%d opcode=%d len=%d%s" % (i, opcode, plen, info))
            except Exception as e:
                print("C #%d DECRYPT ERROR: %s" % (i, str(e)[:60]))
