#!/usr/bin/env python3
"""Integration check for the 2026-08 silent-degradation fixes.

The unit suite covers each fix in isolation against fakes. This script wires the
REAL components together -- actual SessionMemory (SQLite on disk), actual
SkillRouter, actual MoLLlamaCpp against a stub llama.cpp server -- because every
one of these bugs was an *integration* bug: each component was individually
defensible, and the contract between two of them was what broke.

None of these failures crash. They degrade silently: the context window slides
the wrong way, an expert never mounts, a banned LoRA slips through, a mount
"succeeds" while running the bare base. Anything that fails here would otherwise
show up only as "the answers got worse", weeks later.

No GPU and no real server needed:

    python scripts/verify_bugfixes.py        # exit 0 = all good, 1 = regression

Suitable as a pre-commit / CI gate alongside `pytest tests/ -q`.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screwshell.core.mol_engine_llamacpp import MoLLlamaCpp   # noqa: E402
from screwshell.core.router import SkillRouter                # noqa: E402
from screwshell.memory.stores import SessionMemory            # noqa: E402

# Mirrors a real W7900 launch: experts live in per-expert folders all containing
# a file literally named adapter.gguf, the planning LoRA sits in its historical
# directory teichai_fable5_plan/, and a stale --lora may still preload a banned
# expert.
PRELOADED = [
    {"id": 0, "path": "/persistent/loras/btl3/adapter.gguf", "scale": 0.0},
    {"id": 1, "path": "/persistent/loras/teichai_fable5_plan/adapter.gguf", "scale": 0.0},
    {"id": 2, "path": "/persistent/loras/cybersec/adapter.gguf", "scale": 0.0},
    {"id": 3, "path": "/persistent/loras/fable5/adapter.gguf", "scale": 0.0},  # FORBIDDEN
]

_posted: list = []
_failures: list[str] = []


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, payload: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._send(json.dumps(PRELOADED).encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        _posted.append(json.loads(self.rfile.read(n) or "[]"))
        self._send(b'{"ok":true}')


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        _failures.append(label)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"   {detail}" if detail else ""))


def main() -> int:
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    try:
        print("1) adapter naming + forbidden ban at the registration layer")
        eng = MoLLlamaCpp("Qwen3.6-27B", server_url=url).load_base()
        check("named by parent dir, not the .gguf filename",
              "adapter" not in eng.adapters, f"keys={sorted(eng.adapters)}")
        check("disk name mapped to the logical name",
              "teichai_plan" in eng.adapters)
        check("preloaded forbidden expert refused",
              "fable5" not in eng.adapters)

        print("\n2) router and engine agree on the name (the agent expert can mount)")
        wanted = SkillRouter().skill_map["agent"]
        check(f"router asks for {wanted!r} and the engine has it",
              wanted in eng.adapters)

        print("\n3) roomy mount: target 1.0, every other adapter explicitly 0.0")
        _posted.clear()
        eng.activate("teichai_plan")
        scales = {e["id"]: e["scale"] for e in _posted[-1]}
        check("target id=1 at scale 1.0", scales.get(1) == 1.0, f"posted={scales}")
        check("all others zeroed (no LoRA blending)",
              all(v == 0.0 for k, v in scales.items() if k != 1))
        check("active_adapter reflects the mount",
              eng.active_adapter == "teichai_plan")

        print("\n4) an un-preloaded adapter must fail LOUDLY, not fake success")
        eng.load_adapter("ghost", "/nowhere/ghost/adapter.gguf")
        rec = eng.activate("ghost")
        check("mode reported as mount_failed_base",
              rec.mode == "mount_failed_base", f"mode={rec.mode}")
        check("does not claim an expert it never mounted",
              eng.active_adapter is None)

        print("\n5) forbidden guard covers the tagged call the orchestrator makes")
        poisoned = SkillRouter()
        poisoned.skill_map["agent"] = "fable5"
        d = poisoned.route("anything", task_tag="agent")
        check("blocked -> None instead of the banned LoRA",
              d.adapter is None, f"adapter={d.adapter}")
        check("the downgrade is recorded in the reason",
              "FORBIDDEN" in d.reason)

        print("\n6) SessionMemory keeps the RECENT window (real SQLite)")
        tmp = tempfile.mkdtemp()
        mem = SessionMemory(tmp, session_id="probe")
        for i in range(1, 21):
            mem.add_turn("user", f"turn-{i:02d}")
        got = [t["content"] for t in mem.history(limit=12)]
        check("20 turns, limit 12 -> turn-09..turn-20",
              got == [f"turn-{i:02d}" for i in range(9, 21)],
              f"{got[0]}..{got[-1]}" if got else "empty")

        print("\n7) the window survives a restart (persistence path)")
        again = [t["content"] for t in
                 SessionMemory(tmp, session_id="probe").history(limit=5)]
        check("reopened DB -> turn-16..turn-20",
              again == [f"turn-{i}" for i in range(16, 21)], str(again))

        print("\n8) unit-suite baseline gate (docs/TRUTH.md sync is machine-checked)")
        import re as _re
        import subprocess as _sp
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = _sp.run([sys.executable, "-m", "pytest", "tests/", "-q",
                     "-p", "no:cacheprovider"],
                    capture_output=True, text=True, cwd=root, timeout=600)
        whole = r.stdout + r.stderr
        # The local safe-delete layer can append cleanup log lines AFTER the
        # pytest summary tail (pytest-of-djb garbage dirs), so never rely on
        # the last line -- scan the whole output instead.
        m = _re.search(r"(\d+) passed", whole)
        passed = int(m.group(1)) if m else -1
        f = _re.search(r"(\d+) failed", whole)
        failed = int(f.group(1)) if f else 0
        # 2026-08-04: 206 after OPENSOURCE_COMPARISON optimization batch
        # (RAG hybrid BM25+RRF, quote round-trip, semantic routing, llm-judge,
        # planner json_schema). 2026-08-05: 257 after V2 observatory (v15);
        # 296 after V3 observatory (v18: thresholds/percentile/ui_layout/
        # gov_events/ab_windows/config_snapshot/ui_build). 2026-08-06: 375
        # after tune-loop one-click autotune (v22: scorer/mapper/cycle/relay/
        # ui + 43 new tests). Bump with every batch -- and mirror in TRUTH §3.
        check("unit suite passes (>= 375)", passed >= 375, f"passed={passed}")
        check("no failures in the suite", failed == 0, f"failed={failed}")
        if r.returncode != 0 or failed:
            print("        note: pytest exit %d, tail: %s"
                  % (r.returncode, whole.strip().splitlines()[-1][:200]))
    finally:
        srv.shutdown()

    print()
    if _failures:
        print(f"=== {len(_failures)} REGRESSION(S) ===")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("=== all integration checks passed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
