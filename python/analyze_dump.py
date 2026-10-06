import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from headless_client import ProtobufCodec

D = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'game_dump.json')))

resources = {1: 'Food', 2: 'Wood', 3: 'Stone', 5: 'Gold'}
for e in D:
    if e.get('op') == 121 and 'd' in e:
        entries = e['d'].get('1', [])
        if isinstance(entries, list):
            print('=== Resources ===')
            for entry in entries:
                if isinstance(entry, str):
                    raw = entry.encode('utf-8').decode('unicode_escape').encode('latin-1')
                    inner = ProtobufCodec.decode_message(raw)
                    rid = inner.get(1, '?')
                    ramount = inner.get(2, 0)
                    rname = resources.get(rid, 'type_%s' % rid)
                    print('  %s = %d' % (rname, ramount))

for e in D:
    if e.get('op') == 9999 and 'd' in e:
        d = e['d']
        if '1' in d and isinstance(d['1'], list):
            for entry in d['1']:
                if isinstance(entry, dict) and '2' in entry:
                    profile = entry.get('2', {})
                    if isinstance(profile, dict):
                        print()
                        print('=== Player Profile ===')
                        print('  Player ID: %s' % profile.get('1'))
                        print('  Kingdom: %s' % profile.get('2'))
                        print('  Power: %s' % profile.get('6'))
                        print('  VIP: %s' % profile.get('34'))
                        name_raw = profile.get('5', '')
                        print('  Name raw: %s' % repr(name_raw))
                        print('  Alliance: %s' % profile.get('32'))

for e in D:
    op = e.get('op')
    if op not in [54, 8003, 8563, 4608, 125, 9717, 8703, 1890, 1980, 601, 9100, 6005, 7994, 1429, 8103, 8600, 7922, 7943]:
        print()
        print('=== Response op=%d ===' % op)
        if 'd' in e:
            print('  data:', json.dumps(e['d'], default=str)[:300])
        if 'r' in e:
            print('  raw:', e['r'][:100])
