import sys, os, json, asyncio, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_module import RokCrypto
from headless_client import ProtobufCodec, FrameParser, build_minimal_login
from derive_seed_from_nonce import derive_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("chat_formats")

async def test_all_formats():
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'profiles', 'teez9334.json')
    with open(profile_path) as f:
        profile = json.load(f)
    quick_token = "A-aJhV1Rggx3kCqZR50XixvoYSOVp6-P"
    quick_uid = 260172399

    reader, writer = await asyncio.open_connection(profile["auth_server"], profile["auth_port"])
    header = await reader.readexactly(2)
    length = (header[0] << 8) | header[1]
    payload = await reader.readexactly(length)
    fields = ProtobufCodec.decode_message(payload)
    field2 = fields.get(2, b"")
    sub_fields = ProtobufCodec.decode_message(field2)
    sub1, sub2 = sub_fields.get(1, 0), sub_fields.get(2, 0)
    seed1, seed2 = derive_seed(sub1, sub2)
    crypto_tx, crypto_rx = RokCrypto(seed1), RokCrypto(seed2)

    login_payload = build_minimal_login({
        "player_id": quick_uid,
        "access_token": quick_token,
        "app_uid": quick_uid,
    })
    encrypted = crypto_tx.encrypt(login_payload)
    writer.write(FrameParser.build_frame(encrypted))
    await writer.drain()

    for i in range(25):
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=5.0)
        except asyncio.TimeoutError:
            break

    logger.info("Connected with quick token, ready to test chat formats")

    msg = "bot test"

    formats = []

    # Format 1: current (always returns 3)
    formats.append(("current", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: ProtobufCodec.encode_message({
                1: msg.encode("utf-8"),
                3: 1,
            }),
            3: 2,
        }),
    })))

    # Format 2: flat - opcode 9911, data = message bytes only
    formats.append(("flat_msg_only", ProtobufCodec.encode_message({
        1: 9911,
        2: msg.encode("utf-8"),
    })))

    # Format 3: {1: msg_bytes}
    formats.append(("{1:msg}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
        }),
    })))

    # Format 4: {1: msg_bytes, 2: channel_int}
    formats.append(("{1:msg,2:ch}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
            2: 2,
        }),
    })))

    # Format 5: {1: msg_bytes, 3: channel}
    formats.append(("{1:msg,3:ch}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
            3: 2,
        }),
    })))

    # Format 6: {2: msg_bytes} - field 2 instead of 1
    formats.append(("{2:msg}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            2: msg.encode("utf-8"),
        }),
    })))

    # Format 7: {1: string_field, 2: channel}
    formats.append(("{1:str,2:ch}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg,
            2: 2,
        }),
    })))

    # Format 8: triple nested {1: {1: {1: msg}}}
    formats.append(("triple_nest", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: ProtobufCodec.encode_message({
                1: ProtobufCodec.encode_message({
                    1: msg.encode("utf-8"),
                }),
            }),
        }),
    })))

    # Format 9: msg as string (not bytes) in field 1
    formats.append(("{1:str_msg}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg,
            3: 2,
        }),
    })))

    # Format 10: {1: msg, 2: 0, 3: 0}
    formats.append(("{1:msg,2:0,3:0}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
            2: 0,
            3: 0,
        }),
    })))

    # Format 11: msg bytes in field 1, varint in field 2
    formats.append(("{1:msg_b,2:1}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
            2: 1,
        }),
    })))

    # Format 12: empty msg
    formats.append(("empty_msg", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: b"",
        }),
    })))

    # Format 13: {1: msg_bytes, 4: int}
    formats.append(("{1:msg,4:int}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
            4: 1,
        }),
    })))

    # Format 14: {1: msg, 2: 0}
    formats.append(("{1:msg,2:0}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
            2: 0,
        }),
    })))

    # Format 15: {1: msg, 3: "castle"}
    formats.append(("{1:msg,3:str}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
            3: "castle",
        }),
    })))

    # Format 16: channel=1 (global)
    formats.append(("{1:msg,3:1_global}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
            3: 1,
        }),
    })))

    # Format 17: no data
    formats.append(("no_data", ProtobufCodec.encode_message({
        1: 9911,
    })))

    # Format 18: {1: msg, 5: 0}
    formats.append(("{1:msg,5:0}", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
            5: 0,
        }),
    })))

    # Format 19: just msg bytes (no nested protobuf at all) in field 1
    formats.append(("raw_1", ProtobufCodec.encode_message({
        1: 9911,
        2: ProtobufCodec.encode_message({
            1: msg.encode("utf-8"),
        }),
    })))

    for name, frame_data in formats:
        encrypted = crypto_tx.encrypt(frame_data)
        writer.write(FrameParser.build_frame(encrypted))
        await writer.drain()
        await asyncio.sleep(0.3)
        try:
            rh = await asyncio.wait_for(reader.readexactly(2), timeout=3.0)
            rl = (rh[0] << 8) | rh[1]
            rd = await asyncio.wait_for(reader.readexactly(rl), timeout=3.0)
            dec = crypto_rx.decrypt(rd)
            pf = ProtobufCodec.decode_message(dec)
            opcode = pf.get(1, 0)
            data = pf.get(2, b"")
            if opcode == 8003:
                logger.info("  %-25s -> keepalive (skip)", name)
                continue
            if isinstance(data, bytes) and len(data) > 0:
                inner = ProtobufCodec.decode_message(data)
                result = inner.get(2, "?")
                logger.info("  %-25s -> opcode=%d result=%s", name, opcode, result)
            else:
                logger.info("  %-25s -> opcode=%d no_data", name, opcode)
        except asyncio.TimeoutError:
            logger.info("  %-25s -> timeout", name)
        except Exception as e:
            logger.info("  %-25s -> error: %s", name, str(e)[:60])

    writer.close()

asyncio.run(test_all_formats())
