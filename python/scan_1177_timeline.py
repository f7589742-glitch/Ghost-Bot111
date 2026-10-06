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
        pkts.append((ts_sec + ts_usec/1e6, pkt))
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
streams = collections.defaultdict(lambda: {'c': [], 's': []})
for ts, pkt in pkts:
    ports, payload = payload_of(pkt)
    if ports is None or not payload:
        continue
    sport, dport = ports
    if dport == 3101:
        streams[sport]['c'].append((ts, payload))
    elif sport == 3101:
        streams[dport]['s'].append((ts, payload))

def split_frames(segments):
    """Return list of (ts, frame) in stream order."""
    buf = b''
    out = []
    for ts, seg in segments:
        buf += seg
        while len(buf) >= 2:
            ln = struct.unpack('>H', buf[:2])[0]
            if ln == 0 or len(buf) < 2 + ln:
                break
            out.append((ts, buf[2:2+ln]))
            buf = buf[2+ln:]
    return out

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
    if not b:
        return []
    fields = []
    i = 0
    while i < len(b):
        try:
            tag, i = rd_varint(b, i)
        except IndexError:
            break
        field, wt = tag >> 3, tag & 7
        if wt == 2:
            try:
                ln, i = rd_varint(b, i)
            except IndexError:
                break
            if i + ln > len(b):
                break
            fields.append((field, 'bytes', b[i:i+ln])); i += ln
        elif wt == 0:
            try:
                v, i = rd_varint(b, i)
            except IndexError:
                break
            fields.append((field, 'varint', v))
        else:
            break
    return fields

def frame_op(dec):
    pf = parse_msg(dec)
    return next((v for f, t, v in pf if f == 1 and t == 'varint'), 0)

def batch_markers(dec):
    try:
        if frame_op(dec) != 9999:
            return None
        data = next((v for f, t, v in parse_msg(dec) if f == 2 and t == 'bytes'), b'')
        outer = parse_msg(data)
        for f, t, v in outer:
            if t == 'bytes':
                d = try_decomp(v)
                if d:
                    m = parse_msg(d)
                    markers = []
                    for f2, t2, v2 in m:
                        if t2 == 'bytes':
                            sub = parse_msg(v2)
                            markers += [v3 for f3, t3, v3 in sub if f3 == 1 and t3 == 'varint']
                    return markers
    except Exception:
        pass
    return None

# decode both directions
s_events = []  # (ts, 'S', num, info)
c_events = []
s_num = 0
c_num = 0

def main():
    for cport, segs in streams.items():
        s_frames = split_frames(segs['s'])
        if not s_frames:
            continue
        if s_frames[0][1][:1] != b'\x08':
            continue  # not the protobuf game connection
        c_frames = split_frames(segs['c'])
        crypto_s = RokCrypto(851565604)
        crypto_c = RokCrypto(135717691)
        s_events = []
        s_num = 0
        c_num = 0
        for ts, fr in s_frames:
            if s_num == 0:
                s_num += 1
                continue  # greeting
            s_num += 1
            dec = crypto_s.decrypt(fr)
            markers = batch_markers(dec)
            if markers is not None and 1177 in markers:
                s_events.append((ts, 'S', s_num, 'BATCH1177'))
        for ts, fr in c_frames:
            c_num += 1
            try:
                dec = crypto_c.decrypt(fr)
                op = frame_op(dec)
            except Exception:
                op = -1
            if op in (1004, 1050, 1012, 1051, 925, 1020, 120, 1224) or (op == -1 and c_num < 6):
                s_events.append((ts, 'C', c_num, 'op=%d' % op))

        s_events.sort(key=lambda x: x[0])
        print('cport %s events around BATCH1177:' % cport)
        for i, ev in enumerate(s_events):
            if ev[3] == 'BATCH1177':
                for e in s_events[max(0, i-14):i+1]:
                    print('%.3f  %s f%-4d %s' % e)


if __name__ == '__main__':
    main()
