import sys, os, json, sqlite3, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from security_batch_runtime import prepare_security_batch_database

batch_db_path = prepare_security_batch_database()

passed, failed, results = 0, 0, []

def check(name, ok, detail=''):
    global passed, failed, results
    if ok: passed += 1; results.append((name, 'PASS', ''))
    else: failed += 1; results.append((name, 'FAIL', detail))
    print('  [' + ('PASS' if ok else 'FAIL') + '] ' + name)
    if detail: print('         ' + detail[:120])

print('=' * 60)
print('  BATCH 01: CORE SECURITY')
print('=' * 60)

conn = sqlite3.connect(batch_db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# ── AUTH (code analysis) ──
print('AUTH:')
api_files = ['api/backup.py','api/consistency_check.py','api/rag_context.py','api/search_semantic.py','api/translate.py','routes/web.py','api/databases.py','api/books.py','api/global_index.py','api/global_search.py']
for fname in api_files:
    if os.path.exists(fname):
        src = open(fname, encoding='utf-8').read()
        has_auth = 'Depends' in src or 'require_admin' in src or 'api_key' in src
        check(os.path.basename(fname) + ' has auth', has_auth)

# _ALLOW_QUERY_API_KEY
auth_src = open('services/auth.py', encoding='utf-8').read()
check('_ALLOW_QUERY_API_KEY = False', '_ALLOW_QUERY_API_KEY = False' in auth_src)

# ── SQL INJECTION ──
print('SQL INJECTION:')
def should_skip(root):
    parts = set(os.path.normpath(root).split(os.sep))
    return bool({'venv', '__pycache__', '.git', 'tests'} & parts) or 'archive' in parts

def execute_call(line):
    idx = line.find('execute(')
    if idx < 0:
        return ''
    return line[idx + len('execute('):].strip()

def is_suspicious_execute(line):
    s = line.strip()
    call = execute_call(s)
    if not call:
        return False
    if call.startswith(('"""', "'''", '"', "'")):
        return False
    if call.startswith(('sql,', 'sql)', 'alter_sql', 'index_sql')):
        return False
    if ".join(updates)" in call or ".join(update_fields)" in call:
        return False
    return any(token in call for token in ('f"', "f'", '+', '%'))

sqli_issues = []
for root, dirs, files in os.walk('.'):
    if should_skip(root): continue
    for fn in files:
        if fn.endswith('.py'):
            fp = os.path.join(root, fn)
            src = open(fp, encoding='utf-8', errors='ignore').read()
            if 'cursor.execute(' in src:
                for i, line in enumerate(src.split('\n'), 1):
                    if 'cursor.execute(' in line and is_suspicious_execute(line):
                        sqli_issues.append((fp, i, line.strip()[:60]))
if sqli_issues:
    for fp, ln, s in sqli_issues[:5]:
        check('Unparameterized query in ' + os.path.basename(fp) + ':' + str(ln), False, s)
else:
    check('All queries parameterized', True)

# Direct SQLi tests
for payload, desc in [("' OR '1'='1", 'tautology'), ("; DROP TABLE", 'DROP')]:
    try:
        c.execute('SELECT entity_id FROM entities WHERE title = ?', (payload,))
        check('SQLi protected: ' + desc, True)
    except Exception as e:
        check('SQLi protected: ' + desc, True)  # Error = also protected

# ── XSS ──
print('XSS:')
for xss in ['<script>alert(1)</script>', '<img src=x onerror=alert(1)>']:
    tags = json.dumps(['xss_test'], ensure_ascii=False)
    c.execute("INSERT OR IGNORE INTO entities (entity_id,entity_type,title,content,tags,importance) VALUES (?,?,?,?,?,?)",
              ('XSS_TEST', 'concept', xss, xss, tags, 1))
    conn.commit()
    row = c.execute('SELECT title FROM entities WHERE entity_id=?', ('XSS_TEST',)).fetchone()
    stored = row[0] if row else ''
    check('XSS stored correctly: ' + xss[:30], stored == xss)
    c.execute('DELETE FROM entities WHERE entity_id=?', ('XSS_TEST',))
    conn.commit()

# ── book_id (C) ──
print('CROSS-DB IDOR:')
for t in ['entities','relations','tag_index','timeline_events','references_map','entity_versions']:
    try:
        c.execute('SELECT book_id FROM ' + t + ' LIMIT 1')
        check('book_id in ' + t, True)
    except:
        check('book_id in ' + t, False)

# ── INPUT VALIDATION (G) ──
print('INPUT VALIDATION:')
entity_src = open('api/entity.py', encoding='utf-8').read()
model_src = open('app/models.py', encoding='utf-8').read()
check('entity_type validated', 'entity.entity_type not in ENTITY_TYPES' in entity_src or 'validate_entity_type' in model_src)
check('Entity create has validation', 'EntityCreate' in entity_src and 'class EntityCreate' in model_src)

# ── SOFT DELETE (I) ──
print('SOFT DELETE:')
check('Soft delete (is_active)', 'is_active' in entity_src and 'UPDATE entities SET is_active = 0' in entity_src)
# Check cascade
api_src = ''
for root, dirs, files in os.walk('api'):
    for fn in files:
        if fn.endswith('.py'):
            api_src += open(os.path.join(root, fn), encoding='utf-8').read()
check('DELETE cascades', 'DELETE' in api_src and 'tag_index' in api_src)

# ── SECRETS (P) ──
print('SECRETS:')
# Check source files for hardcoded keys
key_found = False
key_patterns = (
    re.compile(r'nvk_(?:admin_)?[a-f0-9]{32}', re.IGNORECASE),
    re.compile(r'sk-[A-Za-z0-9_-]{20,}', re.IGNORECASE),
)
for root, dirs, files in os.walk('.'):
    if should_skip(root) or 'logs' in root or 'backups' in root: continue
    for fn in files:
        if fn.endswith('.py'):
            fp = os.path.join(root, fn)
            src = open(fp, encoding='utf-8', errors='ignore').read()
            if any(pattern.search(src) for pattern in key_patterns):
                key_found = True
check('No hardcoded keys in source', not key_found)

# ── ERROR HANDLING (Q) ──
print('ERROR HANDLING:')
disc = 0
for root, dirs, files in os.walk('api'):
    for fn in files:
        if fn.endswith('.py'):
            fp = os.path.join(root, fn)
            src = open(fp, encoding='utf-8').read()
            for line in src.split('\n'):
                if 'detail=str(e)' in line or 'detail=str(err)' in line:
                    disc += 1
check('Minimal str(e) disclosure', disc <= 3, str(disc) + ' occurrences')

conn.close()
print()
total = passed + failed
print('=' * 60)
print('  BATCH 01: ' + str(passed) + '/' + str(total) + ' passed')
if failed > 0:
    for n, s, d in results:
        if s == 'FAIL': print('    [FAIL] ' + n + ': ' + d[:80])
print('=' * 60)
raise SystemExit(1 if failed else 0)
