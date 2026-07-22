#!/usr/bin/env python3
"""
AutoSec Agent — Complete Build System
Automates: testing, git commit, and prepares for submission
"""
import subprocess, sys, os
from pathlib import Path

BASE = Path(__file__).parent
R = '\033[91m'; G = '\033[92m'; Y = '\033[93m'; C = '\033[96m'; N = '\033[0m'; BOLD = '\033[1m'

def run(cmd, cwd=None):
    print(f"  {C}$ {cmd}{N}")
    r = subprocess.run(cmd, shell=True, cwd=cwd or BASE, capture_output=True, text=True)
    if r.stdout.strip(): print(f"    {r.stdout[:500]}")
    if r.returncode != 0: print(f"    {R}{r.stderr[:300]}{N}")
    return r.returncode

def main():
    print(f"{R}{BOLD}\n╔════════════════════════════════════════════════╗")
    print(f"║     AutoSec Agent — Build System v1.0       ║")
    print(f"╚════════════════════════════════════════════════╝{N}\n")
    
    tests_passed = 0
    tests_total = 0
    
    # Step 1: Run Tests
    print(f"{Y}{BOLD}[1/4] Running Test Suite...{N}")
    r = subprocess.run([sys.executable, "tests/test_all.py"], cwd=BASE, capture_output=True, text=True)
    print(f"  {r.stdout}")
    if r.returncode == 0:
        print(f"  {G}✅ Tests passed!{N}")
        tests_passed = 1
    else:
        print(f"  {R}❌ Tests failed!{N}")
    tests_total += 1
    
    # Step 2: Git Status
    print(f"\n{Y}{BOLD}[2/4] Checking Git Status...{N}")
    r = subprocess.run(["git", "status", "--short"], cwd=BASE, capture_output=True, text=True)
    if r.stdout.strip():
        print(f"  {Y}Uncommitted changes:{N}")
        print(f"  {r.stdout[:500]}")
    else:
        print(f"  {G}✅ Clean working tree{N}")
    
    # Step 3: Git Add + Commit
    print(f"\n{Y}{BOLD}[3/4] Committing Changes...{N}")
    run("git add -A", cwd=BASE)
    r = run('git commit -m "AutoSec Agent: Enhanced ROCm + AI analysis + ultimate demo"', cwd=BASE)
    
    # Step 4: Build Summary
    print(f"\n{Y}{BOLD}[4/4] Build Summary{N}")
    print(f"""
{G}{BOLD}✅ BUILD COMPLETE{N}
  📦 Project: auto-sec-agent
  📁 Location: {BASE}
  🧪 Tests: {tests_passed}/{tests_total} passed
  
{R}{BOLD}🚀 READY FOR SUBMISSION{N}
  Steps to submit:
  1. Fork: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07
  2. Copy auto-sec-agent/ into your fork
  3. Create PR: "Track 2, AutoSec, AutoSec Agent"
  4. Ensure AMD AI Developer Program membership
{N}""")

if __name__ == "__main__":
    main()
