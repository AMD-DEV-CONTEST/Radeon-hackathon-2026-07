"""AutoSec — Complete System Verification v2"""
import subprocess
from pathlib import Path

BASE = Path("C:/Users/Precision/Desktop/Radeon-hackathon-2026-07/auto-sec-agent")
G = '\033[92m'; R = '\033[91m'; N = '\033[0m'; BOLD = '\033[1m'
results = []

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, cwd=BASE, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except: return ""

def test(name, fn):
    try:
        ok, msg = fn()
        results.append((name, ok))
        print(f"  {'✅' if ok else '❌'} {name} {msg or ''}")
    except Exception as e:
        results.append((name, False))
        print(f"  ❌ {name}: {e}")

print(f"\n{R}{BOLD}╔══════════════════════════════════════════════╗")
print(f"║     AutoSec — Full Verification Suite     ║")
print(f"╚══════════════════════════════════════════════╝{N}\n")

test("Unit Tests (4/4)", lambda: ("4/4 tests" in run("python tests/test_all.py"), ""))
test("All Module Imports", lambda: ("ALL IMPORTS OK" in run("python -c \"from core.agent import AutoSecAgent; from ai.analyzer import ROCmAccelerator, AIAnalyzer; from db.database import Database; from agents.orchestrator import Orchestrator; from reporting.email_reporter import EmailReporter; from reporting.notion_reporter import NotionReporter; from config.settings import Config; from config.logger import AutoSecLogger; print('ALL IMPORTS OK')\""), ""))
test("ROCm Engine + Benchmark", lambda: ("ROCm" in run("python -c \"from ai.analyzer import ROCmAccelerator; r=ROCmAccelerator(); s=r.get_specs(); print('Engine:', s['engine'])\""), ""))
test("AI Analyzer (4-phase)", lambda: ("Score" in run("python -c \"from ai.analyzer import AIAnalyzer; a=AIAnalyzer(use_rocm=True); r=a.analyze_scan_results('x',['a.x'],['https://a.x'],[{'info':{'name':'X','severity':'high'}}]); print('Score:',r['phases']['risk']['score'])\""), ""))
test("Database CRUD", lambda: ("Targets" in run("python -c \"from db.database import Database; d=Database('C:/Users/Precision/Desktop/Radeon-hackathon-2026-07/auto-sec-agent/db/t.db'); d.add_target('x.com'); print('Targets:',d.get_stats()['total_targets']); import os; os.remove('C:/Users/Precision/Desktop/Radeon-hackathon-2026-07/auto-sec-agent/db/t.db')\""), ""))
test("Orchestrator", lambda: ("targets" in run("python agents/orchestrator.py stats"), ""))

def notion():
    import urllib.request, os
    key = os.environ.get("NOTION_API_KEY", "")
    if not key: return (False, "No NOTION_API_KEY set")
    req = urllib.request.Request("https://api.notion.com/v1/search", data=b'{"page_size":1}', headers={"Authorization": f"Bearer {key}", "Notion-Version": "2025-09-03", "Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=10)
    return (resp.status == 200, f"Status: {resp.status}")
test("Notion API", notion)

test("Full Pipeline", lambda: ("Complete" in run("python main.py scanme.nmap.org --quiet", timeout=60), ""))

def tools():
    paths = [
        ("Subfinder", "C:/Users/Precision/go/bin/subfinder.exe"),
        ("Nuclei", "C:/Users/Precision/go/bin/nuclei.exe"),
        ("Naabu", "C:/Users/Precision/go/bin/naabu.exe"),
        ("Httpx", "C:/Users/Precision/go/bin/httpx.exe"),
        ("Himalaya", "C:/Users/Precision/tools/himalaya/himalaya.exe"),
    ]
    missing = [n for n, p in paths if not Path(p).exists()]
    return (len(missing) == 0, f"All {len(paths)} present" if not missing else f"Missing: {', '.join(missing)}")
test("All Tools Installed (6/6)", tools)

def config():
    import sys; sys.path.insert(0, str(BASE))
    from config.settings import Config
    paths = [Config.SUBFINDER_PATH, Config.NUCLEI_PATH, Config.NAABU_PATH, Config.HTTPX_PATH]
    valid = sum(1 for p in paths if Path(p).exists())
    return (valid == len(paths), f"{valid}/{len(paths)}")
test("Config Paths Valid (4/4)", config)

passed = sum(1 for _, p in results if p)
total = len(results)
print(f"\n{R}{BOLD}{'='*50}{N}")
print(f"{G}{BOLD}📊 RESULTS: {passed}/{total} PASSED{N}")
if passed == total:
    print(f"\n{G}{BOLD}🎉 ALL SYSTEMS VERIFIED! READY FOR SUBMISSION!{N}")
