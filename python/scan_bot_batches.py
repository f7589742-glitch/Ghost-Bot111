import json, binascii, zlib, struct, sys
sys.path.insert(0, '.')
from headless_client import ProtobufCodec

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

def extract_posid(blob, out, depth=0):
    """Extract records of form {1: posmsg, 2: id} recursively."""
    try:
        m = parse_msg(blob)
    except Exception:
        return
    for f, t, v in m:
        if t == 'bytes':
            if f == 1:
                sub = parse_msg(v)
                pos = None
                for f2, t2, v2 in sub:
                    if f2 == 1 and t2 == 'f32':
                        pos = (pos or [None, None])
                    if f2 == 2 and t2 == 'f32':
                        pass
                # simpler: check for id on sibling
            extract_posid(v, out, depth+1)

def records_of(blob):
    """Parse a repeated-f1 entity blob; each record {1: posmsg, 2: id}."""
    ents = []
    i = 0
    while i < len(blob):
        tag, i2 = rd_varint(blob, i)
        field, wt = tag >> 3, tag & 7
        if wt != 2:
            i = i2
            continue
        ln, i3 = rd_varint(blob, i2)
        ents.append(blob[i3:i3+ln])
        i = i3 + ln
    out = []
    for e in ents:
        m = parse_msg(e)
        ent_id = None
        pos = None
        for f, t, v in m:
            if f == 1 and t == 'bytes':
                pm = parse_msg(v)
                fx = [x for a, b, x in pm if a == 1 and b == 'f32']
                fy = [x for a, b, x in pm if a == 2 and b == 'f32']
                if fx and fy:
                    pos = (round(fx[0], 1), round(fy[0], 1))
            if f == 2 and t == 'varint':
                ent_id = v
        out.append((ent_id, pos))
    return out

d = json.load(open('bot_session_log.json'))
for t, op, hx in d:
    if op != 9999:
        continue
    raw = binascii.unhexlify(hx)
    pf = ProtobufCodec.decode_message(raw)
    data = pf.get(2, b'')
    outer = ProtobufCodec.decode_message(data)
    for k, v in outer.items():
        if not isinstance(v, bytes):
            continue
        for wbits in (15, -15):
            try:
                dc = zlib.decompress(v, wbits)
                break
            except Exception:
                dc = None
        if dc is None:
            continue
        print('=== 9999 batch: decompressed %d bytes ===' % len(dc))
        m = parse_msg(dc)
        for f, t, v in m:
            if t == 'varint':
                print('  marker field%d = %d' % (f, v))
            if t == 'bytes':
                sub = parse_msg(v)
                print('  field%d msg: %d fields' % (f, len(sub)))
                for f2, t2, v2 in sub:
                    if t2 == 'varint':
                        print('    f%d = %d' % (f2, v2))
                    elif t2 == 'bytes':
                        recs = records_of(v2)
                        nrec = len(recs)
                        print('    f%d blob %dB, %d records' % (f2, len(v2), nrec))
                        for rid, pos in recs[:6]:
                            print('      id=%-10s pos=%s' % (rid, pos))
        print()
