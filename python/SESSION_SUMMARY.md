=== SESSION SUMMARY ===

## Major Breakthrough: CRYPTO VERIFIED

**The full LFSR stream cipher implementation is 100% correct!**
- Python `RokCrypto(seed)` generates keystream matching real game data
- Verified against capture: seed 0x168101d6 → all 555 bytes of keystream match
- Two states: State1 (seed1) for OUTGOING, State2 (seed2) for INCOMING

## New Capabilities

### Working XOR Capture (epilogue hook at 0x2ace)
- Reliably captures plaintext/ciphertext pairs at scale (382 calls in 45s)
- Uses entry hook (0x2975) to save "before" data keyed by state ptr
- Uses epilogue hook (0x2ace) to read "after" data when XOR completes
- Works around Frida onLeave bug that affects functions with non-standard calling conventions

### Reliable Game Launch (SendMessage approach)
- PostMessage/SendMessage click is MORE reliable than cursor-based clicks
- Sends WM_LBUTTONDOWN/WM_LBUTTONUP directly to the launcher window
- Bypasses window focus issues

### Key Findings about Protocol
- **Greeting does NOT go through XOR** - it's plaintext inside TLS
- Two LFSR states: seed1 for send, seed2 for receive
- Plaintext is protobuf with field 1 = message type (varint), field 2 = payload
- Keepalive: `08 09 12 00` (field1=9, empty field2)
- Seeds come from game state (sub_B9850 variant arrays), NOT from greeting nonce
- Seeds change every session

## Remaining Unknowns

### Seed Derivation Formula
- Seeds are read from variant arrays at [[obj+0x20] + (channel-1) * 16]
- The SOURCE of these variant values is unknown
- Seeds are NOT derived from the greeting nonce
- Need to trace write-access to the variant arrays to find the source

### Bot Implementation Gap
- Without knowing seed derivation, bot can only work via Frida seed capture
- Standalone bot needs to either:
  1. Find and replicate seed derivation
  2. Override game memory to use known seeds
  3. Run alongside Frida for seed capture
- AND implement TLS connection + greeting receive + protocol messages

## Files Created/Updated
- `_capture_xor_v2.py` - XOR capture using epilogue hook (WORKING)
- `_capture_greeting.py` - Fresh game launch + capture (greeting doesn't go through XOR)
- `_fast_capture.py` - 50ms Frida polling + capture
- `_uber_capture.py` - Mega script: launch + click + capture
- `_keyboard_capture.py` - Keyboard-based click + capture
- `_sendmsg_click.py` - SendMessage click (MOST RELIABLE)
- `_simple_capture.py` - Capture by PID (simplest)
- `_verify_crypto.py` - Crypto verification script (CONFIRMED)
- `_analyze_xor.py` - Protocol analysis
- `_read_nonce.py` - Read nonce from state (found 2 states with different identifiers)

## Files Not Modified
- `crypto_module.py` - already correct!
- `headless_client.py` - needs TLS + seed integration
