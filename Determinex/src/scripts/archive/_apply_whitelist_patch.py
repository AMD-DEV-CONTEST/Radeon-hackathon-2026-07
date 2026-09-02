from pathlib import Path

# Per-model whitelists - explicit ownership, no globs ever
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

# Old bad pattern (top-level, no indent)
BAD = 'for f in sorted(DATA_DIR.glob("*.jsonl")):'

for path, wl in WHITELISTS.items():
    p = Path(path)
    src = p.read_text()

    # First undo any previous broken patch attempt
    # Remove indented WHITELIST block that was incorrectly inserted
    import re
    src = re.sub(
        r'# LOCKED WHITELIST.*?for fname in WHITELIST:\n        f = DATA_DIR / fname\n        if not f\.exists\(\):\n            print\(f"  \[WARN\] Missing: \{f\}", flush=True\)\n            continue',
        BAD,
        src,
        flags=re.DOTALL
    )

    if BAD not in src:
        print(f'[WARN] bad pattern still not found in {p.name} after undo')
        print(repr(src[4000:4300]))
        continue

    file_list = '\n'.join(f'    "{f}",' for f in wl)
    repl = (
        '# LOCKED WHITELIST - never use glob("*.jsonl") here\n'
        'WHITELIST = [\n'
        f'{file_list}\n'
        ']\n'
        'for fname in WHITELIST:\n'
        '    f = DATA_DIR / fname\n'
        '    if not f.exists():\n'
        '        print(f"  [WARN] Missing whitelist file: {f}", flush=True)\n'
        '        continue'
    )
    src = src.replace(BAD, repl, 1)
    p.write_text(src)
    print(f'[OK] Patched {p.name} with {len(wl)}-file whitelist')

print('Done.')
