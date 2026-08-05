#!/usr/bin/env python3
"""
radeon_live_segment.py — the optimization section, running on a live AMD Radeon GPU.

Track 2 Requirement 3 asks for "the actual execution performance on an AMD Radeon GPU". The
submission's captured evidence came from a Radeon Cloud instance that was destroyed, so those
sections replay recorded numbers and say so on screen. This runs against AMD's Radeon Token
Factory instead, which is live, and everything below is measured while the camera is on.

It is deliberately the SAME code path the product uses. `determinex_calibrate` is not a demo
script: it is what sets K for verified search, and K is the correctness knob
(`P = 1 - (1-p)^K`). Watching it measure the GPU is watching the optimization happen.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

PAUSE = 2.5


def say(title: str) -> None:
    print()
    print("=" * 74)
    print(f"  {title}")
    print("=" * 74)
    sys.stdout.flush()
    time.sleep(PAUSE)


def main() -> int:
    try:
        from determinex_providers import _load_env_once

        _load_env_once()
    except Exception:
        pass
    key = os.environ.get("AMD_TOKEN_FACTORY_KEY", "")
    base = os.environ.get("AMD_TOKEN_FACTORY_BASE", "https://radeon.anruicloud.com/api/v1")

    say("1/4  THE HARDWARE - AMD Radeon, serving right now")
    print(f"  endpoint : {base}")
    print(f"  auth     : AMD_TOKEN_FACTORY_KEY present ({len(key)} chars), never printed")
    t = time.monotonic()
    req = urllib.request.Request(base + "/models", headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        models = [m["id"] for m in json.loads(r.read()).get("data", [])]
    print(f"  models   : {len(models)} served, answered in {time.monotonic() - t:.1f}s")
    for m in models:
        print(f"             - {m}")
    time.sleep(PAUSE)

    say("2/4  ONE CANDIDATE, MEASURED - what a single generation costs")
    body = json.dumps({
        "model": "MiniCPM5-1B",
        "messages": [{"role": "user", "content": "Write a Rust function that reverses a string."}],
        "max_tokens": 64, "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    el = time.monotonic() - t
    tok = (d.get("usage") or {}).get("completion_tokens", 0)
    print(f"  {tok} tokens in {el:.2f}s  =  {tok / el:.1f} tok/s single stream")
    time.sleep(PAUSE)

    say("3/4  WHAT DOES THE Kth CANDIDATE COST? - live sweep, the product's own code")
    print("  scripts/determinex_calibrate.py --backend amd --model MiniCPM5-1B")
    print("  K is the correctness knob: P = 1 - (1-p)^K. This measures the machine,")
    print("  it does not read a config -- a client-side setting is not the authority")
    print("  that enforces the limit.")
    print()
    sys.stdout.flush()
    subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "determinex_calibrate.py"),
         "--backend", "amd", "--model", "MiniCPM5-1B",
         "--ks", "1,2,4,8,16,32", "--num-predict", "64", "--repeats", "1"],
        cwd=str(_ROOT), check=False,
    )
    time.sleep(PAUSE)

    say("4/4  THE STORED CURVE - what the solver will actually use")
    subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "determinex_calibrate.py"), "--show"],
        cwd=str(_ROOT), check=False,
    )
    print()
    print("  The amd:: row above was measured live on AMD Radeon just now, "
          + time.strftime("%Y-%m-%d %H:%M:%S") + ".")
    # Precision, because this section READS STORAGE and an earlier version of this line
    # claimed "no number on this screen was read from a file" -- true of sections 1-3 and
    # flatly false of the one it was printed under, which prints the profile store. The
    # other rows are prior calibrations of other backends and are shown deliberately: the
    # point of the store is that one machine holds different curves for different rigs.
    print("  The other rows are earlier calibrations of other backends, read from that file")
    print("  -- shown on purpose: one box, several rigs, a different K for each.")
    time.sleep(PAUSE + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
