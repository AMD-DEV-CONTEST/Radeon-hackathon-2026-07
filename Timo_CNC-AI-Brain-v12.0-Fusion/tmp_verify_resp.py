# -*- coding: utf-8 -*-
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

d = json.load(open('tmp_resp_chat.json', encoding='utf-8'))
print('== TOP-LEVEL KEYS ==')
print(sorted(d.keys()))

reply = d.get('reply') or d.get('message') or ''
print('\n== REPLY TEXT ==')
print(reply[:1500])

ps = d.get('part_spec')
print('\n== part_spec ==')
print(json.dumps(ps, ensure_ascii=False)[:2000] if ps else 'MISSING')
if isinstance(ps, dict):
    params = ps.get('params') or ps
    print('params:', json.dumps(params, ensure_ascii=False)[:1500])

tot = d.get('cad_tot_chain')
print('\n== cad_tot_chain ==')
if tot is None:
    print('MISSING')
else:
    s = json.dumps(tot, ensure_ascii=False)
    print('len:', len(s))
    print(s[:3000])
    if len(s) > 3000:
        print('...(truncated tail)')
        print(s[-1500:])

rc = d.get('cad_reasoning_chain')
print('\n== cad_reasoning_chain ==')
if rc is None:
    print('MISSING')
else:
    s = json.dumps(rc, ensure_ascii=False)
    print('len:', len(s))
    print(s[:2500])

print('\n== EXISTING FIELDS ==')
for k in ('reasoning_chain', 'step_path', 'volume', 'volume_cm3', 'volume_report', 'cad_volume', 'quote', 'cad_command'):
    if k in d:
        v = d[k]
        s = json.dumps(v, ensure_ascii=False)
        print(k, '=>', s[:600])
    else:
        print(k, '=> MISSING')
