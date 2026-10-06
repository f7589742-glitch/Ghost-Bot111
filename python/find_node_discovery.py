"""
find_node_discovery.py — Find how the client learns resource-node (type 1027) entity ids.

Usage: python find_node_discovery.py <pcap_or_pcapng>
Supports both classic pcap and pcapng (Wireshark default).

Strategy:
1. Parse all TCP streams to port 3101, group by client port.
2. For the connection whose server stream starts with a protobuf greeting (op=8562),
   derive seeds and decrypt ALL frames (must decrypt every frame to keep keystream in sync).
3. Find the FIRST 9999 batch containing an entity of type 1027 (resource node).
4. Print every client opcode sent before that moment (with payloads), and the server
   frames in the same window, so the discovery command sequence is visible.
"""

import struct, sys, os, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec

PCAP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'game_capture.pcap')
LIMIT_STR = int(os.environ.get('DISCOVERY_PRE_WINDOW', '60'))

# ---------------- pcap/pcapng parsing ----------------

def parse_blocks_pcap(data):
    """Classic pcap: 24-byte global header then records."""
    recs = []
    offset = 24
    while offset + 16 <= len(data):
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack('<IIII', data[offset:offset+16])
        offset += 16
        if offset + incl_len > len(data):
            break
        recs.append((ts_sec + ts_usec / 1e6, data[offset:offset+incl_len]))
        offset += incl_len
    return recs

def parse_blocks_pcapng(data):
    """pcapng: Section Header Block then Interface/Enhanced Packet blocks."""
    recs = []
    offset = 0
    while offset + 12 <= len(data):
        btype, blen = struct.unpack('<II', data[offset:offset+8])
        if blen < 12 or offset + blen > len(data):
            break
        body = data[offset+8:offset+blen-4]  # minus trailing CRC
        if btype == 0x0A0D0D0A:  # SHB
            pass
        elif btype == 0x00000006:  # EPB
            if len(body) >= 20:
                iface, hi, lo, caplen = struct.unpack('<IIII', body[:16])
                recs.append((hi * 2**32 + lo, body[20:20+caplen]))
        elif btype == 0x00000003:  # SPB (obsolete, rarely used)
            if len(body) >= 8:
                recs.append((0, body[8:]))
        offset += blen
        if blen % 4:
            offset += 4 - (blen % 4)
    return recs

def get_packets(path):
    with open(path, 'rb') as f:
        data = f.read()
    if data[:4] == b'\x0a\x0d\x0d\x0a':
        recs = parse_blocks_pcapng(data)
    else:
        recs = parse_blocks_pcap(data)
    pkts = []
    for ts, pkt in recs:
        if len(pkt) < 20:
            continue
        if struct.unpack('>H', pkt[0:2])[0] != 0x0800:
            continue
        ip_header = pkt[20:]
        if ip_header[9] != 6:
            continue
        tcp_start = 20 + (ip_header[0] & 0x0F) * 4
        tcp_header = pkt[tcp_start:]
        if tcp_start + 20 > len(pkt):
            continue
        src_port = struct.unpack('>H', tcp_header[0:2])[0]
        dst_port = struct.unpack('>H', tcp_header[2:4])[0]
        doff = ((tcp_header[12] >> 4) & 0xF) * 4
        tcp_data = tcp_header[doff:]
        if not tcp_data:
            continue
        pkts.append((ts, 'S->C' if src_port == 3101 else 'C->S',
                     dst_port if src_port == 3101 else src_port, tcp_data))
    return pkts

# ---------------- frame parsing ----------------

def parse_frames(stream, start):
    frames = []
    spos = start
    while spos + 2 <= len(stream):
        fl = (stream[spos] << 8) | stream[spos+1]
        if fl == 0 or spos + 2 + fl > len(stream):
            break
        frames.append(stream[spos+2:spos+2+fl])
        spos += 2 + fl
    return frames

def try_greeting(frames):
    """Return (sub1, sub2) if first frame is a greeting (op=8562)."""
    if not frames:
        return None
    try:
        pf = ProtobufCodec.decode_message(frames[0])
        if pf.get(1) == 8562:
            inner = ProtobufCodec.decode_message(pf.get(2, b''))
            return inner.get(1, 0), inner.get(2, 0)
    except Exception:
        pass
    return None

def derive_seed(sub1, sub2):
    seed_tx = ((sub2 // 3) + 0x2766) & 0x3fffffff
    seed_rx = ((sub1 >> 1) + 0x400) & 0x3fffffff
    return seed_tx, seed_rx

def f32(i):
    return struct.unpack('<f', struct.pack('<I', i))[0]

def deep(v, indent=0):
    pad = "  " * indent
    if isinstance(v, bytes):
        try:
            inner = ProtobufCodec.decode_message(v)
            out = {}
            for k, sv in inner.items():
                out[k] = deep(sv, indent+1)
            return out
        except:
            try:
                s = v.decode('utf-8')
                if len(s) > 0 and all(32 <= ord(c) < 127 for c in s):
                    return s
            except:
                pass
            if len(v) <= 16:
                return v.hex()
            return "(%dB)" % len(v)
    return v

def entity_types_of_9999(dec):
    """Return list of entity types inside a 9999 frame, or None if not 9999."""
    try:
        pf = ProtobufCodec.decode_message(dec)
        if pf.get(1) != 9999:
            return None
        outer = ProtobufCodec.decode_message(pf.get(2, b''))
        dc = zlib.decompress(outer.get(2, b''))
        inner = ProtobufCodec.decode_message(dc)
        ents = inner.get(1, [])
        types = []
        for e in ents:
            try:
                ie = ProtobufCodec.decode_message(e)
                types.append(ie.get(1))
            except:
                types.append('?')
        return types
    except Exception:
        return None

def node_entities_of_9999(dec):
    """Extract node (type 1027) ids+positions from a 9999 frame."""
    nodes = []
    try:
        pf = ProtobufCodec.decode_message(dec)
        if pf.get(1) != 9999:
            return nodes
        outer = ProtobufCodec.decode_message(pf.get(2, b''))
        dc = zlib.decompress(outer.get(2, b''))
        inner = ProtobufCodec.decode_message(dc)
        ents = inner.get(1, [])
        for e in ents:
            try:
                ie = ProtobufCodec.decode_message(e)
                if ie.get(1) != 1027:
                    continue
                d2 = ProtobufCodec.decode_message(ie.get(2, b''))
                blob = d2.get(1, b'')
                if not isinstance(blob, bytes):
                    continue
                bd = ProtobufCodec.decode_message(blob)
                f1 = bd.get(1, b'')
                f1d = ProtobufCodec.decode_message(f1)
                nid = f1d.get(1)
                p = f1d.get(3)
                pos = None
                if isinstance(p, bytes):
                    pp = ProtobufCodec.decode_message(p)
                    pos = (round(f32(pp.get(1, 0)), 2), round(f32(pp.get(2, 0)), 2))
                nodes.append((nid, pos))
            except Exception:
                pass
    except Exception:
        pass
    return nodes

# ---------------- main ----------------

packets = get_packets(PCAP)
print("file: %s" % PCAP)
print("TCP packets to/from :3101: %d" % len(packets))

streams = {}
for ts, d, cport, tcp_data in packets:
    streams.setdefault(cport, {'S2C': b'', 'C2S': b'', 'n_s': 0, 'n_c': 0})
    if d == 'S->C':
        streams[cport]['S2C'] += tcp_data
    else:
        streams[cport]['C2S'] += tcp_data

print("\nconnections:")
for cport, s in sorted(streams.items()):
    print("  cport %s: S2C=%d C2S=%d" % (cport, len(s['S2C']), len(s['C2S'])))

main = None
for cport, s in sorted(streams.items()):
    sf = parse_frames(s['S2C'], 0)
    g = try_greeting(sf)
    if g:
        main = cport
        sub1, sub2 = g
        seed_tx, seed_rx = derive_seed(sub1, sub2)
        print("\nMAIN connection: cport=%s greeting sub1=%d sub2=%d seeds tx=%d rx=%d" %
              (cport, sub1, sub2, seed_tx, seed_rx))
        s['seeds'] = (seed_tx, seed_rx)
        s['greeting_len'] = len(sf[0]) + 2
        break

if main is None:
    print("No protobuf greeting found on any connection — can't decrypt.")
    sys.exit(1)

s = streams[main]
seed_tx, seed_rx = s['seeds']

# decrypt client frames
crypto_tx = RokCrypto(seed_tx)
cframes = parse_frames(s['C2S'], 0)
c_ops = []
for i, fr in enumerate(cframes):
    try:
        dec = crypto_tx.decrypt(fr)
        pf = ProtobufCodec.decode_message(dec)
        op = pf.get(1, 0)
        dataf = pf.get(2, b'')
        c_ops.append((i + 1, op, dec, dataf))
    except Exception:
        c_ops.append((i + 1, 'FAIL', None, None))

# decrypt server frames
crypto_rx = RokCrypto(seed_rx)
sframes = parse_frames(s['S2C'], s.get('greeting_len', 19))
s_ops = []
for i, fr in enumerate(sframes):
    try:
        dec = crypto_rx.decrypt(fr)
        pf = ProtobufCodec.decode_message(dec)
        s_ops.append((i + 1, pf.get(1, 0), dec))
    except Exception:
        s_ops.append((i + 1, 'FAIL', None))

print("\ntotal client frames: %d, server frames: %d" % (len(c_ops), len(s_ops)))

# find first node push
first_node = None
for i, (num, op, dec) in enumerate(s_ops):
    if op == 'FAIL':
        continue
    nodes = node_entities_of_9999(dec)
    if nodes:
        first_node = (num, op, nodes)
        break

if first_node is None:
    print("\nNO type-1027 node entity found in this capture at all.")
else:
    snum, sop, nodes = first_node
    print("\nFIRST node entity push: S f%d op=%d nodes=%s" % (snum, sop, nodes))
    print("\nTimeline: client ops with server ops, until %d frames after the node reveal:" % LIMIT_STR)

    # interleave by index, but we don't have per-frame times; print C ops
    # in order and S frames in order, aligned by count
    print("\n--- all client ops BEFORE first node push (S f%d) ---" % snum)
    for num, op, dec, dataf in c_ops:
        if op == 'FAIL':
            continue
        if op == 9:
            continue
        dd = deep(dataf) if dataf is not None else None
        s = str(dd)
        if len(s) > 220:
            s = s[:220] + "..."
        print("C f%d op=%-6d %s" % (num, op, s))

    print("\n--- all server ops BEFORE first node push ---")
    for num, op, dec in s_ops[:snum]:
        if op == 'FAIL':
            continue
        types = entity_types_of_9999(dec)
        if types is not None:
            print("S f%d op=9999 types=%s" % (num, str(types)[:150]))
        else:
            try:
                pf = ProtobufCodec.decode_message(dec)
                dataf = pf.get(2, b'')
                if op in (8003, 9, 8010):
                    continue
                dd = deep(dataf)
                s = str(dd)
                if len(s) > 180:
                    s = s[:180] + "..."
                print("S f%d op=%-6d %s" % (num, op, s))
            except Exception:
                print("S f%d UNDECODABLE" % num)

    print("\n--- first 10 server frames AFTER node reveal ---")
    for num, op, dec in s_ops[snum:snum + 10]:
        if op == 'FAIL':
            continue
        types = entity_types_of_9999(dec)
        if types is not None:
            print("S f%d op=9999 types=%s" % (num, str(types)[:150]))
        else:
            try:
                pf = ProtobufCodec.decode_message(dec)
                dd = deep(pf.get(2, b''))
                s = str(dd)
                if len(s) > 180:
                    s = s[:180] + "..."
                print("S f%d op=%-6d %s" % (num, op, s))
            except Exception:
                print("S f%d UNDECODABLE" % num)
