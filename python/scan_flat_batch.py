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
crypto = RokCrypto(851565604)

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

def parse_msg(b, depth=0):
    fields = []
    i = 0
    while i < len(b):
        tag, i = rd_varint(b, i)
        field, wt = tag >> 3, tag & 7
        if wt == 2:
            ln, i = rd_varint(b, i)
            data = b[i:i+ln]; i += ln
            fields.append((field, 'bytes', data))
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

def decode_payload(payload):
    """Full decode of an op frame payload (opcode in f1, data in f2)."""
    return parse_msg(payload)

for fidx in (339, 368, 341):
    dec = None
    for idx in range(2, fidx+1):
        dec = crypto.decrypt(sf[idx-1])
    pf = parse_msg(dec)
    op = next((v for f, t, v in pf if f == 1 and t == 'varint'), None)
    data = next((v for f, t, v in pf if f == 2), b'')
    outer = parse_msg(data)
    d = None
    for f, t, v in outer:
        if t == 'bytes':
            d = try_decomp(v)
            if d:
                break
    if d is None:
        continue
    print('=== f%d op=%s decompressed %d bytes head=%s ===' % (fidx, op, len(d), d[:12].hex()))
    top = parse_msg(d)
    for f, t, v in top:
        if t == 'bytes':
            m = parse_msg(v)
            print('  top f%d: msg with %d fields' % (f, len(m)))
            for f2, t2, v2 in m:
                if t2 == 'bytes' and f2 == 2:
                    blob = v2
                    print('    f2 = entity blob %d bytes' % len(blob))
                    ents = []
                    i = 0
                    while i < len(blob):
                        tag, i2 = rd_varint(blob, i)
                        field, wt = tag >> 3, tag & 7
                        if wt != 2: break
                        ln, i3 = rd_varint(blob, i2)
                        ents.append(blob[i3:i3+ln])
                        i = i3 + ln
                    print('    entities: %d' % len(ents))
                    n_nodes = 0
                    for e in ents[:12]:
                        ef = parse_msg(e)
                        pos = None
                        ent_id = None
                        for ef2, et2, ev2 in ef:
                            if ef2 == 1 and et2 == 'bytes':
                                pv = parse_msg(ev2)
                                fx = [x for a, b, x in pv if a == 1 and b == 'f32']
                                fy = [x for a, b, x in pv if a == 2 and b == 'f32']
                                if fx and fy:
                                    pos = (round(fx[0], 1), round(fy[0], 1))
                            if ef2 == 2 and et2 == 'varint':
                                ent_id = ev2
                        if ent_id == 4138906 or pos:
                            print('      id=%-9d pos=%s' % (ent_id, pos))
                            if ent_id == 4138906:
                                n_nodes += 1
                    print('    node-4138906 count in first 12:', n_nodes)
                elif t2 == 'varint':
                    print('    f2 varint = %d' % v2)
