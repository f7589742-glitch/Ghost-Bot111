import sys, struct, collections, zlib
sys.path.insert(0, '.')
from headless_client import ProtobufCodec
from crypto_module import RokCrypto

def parse_pcap(path):
    data = open(path, 'rb').read()
    off = 24; pkts = []
    while off + 16 <= len(data):
        ts_sec, ts_usec, caplen, origlen = struct.unpack('<IIII', data[off:off+16])
        pkt = data[off+16:off+16+caplen]; off += 16 + caplen
        pkts.append(pkt)
    return pkts

def payload_of(pkt):
    i = 0
    while i < len(pkt) - 20:
        if pkt[i] == 0x45 and pkt[i+9] == 6:
            ihl = (pkt[i] & 0xf) * 4
            tcp_off = i + ihl + ((pkt[i+ihl+12] >> 4) * 4)
            return struct.unpack('>HH', pkt[i+ihl:i+ihl+4]), pkt[tcp_off:]
        i += 1
    return None, b''

pkts = parse_pcap(r'D:\aa\Headless Bot RoK\game_capture.pcap')
streams = collections.defaultdict(bytes)
for pkt in pkts:
    ports, payload = payload_of(pkt)
    if ports:
        streams[ports] += payload

def split(buf):
    frames = []
    while len(buf) >= 2:
        ln = struct.unpack('>H', buf[:2])[0]
        if len(buf) < 2 + ln: break
        frames.append(buf[2:2+ln]); buf = buf[2+ln:]
    return frames

sf = split(streams[(3101, 37870)])
cf = split(streams[(37870, 3101)])
crypto_s = RokCrypto(851565604)
crypto_c = RokCrypto(135717691)

def try_decomp(b):
    for wbits in (15, -15):
        try:
            return zlib.decompress(b, wbits)
        except Exception:
            pass
    return None

def rd_varint(b, i):
    v = 0; shift = 0
    while True:
        byte = b[i]; i += 1
        v |= (byte & 0x7f) << shift
        if not byte & 0x80: break
        shift += 7
    return v, i

def parse_msg(b):
    fields = []
    i = 0
    while i < len(b):
        tag, i = rd_varint(b, i)
        field, wt = tag >> 3, tag & 7
        if wt == 2:
            ln, i = rd_varint(b, i)
            fields.append((field, 'bytes', b[i:i+ln])); i += ln
        elif wt == 0:
            v, i = rd_varint(b, i)
            fields.append((field, 'varint', v))
        elif wt == 5:
            fields.append((field, 'f32', struct.unpack('<f', b[i:i+4])[0])); i += 4
        elif wt == 1:
            fields.append((field, 'f64', b[i:i+8])); i += 8
        else:
            break
    return fields

# server frames: op + marker1177 info
s_info = []
for i, fr in enumerate(sf):
    if i == 0:
        s_info.append((i+1, 8562, None, None))
        continue
    dec = crypto_s.decrypt(fr)
    pf = parse_msg(dec)
    op = next((v for f, t, v in pf if f == 1 and t == 'varint'), 0)
    data = next((v for f, t, v in pf if f == 2 and t == 'bytes'), b'')
    marker = None
    nodes = None
    if op == 9999:
        outer = parse_msg(data)
        for f, t, v in outer:
            if t == 'bytes':
                d = try_decomp(v)
                if d:
                    m = parse_msg(d)
                    for f2, t2, v2 in m:
                        if t2 == 'bytes':
                            sub = parse_msg(v2)
                            for f3, t3, v3 in sub:
                                if f3 == 1 and t3 == 'varint':
                                    marker = v3
                                if f3 == 2 and t3 == 'bytes':
                                    b2 = v3
                                    if b2 and b2[0] == 0x0a:
                                        n = b2.count(b'\x0a')
                                        nodes = n
    s_info.append((i+1, op, marker, nodes))

# client frames: op only
c_ops = []
for i, fr in enumerate(cf):
    dec = crypto_c.decrypt(fr)
    pf = parse_msg(dec)
    op = next((v for f, t, v in pf if f == 1 and t == 'varint'), 0)
    c_ops.append((i+1, op))

# interleave by index proportionally: assume c_i aligns near s ~ i (rough)
print('server frames with marker batches:')
for n, op, marker, nodes in s_info:
    if marker is not None and marker == 1177:
        print('  S f%d op=%d marker=1177 entities=%s' % (n, op, nodes))
print()
print('node-list batches (marker 1177) timeline vs client moves:')
for n, op, marker, nodes in s_info:
    if marker == 1177:
        # find client ops around this server frame (client ~ same count)
        around = [op for _, op in c_ops[n-3:n+1]]
        print('  S f%-4d after C ops %s' % (n, around))
