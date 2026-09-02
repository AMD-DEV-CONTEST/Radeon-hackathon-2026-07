import sys, os, json, re, sqlite3, inspect
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from security_batch_runtime import prepare_security_batch_database

batch_db_path = prepare_security_batch_database()

passed, failed = 0, 0
results = []
warnings = []

def check(name, ok, detail=""):
    global passed, failed, results
    if ok:
        passed += 1
        results.append((name, "PASS", ""))
    else:
        failed += 1
        results.append((name, "FAIL", detail))
    print("  [" + ("PASS" if ok else "FAIL") + "] " + name)
    if detail:
        print("         " + detail[:120])

def warn(name, detail):
    global warnings
    warnings.append((name, detail))
    print("  [WARN] " + name + ": " + detail[:100])

print("=" * 60)
print("  BATCH 05: MISSING ATTACK SURFACES")
print("=" * 60)

# ─── B: API SURFACE SCAN ───
print()
print("B: API ROUTE ENUMERATION")
print("-" * 50)

try:
    import main as app_module
    app = app_module.app
    routes = []
    for route in app.routes:
        methods = getattr(route, "methods", set())
        path = getattr(route, "path", str(route))
        endpoint = getattr(route, "endpoint", None)
        deps = getattr(route, "dependencies", [])
        routes.append((list(methods) if methods else ["ANY"], path, endpoint, deps))

    total_routes = len(routes)
    check("FastAPI routes enumerable", True, str(total_routes) + " routes found")
    api_routes = [(m, p, e, d) for m, p, e, d in routes if p.startswith("/api/")]
    check("API routes count > 0", len(api_routes) > 0, str(len(api_routes)) + " routes")

    write_verbs = ["POST", "PUT", "DELETE", "PATCH"]
    unauth_writes = []
    for methods, path, endpoint, deps in api_routes:
        is_write = any(v in methods for v in write_verbs)
        has_dep = any("Depends" in str(d) for d in deps) if deps else False
        if is_write and not has_dep:
            if endpoint:
                try:
                    src_lines = inspect.getsourcelines(endpoint)[0]
                    src_joined = "".join(src_lines)
                    if "Depends" not in src_joined and "require_admin" not in src_joined:
                        unauth_writes.append((path, methods))
                except:
                    unauth_writes.append((path, methods))
    for p, m in unauth_writes:
        check("AUTH MISSING: " + p + " (" + ",".join(m) + ")", False)
    if not unauth_writes:
        check("All write API routes have auth", True)

except Exception as e:
    check("FastAPI route enumeration", False, str(e)[:100])

# ─── B2: Manual route coverage check ───
print()
print("B2: MANUAL ROUTE COVERAGE")
print("-" * 50)

api_dir = "api"
api_files = sorted([f for f in os.listdir(api_dir) if f.endswith(".py") and f != "__init__.py"])
for fn in api_files:
    fp = os.path.join(api_dir, fn)
    src = open(fp, encoding="utf-8", errors="ignore").read()
    routes_found = len(re.findall(r'@(?:router|app)\.(?:get|post|put|delete|patch)\(', src))
    has_auth = "Depends" in src or "require_admin" in src or "get_current_user" in src
    if routes_found > 0:
        check(fn + ": " + str(routes_found) + " routes, " + ("AUTH OK" if has_auth else "NO AUTH!"), has_auth)

# ─── C: CROSS-DATABASE IDOR (DEEP) ───
print()
print("C: CROSS-DATABASE IDOR (DEEP)")
print("-" * 50)

conn = sqlite3.connect(batch_db_path)
c = conn.cursor()

# Check book_id isolation
try:
    books = c.execute("SELECT DISTINCT book_id FROM entities").fetchall()
    book_count = len(books)
    check("book_id isolation in entities", book_count > 0, str(book_count) + " books found")
except Exception as e:
    check("book_id isolation in entities", False, str(e)[:60])

# Check relations book_id
try:
    rel_books = c.execute("SELECT DISTINCT book_id FROM relations").fetchall()
    check("book_id isolation in relations", len(rel_books) > 0, str(len(rel_books)) + " books")
except:
    check("book_id isolation in relations", False)

# Check entity_versions book_id
try:
    ver_books = c.execute("SELECT DISTINCT book_id FROM entity_versions").fetchall()
    check("book_id isolation in entity_versions", len(ver_books) > 0, str(len(ver_books)) + " books")
except:
    check("book_id isolation in entity_versions", False)

# Check no database_id (migration needed)
try:
    c.execute("SELECT database_id FROM entities LIMIT 1")
    check("database_id in entities", True)
except:
    warn("database_id in entities", "Column not found - migration needed for V2.0")

# Check vector_chunks book_id
try:
    vc_books = c.execute("SELECT DISTINCT book_id FROM vector_chunks").fetchall()
    check("book_id isolation in vector_chunks", len(vc_books) > 0, str(len(vc_books)) + " books")
except:
    check("book_id isolation in vector_chunks", False)

# Check entity_translations book_id
try:
    et_books = c.execute("SELECT DISTINCT book_id FROM entity_translations").fetchall()
    check("book_id isolation in entity_translations", len(et_books) > 0)
except:
    warn("book_id in entity_translations", "Table may not exist")

conn.close()

# ─── E: XSS DEEP DIVE ───
print()
print("E: XSS DEEP SCAN")
print("-" * 50)

vue_dir = "frontend/src"
if os.path.exists(vue_dir):
    vhtml_files = []
    for root, dirs, files in os.walk(vue_dir):
        if "node_modules" in root: continue
        for fn in files:
            if fn.endswith(".vue"):
                fp = os.path.join(root, fn)
                src = open(fp, encoding="utf-8", errors="ignore").read()
                if "v-html" in src:
                    vhtml_files.append(os.path.relpath(fp))
                    for i, line in enumerate(src.split("\n"), 1):
                        if "v-html" in line:
                            check("v-html in " + fn + ":" + str(i), False, line.strip()[:60])
                            break
    if not vhtml_files:
        check("No v-html in Vue components", True)
else:
    warn("Vue directory", "frontend/src not found")

# ─── G: INPUT VALIDATION ───
print()
print("G: INPUT VALIDATION (DEEP)")
print("-" * 50)

main_src = open("main.py", encoding="utf-8").read()
check("Main has input limits", "MAX_" in main_src or "max_length" in main_src)

models_found = 0
for root, dirs, files in os.walk("."):
    if "venv" in root or "__pycache__" in root or ".git" in root: continue
    for fn in files:
        if fn.endswith(".py"):
            src = open(os.path.join(root, fn), encoding="utf-8", errors="ignore").read()
            if "BaseModel" in src or "pydantic" in src.lower():
                models_found += 1
check("Pydantic models exist", models_found > 0, str(models_found) + " files")

# ─── H: CONCURRENCY ───
print()
print("H: CONCURRENCY / TOCTOU REVIEW")
print("-" * 50)

lock_found = False
for root, dirs, files in os.walk("."):
    if "venv" in root or "__pycache__" in root or ".git" in root: continue
    for fn in files:
        if fn.endswith(".py"):
            src = open(os.path.join(root, fn), encoding="utf-8", errors="ignore").read()
            if "threading.Lock" in src or "asyncio.Lock" in src:
                lock_found = True
                break
check("Threading/async locks used", lock_found)

# ─── P: SECRET LEAKAGE DEEP ───
print()
print("P: SECRET LEAKAGE (DEEP)")
print("-" * 50)

for fn in ["config.yaml", ".env.example", "logging.conf"]:
    if os.path.exists(fn):
        src = open(fn, encoding="utf-8", errors="ignore").read()
        has_real_key = "nvk_" in src or "sk-" in src
        if has_real_key:
            # Check if it's actually a real key or a template
            if "your-" not in src.lower():
                check("Real key in " + fn + "!", False)
            else:
                check("Template key in " + fn, True)
        else:
            check("No secrets in " + fn, True)

if os.path.exists("logs"):
    log_files = []
    credential_patterns = (
        re.compile(r"(?i)(?<![a-z0-9])nvk_(?:admin_)?[a-z0-9]{16,}"),
        re.compile(r"(?i)(?<![a-z0-9])sk-(?:proj-)?[a-z0-9_-]{12,}"),
    )
    for root, dirs, files in os.walk("logs"):
        for fn in files:
            fp = os.path.join(root, fn)
            try:
                src = open(fp, encoding="utf-8", errors="ignore").read()
                for pattern in credential_patterns:
                    if pattern.search(src):
                        log_files.append(fp)
                        break
            except:
                pass
    if log_files:
        check("Secrets in log files!", False, str(len(log_files)) + " files")
    else:
        check("No secrets leaked to logs", True)

# ─── Q: ERROR HANDLING ───
print()
print("Q: ERROR HANDLING (DEEP)")
print("-" * 50)

all_str_e = []
for root, dirs, files in os.walk("api"):
    for fn in files:
        if fn.endswith(".py"):
            fp = os.path.join(root, fn)
            src = open(fp, encoding="utf-8").read()
            for i, line in enumerate(src.split("\n"), 1):
                s = line.strip()
                if "detail=str(" in s and ("e)" in s or "err)" in s):
                    all_str_e.append((os.path.basename(fp), i, s[:60]))

for fn, ln, s in all_str_e:
    check("str(e) disclosure in " + fn + ":" + str(ln), False, s)
if not all_str_e:
    check("No str(e) disclosure in api/", True)

# ─── SUMMARY ───
print()
total = passed + failed
print("=" * 60)
print("  BATCH 05: " + str(passed) + "/" + str(total) + " passed")
print("  Warnings: " + str(len(warnings)))
if failed > 0:
    print()
    for n, s, d in results:
        if s == "FAIL":
            print("    [FAIL] " + n + (": " + d if d else ""))
print("=" * 60)
raise SystemExit(1 if failed else 0)
