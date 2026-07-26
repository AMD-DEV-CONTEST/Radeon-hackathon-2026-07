#!/usr/bin/env python3
"""Train π0.5 G1-D joint policy (wrapper for OpenPI train_pytorch.py).

Usage (from project root):
  cd src && python train.py --config pi05_g1d_joint_full

See configs/g1d_organize_table.yaml and README.md Section 5.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if __name__ == "__main__":
    sys.argv[0] = str(_ROOT / "scripts" / "train_pytorch.py")
    runpy.run_path(str(_ROOT / "scripts" / "train_pytorch.py"), run_name="__main__")
