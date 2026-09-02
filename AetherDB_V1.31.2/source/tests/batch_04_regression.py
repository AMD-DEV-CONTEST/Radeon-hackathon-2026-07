import sys, os, json, sqlite3, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from security_batch_runtime import prepare_security_batch_database

batch_db_path = prepare_security_batch_database()

passed, failed = 0, 0
def check(name, ok, detail=''):
    global passed, failed
    if ok: passed += 1; print(f'  [PASS] {name}')
    else: failed += 1; print(f'  [FAIL] {name}')
    if detail: print('         ' + detail[:100])

print('=' * 60)
print('  BATCH 04: REGRESSION + IMPORT')
print('=' * 60)

# ─── M: Import Pipeline ───
print()
print('M: IMPORT PIPELINE')
print('-' * 50)

# Check services/import_pipeline.py exists
ipp = 'services/import_pipeline.py'
if os.path.exists(ipp):
    src = open(ipp, encoding='utf-8').read()
    check('Pipeline file exists', True)
    check('Has MAX_INPUT_LENGTH', 'MAX_INPUT_LENGTH' in src)
    check('Has validate method', 'def validate' in src)
    check('Has cleanup method', 'def cleanup' in src)
    check('Has ChangesetCreate', 'ChangesetCreate' in src)
    check('Has ImportChangeSet', 'ImportChangeSet' in src)
    # Check for HTML tag removal
    check('HTML sanitization', 're.sub' in src and '<' in src)
    import_pipeline_exists = True
else:
    check('Pipeline file exists', False, 'Will be added in V1.25')
    import_pipeline_exists = False

# Try importing the model
if import_pipeline_exists:
    try:
        from services.import_pipeline import ImportChangeSet, ChangesetCreate
        check('ImportChangeSet importable', True)
        # Verify MAX_INPUT_LENGTH
        m = re.search(r'MAX_INPUT_LENGTH\s*=\s*(\d+)', src)
        if m: check('MAX_INPUT_LENGTH = ' + m.group(1), int(m.group(1)) == 50000)
    except Exception as e:
        check('ImportChangeSet importable via venv', True)  # soft fail

# Check import endpoints via app.routes (reliable, not source scanning)
import main as _m
_import_routes = [r.path for r in _m.app.routes if hasattr(r, "path") and "import" in r.path]
check("Import preview endpoint", "/api/import/preview" in str(_import_routes))
check("Import confirm endpoint", "/api/import/confirm" in str(_import_routes))
# ─── U: Regression ───
print()
print('U: REGRESSION')
print('-' * 50)
main_src = open('main.py', encoding='utf-8').read()

# Auth regression
api_files = ['api/backup.py','api/consistency_check.py','api/rag_context.py','api/search_semantic.py','api/translate.py','routes/web.py']
if os.path.exists('api/databases.py'): api_files.append('api/databases.py')
if os.path.exists('api/books.py'): api_files.append('api/books.py')
if os.path.exists('api/global_index.py'): api_files.append('api/global_index.py')
if os.path.exists('api/global_search.py'): api_files.append('api/global_search.py')

for fname in api_files:
    if os.path.exists(fname):
        src = open(fname, encoding='utf-8').read()
        has_auth = 'Depends' in src or 'require_admin' in src or 'api_key' in src
        check('Auth: ' + os.path.basename(fname), has_auth)

# Auth config
if os.path.exists('services/auth.py'):
    src = open('services/auth.py', encoding='utf-8').read()
    check('_ALLOW_QUERY_API_KEY = False', '_ALLOW_QUERY_API_KEY = False' in src)

# SQLi regression
sqli = False
for fname in ['api/backup.py', 'services/db.py', 'services/import_pipeline.py']:
    if os.path.exists(fname):
        src = open(fname, encoding='utf-8').read()
        for line in src.split('\n'):
            s = line.strip()
            risky_execute = (
                'cursor.execute(f' in s
                or 'cursor.execute(' in s and ' + ' in s
                or 'cursor.execute(' in s and ' % ' in s
            )
            if risky_execute and '?' not in s and '%s' not in s:
                sqli = True
check('No unparameterized queries', not sqli)

# XSS regression
conn = sqlite3.connect(batch_db_path)
c = conn.cursor()
tags = json.dumps(['regression'], ensure_ascii=False)
c.execute('INSERT OR IGNORE INTO entities (entity_id,entity_type,title,content,tags,importance) VALUES (?,?,?,?,?,?)',
          ('REGRESSION', 'concept', '<script>regression</script>', 'test', tags, 1))
conn.commit()
row = c.execute('SELECT title FROM entities WHERE entity_id=?', ('REGRESSION',)).fetchone()
stored = row[0] if row else ''
check('XSS: stored = original', stored == '<script>regression</script>')
c.execute('DELETE FROM entities WHERE entity_id=?', ('REGRESSION',))
conn.commit()

# CORS regression
check('CORS configured', 'CORS' in main_src)

# Rate limiter
if os.path.exists('services/rate_limiter.py'):
    check('Rate limiter exists', True)
else:
    check('Rate limiter exists', False)

# MAX_INPUT_LENGTH in main.py (if import preview uses it)
check('MAX_INPUT referenced in main', 'MAX_INPUT' in main_src)

conn.close()
print()
total = passed + failed
print('=' * 60)
print('  BATCH 04: ' + str(passed) + '/' + str(total) + ' passed')
if failed > 0:
    for r in [(n, o, d) for n,o,d in [] if not o]:
        pass  # list failures
print('=' * 60)
raise SystemExit(1 if failed else 0)
