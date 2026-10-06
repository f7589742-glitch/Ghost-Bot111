import sys, os, json, asyncio, time, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, build_minimal_login
from derive_seed_from_nonce import derive_seed

async def test():
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez8888_56.json')
    with open(profile_path) as f:
        profile = json.load(f)

    reader, writer = await asyncio.open_connection(profile['server_host'], profile['server_port'])
    header = await reader.readexactly(2)
    length = (header[0] << 8) | header[1]
    payload = await reader.readexactly(length)
    fields = ProtobufCodec.decode_message(payload)
    field2 = fields.get(2, b'')
    sub_fields = ProtobufCodec.decode_message(field2)
    sub1, sub2 = sub_fields.get(1, 0), sub_fields.get(2, 0)
    seed1, seed2 = derive_seed(sub1, sub2)
    crypto_tx, crypto_rx = RokCrypto(seed1), RokCrypto(seed2)

    login = build_minimal_login({
        'player_id': profile['app_uid'],
        'access_token': profile['access_token'],
        'app_uid': profile['app_uid'],
    })
    writer.write(FrameParser.build_frame(crypto_tx.encrypt(login)))
    await writer.drain()

    for i in range(25):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
        except asyncio.TimeoutError:
            break

    msg = 'Hello from bot'

    # Try many different chat message structures
    role_id = int(profile.get('role_id', profile['app_uid']))

    formats = {
        # Basic structures
        '1:msg_only': {1: 9911, 2: ProtobufCodec.encode_message({1: msg.encode()})},
        '1:msg_2:2': {1: 9911, 2: ProtobufCodec.encode_message({1: msg.encode(), 2: 2})},
        '1:msg_3:castle': {1: 9911, 2: ProtobufCodec.encode_message({1: msg.encode(), 3: 'castle'})},
        
        # With role info
        '1:msg_5:rid': {1: 9911, 2: ProtobufCodec.encode_message({1: msg.encode(), 5: role_id})},
        '1:msg_3:2_5:rid': {1: 9911, 2: ProtobufCodec.encode_message({1: msg.encode(), 3: 2, 5: role_id})},
        '1:msg_2:2_5:rid_6:0': {1: 9911, 2: ProtobufCodec.encode_message({1: msg.encode(), 2: 2, 5: role_id, 6: 0})},
        
        # Nested msg with role
        '1:nest_2:2': {1: 9911, 2: ProtobufCodec.encode_message({
            1: ProtobufCodec.encode_message({1: msg.encode(), 2: role_id}),
            3: 2,
        })},
        '1:nest_3:2': {1: 9911, 2: ProtobufCodec.encode_message({
            1: ProtobufCodec.encode_message({1: msg.encode(), 3: 2}),
        })},
        
        # Try with extra fields
        '1:msg_2:0_3:0_4:0': {1: 9911, 2: ProtobufCodec.encode_message({1: msg.encode(), 2: 0, 3: 0, 4: 0})},
        '1:msg_2:0_3:2_4:0_5:0': {1: 9911, 2: ProtobufCodec.encode_message({1: msg.encode(), 2: 0, 3: 2, 4: 0, 5: 0})},
        
        # msg as varint in field 1
        '1:int_2:msg': {1: 9911, 2: ProtobufCodec.encode_message({1: role_id, 2: msg.encode()})},
        
        # All fields flat
        'flat': {1: 9911, 2: ProtobufCodec.encode_message({1: msg.encode(), 2: 0, 3: 2, 4: 0, 5: role_id, 6: 0})},
        
        # msg as string field 2
        '2:str_3:int': {1: 9911, 2: ProtobufCodec.encode_message({2: msg, 3: 2})},
        '2:bytes_3:int': {1: 9911, 2: ProtobufCodec.encode_message({2: msg.encode(), 3: 2})},
        
        # Different opcode for chat?
        '9912_msg': {1: 9912, 2: ProtobufCodec.encode_message({1: msg.encode(), 3: 2})},
        '9910_msg': {1: 9910, 2: ProtobufCodec.encode_message({1: msg.encode(), 3: 2})},
        
        # With name bytes
        '1:msg_2:name_3:ch': {1: 9911, 2: ProtobufCodec.encode_message({1: msg.encode(), 2: profile.get('role_name', 'bot').encode(), 3: 2})},
    }

    for name, frame_data in formats.items():
        encrypted = crypto_tx.encrypt(ProtobufCodec.encode_message(frame_data))
        writer.write(FrameParser.build_frame(encrypted))
        await writer.drain()
        await asyncio.sleep(0.2)
        try:
            while True:
                rh = await asyncio.wait_for(reader.readexactly(2), timeout=1.5)
                rl = (rh[0] << 8) | rh[1]
                rd = await asyncio.wait_for(reader.readexactly(rl), timeout=1.5)
                dec = crypto_rx.decrypt(rd)
                pf = ProtobufCodec.decode_message(dec)
                opcode = pf.get(1, 0)
                if opcode == 8003:
                    continue
                data = pf.get(2, b'')
                if opcode == 1 and isinstance(data, bytes) and len(data) > 0:
                    inner = ProtobufCodec.decode_message(data)
                    result = inner.get(2, 'ok')
                    if result != 0:
                        print("  %-35s -> ERROR=%s" % (name, result))
                    else:
                        print("  %-35s -> SUCCESS!" % name)
                elif opcode == 1:
                    print("  %-35s -> opcode=1 no_data" % name)
                else:
                    print("  %-35s -> opcode=%d" % (name, opcode))
                break
        except asyncio.TimeoutError:
            print("  %-35s -> timeout (no response)" % name)

    writer.close()

asyncio.run(test())
