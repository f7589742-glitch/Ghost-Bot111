import socket, sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser
from derive_seed_from_nonce import derive_seed

profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez8888_56.json')
with open(profile_path) as f:
    profile = json.load(f)

hosts = [
    ('rocchat.lilithgame.com', 8080),
    ('rocchat2.lilithgame.com', 8080),
    ('34.107.206.111', 8080),
    ('139.95.8.78', 8080),
]

for host, port in hosts:
    print(f"\n=== Connecting to {host}:{port} ===")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    try:
        s.connect((host, port))
        print("Connected!")
        
        time.sleep(1)
        data = s.recv(4096)
        print("Greeting: %d bytes" % len(data))
        if data:
            print("Hex: %s" % data.hex()[:200])
            length = (data[0] << 8) | data[1]
            print("Length field: %d" % length)
            if length + 2 <= len(data):
                payload = data[2:2+length]
                fields = ProtobufCodec.decode_message(payload)
                print("Fields: %s" % fields)
                field2 = fields.get(2, b'')
                if isinstance(field2, bytes) and len(field2) > 0:
                    sub = ProtobufCodec.decode_message(field2)
                    sub1, sub2 = sub.get(1, 0), sub.get(2, 0)
                    print("Sub1=%d sub2=%d" % (sub1, sub2))
                    seed1, seed2 = derive_seed(sub1, sub2)
                    
                    crypto_tx = RokCrypto(seed1)
                    crypto_rx = RokCrypto(seed2)
                    
                    login = ProtobufCodec.encode_message({
                        1: int(profile['app_uid']),
                        2: profile['access_token'].encode(),
                    })
                    encrypted = crypto_tx.encrypt(login)
                    frame = FrameParser.build_frame(encrypted)
                    s.send(frame)
                    print("Sent login (%d bytes)" % len(frame))
                    
                    time.sleep(2)
                    resp = s.recv(4096)
                    if resp:
                        print("Response: %d bytes" % len(resp))
                        if len(resp) >= 2:
                            rlen = (resp[0] << 8) | resp[1]
                            rpayload = resp[2:2+rlen]
                            dec = crypto_rx.decrypt(rpayload)
                            rf = ProtobufCodec.decode_message(dec)
                            print("Decoded: %s" % rf)
                    else:
                        print("No response")
        else:
            print("Empty greeting - trying raw send...")
    except Exception as e:
        print("Error: %s" % str(e)[:100])
    finally:
        s.close()
