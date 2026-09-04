"""Dependency-light Phase B benchmark/parity smoke runner.
Run with: python scripts/benchmark_phase_b.py
"""
from __future__ import annotations
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from nuclear_agent.analysis import run_morris, ParameterRange

def main():
    print("Phase B benchmark: scalar baseline only; no ROCm performance claim.")
    print("Use tests/test_gcs_primary_accelerated.py for optional PyTorch parity.")
if __name__ == "__main__": main()
