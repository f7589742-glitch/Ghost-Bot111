import struct, sys, os, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_module import RokCrypto
from headless_client import ProtobufCodec

PCAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'game_capture.pcap')

with open(PCAP, 'rb') as f:
    data = f.read()

offset = 24
packets = []
while offset < len(data):
    if offset + 16 > len(data):
        break
    ts_sec, ts_usec, incl_len, orig_len = struct.unpack('<IIII', data[offset:offset+16])
    offset += 16
    pkt = data[offset:offset+incl_len]
    offset += incl_len
    if len(pkt) < 20:
        continue
    if struct.unpack('>H', pkt[0:2])[0] != 0x0800:
        continue
    ip_start = 20
    if ip_start + 20 > len(pkt):
        continue
    ip_header = pkt[ip_start:]
    ihl = (ip_header[0] & 0x0F) * 4
    if ip_header[9] != 6:
        continue
    tcp_start = ip_start + ihl
    if tcp_start + 20 > len(pkt):
        continue
    tcp_header = pkt[tcp_start:]
    src_port = struct.unpack('>H', tcp_header[0:2])[0]
    dst_port = struct.unpack('>H', tcp_header[2:4])[0]
    doff = ((tcp_header[12] >> 4) & 0xF) * 4
    tcp_data = tcp_header[doff:]
    if len(tcp_data) == 0 or (src_port != 3101 and dst_port != 3101):
        continue
    packets.append({
        'ts': ts_sec + ts_usec / 1e6,
        'dir': 'S->C' if src_port == 3101 else 'C->S',
        'cport': dst_port if src_port == 3101 else src_port,
        'data': tcp_data,
    })

# Parse frames per direction with timestamps
def parse_frames(stream_data, seed, start_offset, skip_greeting):
    frames = []
    pos = start_offset
    fnum = 0
    while pos + 2 <= len(stream_data):
        fl = (stream_data[pos] << 8) | stream_data[pos+1]
        if fl == 0 or pos + 2 + fl > len(stream_data):
            break
        payload = stream_data[pos+2:pos+2+fl]
        pos += 2 + fl
        fnum += 1
        try:
            dec = seed.decrypt(payload)
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            dataf = pf.get(2, b'')
            frames.append((fnum, op, dataf))
        except:
            frames.append((fnum, None, b''))
    return frames

# Build frame list with timestamps for main connection (cport 37870)
crypto_tx = RokCrypto(135717691)
crypto_rx = RokCrypto(851565604)

main_c2s = []
main_s2c = []
for p in packets:
    if p['cport'] != 37870:
        continue
    (main_c2s if p['dir'] == 'C->S' else main_s2c).append(p)

# Concatenate per-direction preserving packet order, track ts per byte range
def stream_ts(frames_pkts):
    out = b''
    ts_map = []  # (ts, start, end)
    for p in frames_pkts:
        start = len(out)
        out += p['data']
        ts_map.append((p['ts'], start, len(out)))
    return out, ts_map

c2s_data, c2s_map = stream_ts(main_c2s)
s2c_data, s2c_map = stream_ts(main_s2c)

# For each direction, track frame start position and compute ts
def parse_with_ts(data, ts_map, seed, start_offset):
    frames = []
    pos = start_offset
    fnum = 0
    mi = 0
    while pos + 2 <= len(data):
        fl = (data[pos] << 8) | data[pos+1]
        if fl == 0 or pos + 2 + fl > len(data):
            break
        end = pos + 2 + fl
        ts = None
        for i in range(mi, len(ts_map)):
            if ts_map[i][1] <= pos < ts_map[i][2]:
                ts = ts_map[i][0]
                mi = i
                break
        payload = data[pos+2:end]
        pos = end
        fnum += 1
        try:
            dec = seed.decrypt(payload)
            pf = ProtobufCodec.decode_message(dec)
            op = pf.get(1, 0)
            dataf = pf.get(2, b'')
            frames.append((ts, fnum, op, dataf))
        except:
            frames.append((ts, fnum, None, b''))
    return frames

c_frames = parse_with_ts(c2s_data, c2s_map, crypto_tx, 0)
s_frames = parse_with_ts(s2c_data, s2c_map, crypto_rx, 19)

# Merge and sort by timestamp
events = []
for ts, fnum, op, dataf in c_frames:
    if op is not None and op != 9:
        events.append((ts, 'C', fnum, op, dataf))
for ts, fnum, op, dataf in s_frames:
    if op is not None and op != 8003:
        events.append((ts, 'S', fnum, op, dataf))
events.sort(key=lambda e: e[0] if e[0] else 0)

def time_str(ts):
    import datetime
    base = int(ts)
    rem = int((ts - base) * 1000)
    dt = datetime.datetime.utcfromtimestamp(base)
    return dt.strftime('%H:%M:%S') + ".%03d" % rem

def summarize(op, dataf):
    if not isinstance(dataf, bytes) or len(dataf) == 0:
        return ""
    try:
        inner = ProtobufCodec.decode_message(dataf)
        if op == 105:
            return "TROOPS=" + repr([inner.get(k) if not isinstance(inner.get(k), bytes) else inner.get(k).hex() for k in sorted(inner.keys())])
        parts = []
        for k, v in sorted(inner.items()):
            if isinstance(v, bytes):
                if len(v) <= 24:
                    parts.append("f%d: %s" % (k, v.hex()))
                else:
                    parts.append("f%d: (%dB)" % (k, len(v)))
            else:
                parts.append("f%d: %s" % (k, v))
        return "{%s}" % ", ".join(parts)
    except:
        return dataf.hex()[:60]

print("=== FULL TIMELINE (main conn 37870) ===")
for ts, d, fnum, op, dataf in events:
    t = time_str(ts) if ts else "?????"
    info = summarize(op, dataf)
    if op in (1, 2, 5, 6, 8, 52, 105, 106, 107, 110, 120, 123, 125, 161, 170, 203, 205, 250, 300, 306, 366, 423, 502, 532, 600, 602, 925, 9402, 1004, 1012, 1050, 1176, 1202, 1283, 2063, 3000, 3151, 7903, 7914, 7920, 7926, 7938, 7995, 8035, 8037, 8048, 8050, 9999):
        print("%s %s f%-4d op=%-5d len=%-5d %s" % (t, d, fnum, op, len(dataf) if isinstance(dataf, bytes) else 0, info))
    else:
        print("%s %s f%-4d op=%-5d len=%-5d" % (t, d, fnum, op, len(dataf) if isinstance(dataf, bytes) else 0))
