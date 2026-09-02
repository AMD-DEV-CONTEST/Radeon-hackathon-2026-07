import re
from pathlib import Path

WHITELISTS = {
    '/workspace/fix_retrain_engineer.py': [
        'determinex_v1_distilled_claude.jsonl',
        'determinex_v1_distilled_gemini.jsonl',
        'determinex_v1_targeted_gaps.jsonl',
        'gap_v3_arc_mutex.jsonl',
        'gap_v3_go_panic.jsonl',
    ],
    '/workspace/fix_retrain_observer.py': [
        'determinex_v1_distilled_claude.jsonl',
        'determinex_v1_distilled_gemini.jsonl',
        'determinex_v1_distilled_observer.jsonl',
        'gap_v3_arc_mutex.jsonl',
        'gap_v4_observer_specific.jsonl',
    ],
    '/workspace/fix_retrain_sentinel.py': [
        'determinex_v1_distilled_claude.jsonl',
        'determinex_v1_distilled_gemini.jsonl',
        'determinex_v1_targeted_gaps.jsonl',
        'gap_v3_arc_mutex.jsonl',
        'gap_v4_sentinel_specific.jsonl',
    ],
}

BAD = 'for f in sorted(DATA_DIR.glob(""*.jsonl"")):'

for path, wl in WHITELISTS.items():
    p = Path(path)
    src = p.read_text()
    if BAD not in src:
        print(f'[WARN] pattern not found in {p.name}')
        continue
    lines = chr(10).join(f'        ""{f}"",' for f in wl)
    repl = f'WHITELIST = [{chr(10)}{lines}{chr(10)}    ]{chr(10)}    for fname in WHITELIST:{chr(10)}        f = DATA_DIR / fname{chr(10)}        if not f.exists():{chr(10)}            print(f""  [WARN] Missing: {{f}}"", flush=True){chr(10)}            continue'
    src = src.replace(BAD, repl)
    p.write_text(src)
    print(f'[OK] Patched {p.name} with {len(wl)}-file whitelist')
print('Done.')
