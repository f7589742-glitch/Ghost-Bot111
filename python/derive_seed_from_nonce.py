"""
derive_seed_from_nonce.py — Seed derivation from greeting nonce for ROK dual-crypto mode.

Based on reverse-engineered formula from EngineDll.dll:
- Greeting provides two 32-bit values: sub1, sub2
- TX seed (client->server): seed1 = ((sub2 // 3) + 0x2766) & 0x3fffffff
- RX seed (server->client): seed2 = ((sub1 >> 1) + 0x400) & 0x3fffffff

These seeds are used for dual crypto mode:
- crypto_tx = RokCrypto(seed1)  # encrypt client->server
- crypto_rx = RokCrypto(seed2)  # decrypt server->client

The 8-byte nonce is: struct.pack("<II", sub1, sub2)
"""

MASK30 = 0x3fffffff

# Standard constants from EngineDll.dll
TX_CONSTANT = 0x2766   # 10086
RX_CONSTANT = 0x400    # 1024

def derive_seed(sub1: int, sub2: int) -> tuple:
    """
    Derive TX and RX seeds from greeting sub-fields.
    
    Args:
        sub1: First sub-field from greeting (32-bit)
        sub2: Second sub-field from greeting (32-bit)
    
    Returns:
        (seed1, seed2) where:
        - seed1 = TX seed for client->server encryption
        - seed2 = RX seed for server->client decryption
    """
    # Ensure 32-bit values
    sub1 = sub1 & 0xFFFFFFFF
    sub2 = sub2 & 0xFFFFFFFF
    
    # TX seed: client->server encryption seed
    # Formula: ((sub2 // 3) + 0x2766) & 0x3fffffff
    seed1 = ((sub2 // 3) + TX_CONSTANT) & 0x3fffffff
    
    # RX seed: server->client decryption seed  
    # Formula: ((sub1 >> 1) + 0x400) & 0x3fffffff
    seed2 = ((sub1 >> 1) + RX_CONSTANT) & 0x3fffffff
    
    return seed1, seed2


def parse_greeting(raw: bytes):
    """
    Parse the server greeting frame and extract sub1, sub2.
    
    Wire format: [length:2-big-endian][protobuf_payload]
    Protobuf: field1=8562, field2=nested{ sub1=varint, sub2=varint }
    """
    if len(raw) < 4:
        raise ValueError(f"Greeting too short: {len(raw)} bytes")
    
    # Skip 2-byte length header
    protobuf = raw[2:]
    
    # Simple protobuf decode for the greeting
    def decode_varint(data, offset=0):
        result = 0
        shift = 0
        while offset < len(data):
            b = data[offset]
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                offset += 1
                break
            shift += 7
            offset += 1
        return result, offset
    
    def decode_message(data, offset=0):
        fields = {}
        while offset < len(data):
            tag_byte = data[offset]
            field_num = tag_byte >> 3
            wire_type = tag_byte & 0x07
            offset += 1
            
            if wire_type == 0:  # varint
                val, offset = decode_varint(data, offset)
                fields[field_num] = val
            elif wire_type == 2:  # length-delimited
                length, offset = decode_varint(data, offset)
                fields[field_num] = data[offset:offset+length]
                offset += length
            else:
                raise ValueError(f"Unsupported wire type {wire_type}")
        return fields
    
    # Parse top-level message
    top_fields = decode_message(raw[2:])
    
    field1 = top_fields.get(1, 0)
    field2 = top_fields.get(2, b"")
    
    sub1, sub2 = 0, 0
    if isinstance(field2, (bytes, bytearray)) and len(field2) >= 2:
        sub_fields = {}
        # decode nested message
        def decode_nested(data):
            f = {}
            offset = 0
            while offset < len(data):
                tag = data[offset]
                fn = tag >> 3
                wt = tag & 0x07
                offset += 1
                if wt == 0:
                    val = 0
                    shift = 0
                    while offset < len(data):
                        b = data[offset]
                        f |= (b & 0x7F) << shift
                        if not (b & 0x80):
                            offset += 1
                            break
                        shift += 7
                        offset += 1
                    f[fn] = val
            decode_nested(field2)
        # Simpler: just decode directly
        sub_fields = decode_message(field2)
        sub1 = sub_fields.get(1, 0)
        sub2 = sub_fields.get(2, 0)
    
    return {
        'field1': 8562,
        'sub1': sub1 & 0xFFFFFFFF,
        'sub2': sub2 & 0xFFFFFFFF,
    }


if __name__ == '__main__':
    # Test with known values from captured_nonces.json
    # nonce_8: "0c08be88a3fb0610" -> lo=0x88A3F008, hi=0x1006FBA3
    sub1_test = 0x88A3F008  # lo
    sub2_test = 0x1006FBA3  # hi
    
    s1, s2 = derive_seed(sub1_test, sub2_test)
    print(f"Test: sub1=0x{sub1_test:08x}, sub2=0x{sub2_test:08x}")
    print(f"  seed1 (TX) = 0x{s1:08x}")
    print(f"  seed2 (RX) = 0x{s2:08x}")
    
    # Test with current session greeting
    sub1_cur = 0x1269c1fc
    sub2_cur = 0x598cd7fd
    s1, s2 = derive_seed(sub1_cur, sub2_cur)
    print(f"\nCurrent: sub1=0x{sub1_cur:08x}, sub2=0x{sub2_cur:08x}")
    print(f"  seed1 (TX) = 0x{s1:08x}")
    print(f"  seed2 (RX) = 0x{s2:08x}")