"""Detached launcher for the MKO Web UI preview.

Spawns `python run.py` with DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so
the FastAPI server outlives the Freebuff shell tool. Stdout+stderr go to
.freebuff/preview.log. The launcher exits immediately after spawning.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / ".freebuff" / "preview.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

with open(LOG, "ab", buffering=0) as logf:
    proc = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=str(ROOT),
        stdout=logf,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
print(proc.pid)
