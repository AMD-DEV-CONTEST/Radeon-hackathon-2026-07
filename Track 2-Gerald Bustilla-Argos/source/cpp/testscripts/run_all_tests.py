#!/usr/bin/env python3
"""
Argos Test Runner — runs all test scripts and reports results.
Usage: python run_all_tests.py
"""
import subprocess
import sys
import os

tests = [
    ("Chatbox Simulation", "test_chatbox_sim.py"),
    ("RAG Pipeline Simulation (Basic)", "test_rag_sim.py"),
    ("Modern RAG Pipeline (Hybrid + RRF + Reranking)", "test_rag_modern.py"),
    ("RAG Evaluation Metrics (Precision/Recall/MRR/NDCG)", "test_rag_evaluation.py"),
    ("API Connectivity", "test_api_new.py"),
]

print("=" * 70)
print("Argos — Full Test Suite")
print("=" * 70)

total_pass = 0
total_fail = 0
script_dir = os.path.dirname(os.path.abspath(__file__))

for name, script in tests:
    path = os.path.join(script_dir, script)
    if not os.path.exists(path):
        print(f"\n--- {name} --- SKIPPED (file not found: {script})")
        continue
    
    print(f"\n--- {name} ---")
    result = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=120)
    
    # Print last few lines of output
    lines = result.stdout.strip().split('\n')
    for line in lines[-5:]:
        print(f"  {line}")
    
    if result.returncode == 0:
        print(f"  STATUS: PASS")
    else:
        print(f"  STATUS: FAIL (exit code {result.returncode})")

print("\n" + "=" * 70)
print("Test suite complete.")
print("=" * 70)
