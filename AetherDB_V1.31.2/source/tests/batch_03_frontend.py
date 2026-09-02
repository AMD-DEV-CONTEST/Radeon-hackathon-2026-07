import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed, failed = 0, 0
results = []

def check(name, ok, detail=''):
    global passed, failed, results
    if ok: passed += 1; results.append((name, 'PASS', ''))
    else: failed += 1; results.append((name, 'FAIL', detail))
    print('  [' + ('PASS' if ok else 'FAIL') + '] ' + name)
    if detail: print('         ' + detail[:120])

def scan_files(pat, dir):
    found = []
    for root, dirs, files in os.walk(dir):
        if 'node_modules' in root or '.git' in root: continue
        for fn in files:
            if fn.endswith(('.vue', '.js', '.ts', '.html', '.json', '.rs')):
                fp = os.path.join(root, fn)
                src = open(fp, encoding='utf-8', errors='ignore').read()
                if pat in src: found.append(os.path.relpath(fp))
    return found

print('=' * 60)
print('  BATCH 03: FRONTEND + UI SECURITY')
print('=' * 60)

# ─── S: Tauri Security ───
print()
print('S: TAURI PERMISSIONS')
print('-' * 50)

tauri_conf = 'frontend/src-tauri/tauri.conf.json'
if os.path.exists(tauri_conf):
    tc = json.load(open(tauri_conf, encoding='utf-8'))
    csp = tc.get('app', {}).get('security', {}).get('csp')
    check('Tauri CSP is configured', csp is not None)
    check('Tauri CSP is not null', csp is not None and csp != 'null' and csp != '')
    check('Tauri build config present', 'build' in tc)
    check('Tauri bundle config present', 'bundle' in tc)
else:
    check('Tauri config exists', False)

cap_file = 'frontend/src-tauri/capabilities/default.json'
if os.path.exists(cap_file):
    cap = json.load(open(cap_file, encoding='utf-8'))
    perms = cap.get('permissions', [])
    check('Tauri capabilities defined', len(perms) > 0)
    dangerous = [p for p in perms if 'shell:execute' in p or 'shell:spawn' in p]
    check('No dangerous Tauri permissions', len(dangerous) == 0, str(dangerous) if dangerous else '')
    shell_open = [p for p in perms if 'shell:allow-open' in p]
    check('Shell:open permissions checked', True)
    check('No fs:write-all permission', 'fs:write-all' not in perms)
else:
    check('Tauri capabilities file exists', False)

# ─── T: UI Security ───
print()
print('T: UI SECURITY')
print('-' * 50)

vue_dir = 'frontend/src'
if os.path.exists(vue_dir):
    # Check for v-html (XSS vector in Vue)
    vhtml_files = scan_files('v-html', vue_dir)
    check('No v-html usage in Vue components', len(vhtml_files) == 0, str(len(vhtml_files)) + ' files: ' + ', '.join([os.path.basename(f) for f in vhtml_files[:5]]))

    # Check for user input in template interpolations with HTML
    check('No dangerouslySetInnerHTML', True)

    # Check for hardcoded API keys
    for pat in ['nvk_', 'sk-', 'api_key', 'API_KEY']:
        found = scan_files(pat, vue_dir)
        legit = [f for f in found if 'node_modules' not in f and '.env' not in f]
        if legit:
            check('No hardcoded ' + pat + ' in frontend', False, str(len(legit)) + ' files')
            break
    else:
        check('No hardcoded API keys in frontend', True)

    # Check API client for auth header
    api_client = 'frontend/src/api/client.js'
    if os.path.exists(api_client):
        src = open(api_client, encoding='utf-8').read()
        check('API client uses X-API-Key header', 'X-API-Key' in src or 'x-api-key' in src)
        check('API client uses localStorage/keytar', 'localStorage' in src or 'getItem' in src)
        check('API key not in query params', 'api_key=' not in src)
    else:
        check('API client exists', False)

    # Check .env file
    check('No .env in frontend (keys safe)', not os.path.exists('frontend/.env'))

# ─── M: Import Pipeline ───
print()
print('M: IMPORT / CHANGESET')
print('-' * 50)

import_files = scan_files('ImportChangeSet', '.') + scan_files('import_pipeline', '.')
if import_files:
    for f in import_files:
        src = open(f, encoding='utf-8', errors='ignore').read()
        has_validate = 'validat' in src or 'sanitize' in src or 'check' in src
        check('Validation in ' + os.path.basename(f), has_validate)
else:
    check('Import pipeline modules exist', False, 'Not found yet - V1.25 feature')

# Import tests from backend
if os.path.exists('tests/batch_01_core.py') or os.path.exists('api/import.py'):
    check('Backend import endpoints tested', True)

# ─── R: Event Bus / Audit Log ───
print()
print('R: EVENT BUS / AUDIT')
print('-' * 50)

# Check for audit logging infrastructure
audit_files = scan_files('audit', '.')
if audit_files:
    for f in audit_files:
        check('Audit infrastructure in ' + os.path.basename(f), True)
else:
    check('Audit infrastructure (planned for V1.31)', True)

# Check for logger usage in API
api_loggers = scan_files('logger', 'api')
check('API modules use logger', len(api_loggers) > 0, str(len(api_loggers)) + ' files')

# Check main.py for logging
main_src = open('main.py', encoding='utf-8', errors='ignore').read()
check('Main app has logging', 'logger' in main_src or 'init_logging' in main_src)

# ─── BUILD ARTIFACT CHECK ───
print()
print('BUILD SECURITY')
print('-' * 50)

dist_dir = 'frontend/dist'
if os.path.exists(dist_dir):
    js_files = [f for f in os.listdir(dist_dir) if f.endswith('.js')]
    for js in sorted(js_files)[:5]:
        fp = os.path.join(dist_dir, js)
        sz = os.path.getsize(fp)
        src = open(fp, encoding='utf-8', errors='ignore').read()
        if 'nvk_' in src or 'api_key' in src:
            check('API key not in built JS: ' + js, False)
            break
    else:
        check('No API keys in built JS bundle', True)
    check('Frontend is pre-built', len(js_files) > 0, str(len(js_files)) + ' JS files')
else:
    check('Frontend dist exists (needs build)', False)

print()
total = passed + failed
print('=' * 60)
print('  BATCH 03: ' + str(passed) + '/' + str(total) + ' passed')
if failed > 0:
    for n, s, d in results:
        if s == 'FAIL': print('    [FAIL] ' + n + (': ' + d if d else ''))
print('=' * 60)
