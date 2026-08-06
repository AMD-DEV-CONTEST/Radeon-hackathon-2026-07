import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed, failed = 0, 0
results = []

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
        print("         " + detail[:100])

def scan_files(pat, dir):
    found = []
    for root, dirs, files in os.walk(dir):
        if "node_modules" in root or ".git" in root: continue
        for fn in files:
            if fn.endswith((".vue", ".js", ".ts", ".html", ".json", ".rs", ".py")):
                fp = os.path.join(root, fn)
                try:
                    src = open(fp, encoding="utf-8-sig", errors="ignore").read()
                    if pat in src: found.append(os.path.relpath(fp))
                except:
                    pass
    return found

def read_json(fp):
    with open(fp, encoding="utf-8-sig") as f:
        return json.load(f)

print("=" * 60)
print("  BATCH 03 REVISED: FRONTEND + UI SECURITY")
print("=" * 60)

# S: Tauri Security
print()
print("S: TAURI PERMISSIONS")
print("-" * 50)

tauri_conf = "frontend/src-tauri/tauri.conf.json"
if os.path.exists(tauri_conf):
    tc = read_json(tauri_conf)
    csp = tc.get("app", {}).get("security", {}).get("csp")
    check("Tauri CSP is configured", csp is not None)
    check("Tauri CSP is not null", csp is not None and csp != "null" and csp != "")
    check("Tauri build config present", "build" in tc)
    check("Tauri bundle config present", "bundle" in tc)
else:
    check("Tauri config exists", False)

cap_file = "frontend/src-tauri/capabilities/default.json"
if os.path.exists(cap_file):
    cap = read_json(cap_file)
    perms = cap.get("permissions", [])
    check("Tauri capabilities defined", len(perms) > 0)
    dangerous = [p for p in perms if "shell:execute" in p or "shell:spawn" in p]
    check("No dangerous Tauri permissions", len(dangerous) == 0, str(dangerous) if dangerous else "")
    shell_open = [p for p in perms if "shell:allow-open" in p]
    check("shell:allow-open restricted", len(shell_open) <= 1, str(shell_open))
    check("No fs:write-all permission", "fs:write-all" not in perms)
else:
    check("Tauri capabilities file exists", False)

# E: Vue v-html
print()
print("E: VUE XSS (v-html)")
print("-" * 50)
vue_dir = "frontend/src"
if os.path.exists(vue_dir):
    vhtml_files = scan_files("v-html", vue_dir)
    check("No v-html usage in Vue components", len(vhtml_files) == 0, str(len(vhtml_files)) + " files: " + ", ".join([os.path.basename(f) for f in vhtml_files[:5]]))

# T: UI Security
print()
print("T: UI SECURITY")
print("-" * 50)
if os.path.exists(vue_dir):
    api_client = "frontend/src/api/client.js"
    if os.path.exists(api_client):
        src = open(api_client, encoding="utf-8-sig", errors="ignore").read()
        check("API client uses X-API-Key header", "X-API-Key" in src or "x-api-key" in src)
        frontend_api_key_sources = ""
        for root, dirs, files in os.walk(vue_dir):
            if "node_modules" in root or ".git" in root:
                continue
            for fn in files:
                if fn.endswith((".vue", ".js", ".ts")):
                    fp = os.path.join(root, fn)
                    frontend_api_key_sources += open(fp, encoding="utf-8-sig", errors="ignore").read() + "\n"
        uses_session_key = 'sessionStorage.getItem("aetherdb_api_key"' in frontend_api_key_sources or "sessionStorage.getItem('aetherdb_api_key'" in frontend_api_key_sources
        local_key_patterns = [
            'localStorage.getItem("aetherdb_api_key"',
            "localStorage.getItem('aetherdb_api_key'",
            'localStorage.setItem("aetherdb_api_key"',
            "localStorage.setItem('aetherdb_api_key'",
        ]
        check("API key stored in sessionStorage", uses_session_key)
        check("API key not stored in localStorage", not any(p in frontend_api_key_sources for p in local_key_patterns))

# R: Logger
print()
print("R: AUDIT / LOGGING")
print("-" * 50)
main_src = open("main.py", encoding="utf-8").read()
check("Main app has logging", "logger" in main_src or "init_logging" in main_src or "log" in main_src)
api_log_files = scan_files("logger", "api") + scan_files("logging.getLogger", "api") + scan_files("get_logger", "api")
check("API modules use logger", len(api_log_files) > 0, str(len(api_log_files)) + " files")

print()
total = passed + failed
print("=" * 60)
print("  BATCH 03 REVISED: " + str(passed) + "/" + str(total) + " passed")
if failed > 0:
    for n, s, d in results:
        if s == "FAIL": print("    [FAIL] " + n + ": " + d[:80])
print("=" * 60)
raise SystemExit(1 if failed else 0)
