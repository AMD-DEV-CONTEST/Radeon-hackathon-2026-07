#!/usr/bin/env python3
"""Evaluate policy connectivity / smoke test (wrapper).

Usage (from project root, cloud):
  cd src && python eval.py --wss-url wss://rc-xxxx.radeon.firstdg.ai

Delegates to self_scripts/infer/test_amd_policy_client.py
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_CLIENT = _ROOT / "self_scripts" / "infer" / "test_amd_policy_client.py"

if __name__ == "__main__":
    sys.argv[0] = str(_CLIENT)
    runpy.run_path(str(_CLIENT), run_name="__main__")
