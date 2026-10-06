"""
crypto_module.py — Complete encryption/decryption for Rise of Kingdoms protocol.

Fully reverse-engineered from EngineDll.dll:
  - State init (0x24a0): seed → identifier + 3 derived values + 3 arrays of 64 DWORDs
  - Keystream gen (gen_2660): triple additive LFSR with carry → 4096-byte keystream buffer
  - XOR encrypt/decrypt (func_2940): plaintext[i] ^= keystream[i]

Usage:
    from crypto_module import RokCrypto
    crypto = RokCrypto(seed=0x11223344)
    encrypted = crypto.encrypt(plaintext)
    crypto.reset()  # reset keystream position
    decrypted = crypto.decrypt(encrypted)
"""

MASK32 = 0xFFFFFFFF

# ──────────────────────────────────────────────────────────────────────
# State Init (EngineDll.dll + 0x24a0)
# ──────────────────────────────────────────────────────────────────────

def _transform_round1(eax):
    """Single transform round at 0x25d0-0x25f0. Input: eax → Output: ecx."""
    ecx = (eax * 2) & MASK32
    ecx ^= eax; ecx &= MASK32
    ecx = (ecx * 2) & MASK32
    ecx ^= eax; ecx &= MASK32
    ecx = (ecx << 2) & MASK32
    ecx ^= eax; ecx &= MASK32
    ecx = (ecx << 2) & MASK32
    ecx ^= eax; ecx &= MASK32
    ecx = (ecx << 25) & MASK32
    ecx ^= eax; ecx &= MASK32
    eax = (eax >> 1) & MASK32
    ecx = ecx & 0x80000000
    ecx = (ecx | eax) & MASK32
    return ecx


def _transform_round2(ecx):
    """Single transform round at 0x25f2-0x2611. Input: ecx → Output: eax."""
    eax = (ecx * 2) & MASK32
    eax ^= ecx; eax &= MASK32
    eax = (eax * 2) & MASK32
    eax ^= ecx; eax &= MASK32
    eax = (eax << 2) & MASK32
    eax ^= ecx; eax &= MASK32
    eax = (eax << 2) & MASK32
    eax ^= ecx; eax &= MASK32
    eax = (eax << 25) & MASK32
    eax ^= ecx; eax &= MASK32
    ecx = (ecx >> 1) & MASK32
    eax = eax & 0x80000000
    eax = (eax | ecx) & MASK32
    return eax


def _full_transform(val):
    """One inner-loop iteration: two rounds back-to-back."""
    ecx = _transform_round1(val)
    return _transform_round2(ecx)


def _compute_derived(identifier):
    """Compute 3 derived values from identifier (0x24e1-0x259e)."""
    ebx = identifier & MASK32
    r8d = (ebx >> 1) & MASK32

    # derived1 at [rdi+0x08]
    eax = (ebx * 2) & MASK32
    eax ^= ebx; eax &= MASK32
    eax = (eax * 2) & MASK32
    eax ^= ebx; eax &= MASK32
    eax = (eax << 2) & MASK32
    ecx = (ebx * 2) & MASK32
    eax ^= ebx; eax &= MASK32
    ecx ^= r8d; ecx &= MASK32
    eax = (eax << 2) & MASK32
    ecx &= 0x55555555
    eax ^= ebx; eax &= MASK32
    eax = (eax << 25) & MASK32
    eax ^= ebx; eax &= MASK32
    eax &= 0x80000000
    eax = (eax | r8d) & MASK32
    derived1 = eax

    # derived2 at [rdi+0x11c] — ecx carries from above
    # Only uses transform_round2 (single round, not double)
    eax = (ebx * 2) & MASK32
    ecx ^= eax; ecx &= MASK32
    derived2 = _transform_round2(ecx)

    # derived3 at [rdi+0x230]
    # Also uses only transform_round2 (single round)
    ecx = ebx
    eax = ebx
    eax = (eax << 4) & MASK32
    ecx = (ecx >> 4) & MASK32
    ecx ^= eax; ecx &= MASK32
    ebx2 = (ebx << 4) & MASK32
    ecx &= 0x0F0F0F0F
    ecx ^= ebx2; ecx &= MASK32
    ecx = (~ecx) & MASK32
    derived3 = _transform_round2(ecx)

    return derived1, derived2, derived3


# ──────────────────────────────────────────────────────────────────────
# Keystream Generation (gen_2660)
# ──────────────────────────────────────────────────────────────────────

def _gen_2660(state):
    """
    Generate 4096 bytes of keystream into state[0x344:0x1344].
    state: mutable bytearray of at least 0x1344 bytes.
    """
    def r32(off):
        return int.from_bytes(state[off:off+4], 'little')

    def w32(off, val):
        state[off:off+4] = (val & MASK32).to_bytes(4, 'little')

    ks_off = 0x344
    remaining = 1024

    while remaining > 0:
        flag2 = r32(0x12c)
        flag1 = r32(0x18)
        flag3 = r32(0x240)
        ecx = flag2 + flag1 + flag3
        all_same = (ecx == 0 or ecx == 3)

        if not all_same:
            r8b = 1 if ecx == 2 else 0

        # Array1
        update = all_same or (flag1 == r8b)
        if update:
            idx1 = r32(0x14)
            new_idx = (idx1 + 1) & 0x3f
            w32(0x14, new_idx)
            da = (new_idx - r32(0x10)) & 0x3f
            db = (new_idx - r32(0x0c)) & 0x3f
            va = r32(0x1c + da * 4)
            vb = r32(0x1c + db * 4)
            nv = (va + vb) & MASK32
            w32(0x1c + new_idx * 4, nv)
            w32(0x18, 0 if (nv >= va and nv >= vb) else 1)

        # Array2
        flag2_val = r32(0x12c)
        update = all_same or (flag2_val == r8b)
        if update:
            idx2 = r32(0x128)
            new_idx = (idx2 + 1) & 0x3f
            w32(0x128, new_idx)
            da = (new_idx - r32(0x124)) & 0x3f
            db = (new_idx - r32(0x120)) & 0x3f
            va = r32(0x130 + da * 4)
            vb = r32(0x130 + db * 4)
            nv = (va + vb) & MASK32
            w32(0x130 + new_idx * 4, nv)
            w32(0x12c, 0 if (nv >= va and nv >= vb) else 1)

        # Array3
        flag3_val = r32(0x240)
        update = all_same or (flag3_val == r8b)
        if update:
            idx3 = r32(0x23c)
            new_idx = (idx3 + 1) & 0x3f
            w32(0x23c, new_idx)
            da = (new_idx - r32(0x238)) & 0x3f
            db = (new_idx - r32(0x234)) & 0x3f
            va = r32(0x244 + da * 4)
            vb = r32(0x244 + db * 4)
            nv = (va + vb) & MASK32
            w32(0x244 + new_idx * 4, nv)
            w32(0x240, 0 if (nv >= va and nv >= vb) else 1)

        # Output
        i1 = r32(0x14)
        i2 = r32(0x128)
        i3 = r32(0x23c)
        out = r32(0x244 + i3 * 4)
        out ^= r32(0x130 + i2 * 4)
        out ^= r32(0x1c + i1 * 4)
        w32(ks_off, out)
        ks_off += 4
        remaining -= 1

    return bytes(state[0x344:0x344 + 4096])


# ──────────────────────────────────────────────────────────────────────
# RokCrypto: Complete crypto interface
# ──────────────────────────────────────────────────────────────────────

class RokCrypto:
    """
    Rise of Kingdoms stream cipher.
    
    State layout (0x1344 bytes = 4932):
      +0x00: identifier (seed ^ 0x5027919)
      +0x04: keystream_offset (0-1023, byte offset into 4096-byte buffer)
      +0x08: derived1 (seed for array1)
      +0x0c: tap_b1=55, +0x10: tap_a1=24
      +0x14: idx1, +0x18: flag1
      +0x1c..+0x118: array1[64]
      +0x11c: derived2 (seed for array2)
      +0x120: tap_b2=57, +0x124: tap_a2=7
      +0x128: idx2, +0x12c: flag2
      +0x130..+0x22c: array2[64]
      +0x230: derived3 (seed for array3)
      +0x234: tap_b3=58, +0x238: tap_a3=19
      +0x23c: idx3, +0x240: flag3
      +0x244..+0x340: array3[64]
      +0x344..+0x1343: keystream buffer (1024 DWORDs = 4096 bytes)
    """

    STATE_SIZE = 0x1344
    KS_BUFFER_OFF = 0x344
    KS_BUFFER_SIZE = 4096
    KS_BUFFER_DWORDS = 1024

    def __init__(self, seed=0):
        self.state = bytearray(self.STATE_SIZE)
        self._init_state(seed)

    def _init_state(self, seed):
        """Emulate EngineDll+0x24a0."""
        identifier = (seed ^ 0x5027919) & MASK32
        derived1, derived2, derived3 = _compute_derived(identifier)

        def w32(off, val):
            self.state[off:off+4] = (val & MASK32).to_bytes(4, 'little')

        w32(0x00, identifier)
        w32(0x08, derived1)
        w32(0x0c, 55)
        w32(0x10, 24)
        w32(0x11c, derived2)
        w32(0x120, 57)
        w32(0x124, 7)
        w32(0x230, derived3)
        w32(0x234, 58)
        w32(0x238, 19)

        seeds = [derived1, derived2, derived3]
        arr_bases = [0x1c, 0x130, 0x244]
        idx_bases = [0x14, 0x128, 0x23c]

        for arr_idx in range(3):
            eax = seeds[arr_idx]
            base = arr_bases[arr_idx]
            for i in range(64):
                val = eax
                for _ in range(16):
                    ecx = _transform_round1(val)
                    val = _transform_round2(ecx)
                eax = val
                w32(base + i * 4, eax)
            w32(idx_bases[arr_idx], 0x3f)

        # Initial keystream generation
        _gen_2660(self.state)

    def _get_ks_byte(self):
        """Get one keystream byte, regenerating buffer when exhausted."""
        off = int.from_bytes(self.state[0x04:0x08], 'little')
        if off >= self.KS_BUFFER_SIZE:
            _gen_2660(self.state)
            off = 0
        b = self.state[self.KS_BUFFER_OFF + off]
        off += 1
        self.state[0x04:0x08] = off.to_bytes(4, 'little')
        return b

    def process(self, data):
        """XOR data with keystream (same function for encrypt and decrypt)."""
        result = bytearray(len(data))
        for i in range(len(data)):
            result[i] = data[i] ^ self._get_ks_byte()
        return bytes(result)

    def encrypt(self, plaintext):
        """Encrypt plaintext (XOR with keystream)."""
        return self.process(plaintext)

    def decrypt(self, ciphertext):
        """Decrypt ciphertext (XOR with keystream — same as encrypt)."""
        return self.process(ciphertext)

    def reset(self):
        """Reset keystream offset to regenerate buffer."""
        self.state[0x04:0x08] = (0).to_bytes(4, 'little')

    def get_identifier(self):
        return int.from_bytes(self.state[0x00:0x04], 'little')

    def get_derived(self):
        d1 = int.from_bytes(self.state[0x08:0x0c], 'little')
        d2 = int.from_bytes(self.state[0x11c:0x120], 'little')
        d3 = int.from_bytes(self.state[0x230:0x234], 'little')
        return d1, d2, d3


# ──────────────────────────────────────────────────────────────────────
# Server response decryption test
# ──────────────────────────────────────────────────────────────────────

def _parse_varint(data, pos):
    v, s = 0, 0
    while pos < len(data):
        b = data[pos]
        v |= (b & 0x7f) << s
        s += 7
        pos += 1
        if (b & 0x80) == 0:
            break
    return v, pos


def _validate_protobuf(data):
    """Walk a protobuf buffer and return a validity score (0-10)."""
    score = 0
    pos = 0
    depth = 0

    while pos < len(data) and depth < 20:
        if pos >= len(data):
            break

        tag, new_pos = _parse_varint(data, pos)
        if new_pos == pos:
            break
        pos = new_pos

        field_num = tag >> 3
        wire_type = tag & 0x07

        if field_num < 1 or field_num > 536870911:
            break
        if wire_type > 5:
            break

        score += 1

        if wire_type == 0:
            _, pos = _parse_varint(data, pos)
        elif wire_type == 2:
            length, pos = _parse_varint(data, pos)
            if length < 0 or pos + length > len(data):
                break
            content = data[pos:pos + length]
            pos += length

            printable = sum(1 for b in content if 32 <= b < 127)
            if printable > length * 0.6 and length >= 2:
                score += 2

            if length > 0 and content[0] == 0x08:
                score += 1
        elif wire_type == 5:
            pos += 4
        elif wire_type == 1:
            pos += 8
        else:
            break

        depth += 1

    return min(score, 10)


def test_decrypt_server_response(ciphertext, seed):
    """
    Decrypt a server response with a candidate ch=2 seed and score the result.

    Returns dict with:
      - seed: candidate seed value
      - plaintext: decrypted bytes
      - score: 0-10 validity score (higher = more likely correct)
      - reasons: list of scoring reasons
      - hex_preview: first 80 bytes hex
      - ascii_preview: printable ASCII preview
    """
    crypto = RokCrypto(seed)
    plaintext = crypto.decrypt(ciphertext)

    score = 0
    reasons = []

    if len(plaintext) == 0:
        return {
            'seed': seed, 'score': 0, 'reasons': ['empty'],
            'plaintext': plaintext, 'hex_preview': '',
            'ascii_preview': ''
        }

    first_byte = plaintext[0]
    field_num = first_byte >> 3
    wire_type = first_byte & 0x07

    if 1 <= field_num <= 100 and wire_type <= 5:
        score += 1
        reasons.append(f'valid_tag_f{field_num}_w{wire_type}')

    printable = sum(1 for b in plaintext[:80] if 32 <= b < 127)
    if printable > 40:
        score += 2
        reasons.append(f'high_printable_{printable}/80')

    if len(plaintext) >= 4:
        possible_length = (plaintext[0] >> 3 == 0) or (plaintext[0] & 0x07 == 2)
        if possible_length:
            score += 1
            reasons.append('likely_structured')

    proto_score = _validate_protobuf(plaintext[:200])
    score += proto_score
    if proto_score > 3:
        reasons.append(f'protobuf_valid_{proto_score}')

    has_endpoint = b'rocgate' in plaintext or b'lilithgame' in plaintext
    has_version = b'1.1.9' in plaintext or b'1.1.' in plaintext
    if has_endpoint:
        score += 3
        reasons.append('contains_server_address')
    if has_version:
        score += 1
        reasons.append('contains_version')

    score = min(score, 10)

    return {
        'seed': seed,
        'score': score,
        'reasons': reasons,
        'plaintext': plaintext,
        'hex_preview': plaintext[:80].hex(),
        'ascii_preview': ''.join(chr(b) if 32 <= b < 127 else '.' for b in plaintext[:80]),
        'length': len(plaintext)
    }


# ──────────────────────────────────────────────────────────────────────
# Self-test
# ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Test with seed 0x11223344
    crypto = RokCrypto(0x11223344)
    ident = crypto.get_identifier()
    d1, d2, d3 = crypto.get_derived()
    print(f"Identifier:  0x{ident:08x}")
    print(f"Derived1:    0x{d1:08x}")
    print(f"Derived2:    0x{d2:08x}")
    print(f"Derived3:    0x{d3:08x}")

    # Encrypt/decrypt roundtrip
    msg = b"Hello, Rise of Kingdoms!"
    enc = crypto.encrypt(msg)
    crypto.reset()
    dec = crypto.decrypt(enc)
    print(f"\nOriginal:  {msg}")
    print(f"Encrypted: {enc.hex()}")
    print(f"Decrypted: {dec}")
    print(f"Roundtrip: {msg == dec}")

    # Test encrypt then decrypt without reset (continuous stream)
    crypto2 = RokCrypto(0x11223344)
    enc2 = crypto2.encrypt(msg)
    dec2 = crypto2.decrypt(enc2)
    print(f"Continuous: {msg == dec2}")

    # Test server response decryption scoring
    print("\n--- Server response decryption test ---")
    fake_response = b'\x08\x0e\x12\x04test\x1a\x08response'
    for candidate in [0x11223344, 0xDEADBEEF, 0x12345678]:
        result = test_decrypt_server_response(fake_response, candidate)
        print(f"  seed=0x{candidate:08x} score={result['score']} "
              f"reasons={result['reasons']} ascii={result['ascii_preview'][:30]}")
