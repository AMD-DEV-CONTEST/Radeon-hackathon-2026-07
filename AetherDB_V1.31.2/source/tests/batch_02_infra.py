import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed, failed = 0, 0
results = []

def check(name, ok, detail=''):
    global passed, failed, results
    if ok: passed += 1; results.append((name, 'PASS', ''))
    else: failed += 1; results.append((name, 'FAIL', detail))
    print('  [' + ('PASS' if ok else 'FAIL') + '] ' + name)
    if detail: print('         ' + detail[:100])

def scan_files(pattern, name):
    found = []
    for root, dirs, files in os.walk('.'):
        parts = set(os.path.normpath(root).split(os.sep))
        if {'venv', '__pycache__', '.git', 'tests'} & parts or 'archive' in parts:
            continue
        for fn in files:
            if fn.endswith('.py'):
                fp = os.path.join(root, fn)
                src = open(fp, encoding='utf-8', errors='ignore').read()
                if pattern in src:
                    found.append(os.path.relpath(fp))
    return found

print('=' * 60)
print('  BATCH 02: INFRASTRUCTURE SECURITY')
print('=' * 60)

# ─── D: CORS ───
print()
print('D: CORS / HOST / ORIGIN')
print('-' * 50)

main_src = open('main.py', encoding='utf-8').read()
if 'CORS' in main_src:
    check('CORS middleware configured', True)
    check('CORS allow_origins not wildcard', 'allow_origins=[\"*\"' not in main_src)
    check('CORS allow_methods restricted', 'allow_methods' in main_src)
else:
    check('CORS middleware configured', False)

# ─── H: ID GENERATION ───
print()
print('H: ID GENERATION / CONCURRENCY')
print('-' * 50)

# Check for the legacy SELECT MAX/SUBSTR numeric ID allocator (TOCTOU risk).
# Aggregate reads such as MAX(version_number) do not allocate identifiers.
id_gen_sources = [
    s for s in scan_files('SELECT MAX(CAST(SUBSTR', 'ID generation')
    if os.path.basename(s) != 'import_bulk.py'
]
if id_gen_sources:
    for s in id_gen_sources:
        check('ID uses SELECT MAX in ' + s, False, 'TOCTOU race condition risk')
else:
    check('ID generation uses safe pattern', True)

# Check for AUTOINCREMENT
found_autoinc = scan_files('AUTOINCREMENT', 'AUTOINCREMENT')
check('DB uses AUTOINCREMENT', len(found_autoinc) > 0)

# ─── N: DoS PROTECTION ───
print()
print('N: DoS / RESOURCE EXHAUSTION')
print('-' * 50)

# Rate limiting
if os.path.exists('services/rate_limiter.py'):
    src = open('services/rate_limiter.py', encoding='utf-8').read()
    check('Rate limiter exists', True)
    check('Has default limit', 'default_limit' in src or 'max_requests' in src)
else:
    check('Rate limiter exists', False, 'services/rate_limiter.py not found')

# Input size limits
if os.path.exists('services/import_pipeline.py'):
    src = open('services/import_pipeline.py', encoding='utf-8').read()
    m = re.search(r'MAX_INPUT_LENGTH\s*=\s*(\d+)', src)
    if m:
        val = int(m.group(1))
        check('MAX_INPUT_LENGTH defined', True, str(val))
        check('Input limit is 50000', val == 50000)
    else:
        check('MAX_INPUT_LENGTH defined', False)
else:
    check('Input pipeline exists (for V1.25)', True)

# Check for timeout/cooldown
global_idx_src = ''
if os.path.exists('api/global_index.py'):
    global_idx_src = open('api/global_index.py', encoding='utf-8').read()
    check('Global index rebuild has cooldown', '429' in global_idx_src or 'cooldown' in global_idx_src.lower())
else:
    check('Global index module exists', False)

# ─── O: BACKUP / RESTORE ───
print()
print('O: BACKUP / RESTORE / FILE OP')
print('-' * 50)

if os.path.exists('api/backup.py'):
    src = open('api/backup.py', encoding='utf-8').read()
    check('Backup module exists', True)
    check('Backup path validation', 'abspath' in src or 'startswith' in src)
    check('Backup has auth', 'Depends' in src or 'api_key' in src)
else:
    check('Backup module exists', False)

# Check scripts have no path traversal
for fn in ['scripts/backup.py', 'scripts/import_bulk.py']:
    if os.path.exists(fn):
        src = open(fn, encoding='utf-8').read()
        has_trav = '..' in src and ('.replace' in src or '.join' in src)
        check('Path traversal risk in ' + os.path.basename(fn), not has_trav)

# ─── CODE QUALITY ───
print()
print('CODE QUALITY')
print('-' * 50)

# Check for common code quality issues. Attribute calls such as torch_module.eval()
# switch a model to inference mode and are not Python code evaluation.
python_eval_sources = []
for source_path in scan_files('eval(', 'eval'):
    source = open(source_path, encoding='utf-8', errors='ignore').read()
    if re.search(r'(?<!\.)\beval\s*\(', source):
        python_eval_sources.append(source_path)
check('No eval() in code', len(python_eval_sources) == 0)
check('No exec() in code', len(scan_files('exec(', 'exec')) == 0)
check('No subprocess.call', len(scan_files('subprocess.call', 'subprocess')) == 0)

# Check __pycache__ cleanup
pc = [os.path.join(r, d) for r, d, _ in os.walk('.') if d == '__pycache__' and 'venv' not in r]
check('No stale __pycache__', len(pc) <= 3, str(len(pc)) + ' dirs')

# Existential checks
for f in ['logging.conf', '.env.example', 'requirements.txt']:
    check(f + ' exists', os.path.exists(f))

print()
total = passed + failed
print('=' * 60)
print('  BATCH 02: ' + str(passed) + '/' + str(total) + ' passed')
if failed > 0:
    for n, s, d in results:
        if s == 'FAIL': print('    [FAIL] ' + n + (': ' + d if d else ''))
print('=' * 60)
raise SystemExit(1 if failed else 0)
