#!/usr/bin/env python3
"""radeon_breadth.py — measure verified search across models on the Radeon, over the instance's own tunnel.

The paste-and-run script on the box had its embedded heredoc mangled by the terminal, so its
measuring step is broken. Its model-swapping loop survived, which is the part that needs a
shell. This does the measuring from here over HTTPS, which does not.

It polls until a model appears, sweeps it, records the result, then waits for the model to
CHANGE and sweeps the next one. Unattended: a model that never appears is recorded as absent
rather than silently skipped, and every result is written the moment it exists.

    python .local/radeon_sweep.py --hours 6
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:8000/v1"   # runs ON the instance
KEY = "dtx-radeon-2026"
OUT = Path.home() / "determinex_breadth"
HDR = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

TASK = ("Write a Python function flatten(obj) that flattens a nested dict/list into a flat "
        "dict of path->value, using '.' between dict keys and [i] for list indices. "
        "flatten({'a':{'b':1}}) returns {'a.b':1}. "
        "flatten({'x':[1,2]}) returns {'x[0]':1,'x[1]':2}. "
        "flatten({'a':{'b':[{'c':3}]}}) returns {'a.b[0].c':3}. "
        "flatten({}) returns {}. flatten({'k':None}) returns {'k':None}. "
        "Output only the function. No explanation. No markdown fences.")
CHECKS = [({"a": {"b": 1}}, {"a.b": 1}),
          ({"x": [1, 2]}, {"x[0]": 1, "x[1]": 2}),
          ({"a": {"b": [{"c": 3}]}}, {"a.b[0].c": 3}),
          ({}, {}),
          ({"k": None}, {"k": None}),
          ({"p": {"q": {"r": [7, 8]}}}, {"p.q.r[0]": 7, "p.q.r[1]": 8})]


def served() -> str | None:
    """Which model the instance is serving, or None while it is loading or down."""
    try:
        rq = urllib.request.Request(f"{BASE}/models", headers=HDR)
        with urllib.request.urlopen(rq, timeout=20) as r:
            data = json.load(r).get("data") or []
            return data[0]["id"] if data else None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError):
        return None


def generate(model: str, temp: float) -> str:
    body = json.dumps({"model": model, "prompt": TASK,
                       "max_tokens": 400, "temperature": temp}).encode()
    rq = urllib.request.Request(f"{BASE}/completions", body, HDR)
    with urllib.request.urlopen(rq, timeout=240) as r:
        return json.load(r)["choices"][0]["text"]


def clean(t: str) -> str:
    t = t.strip()
    for f in ("```python", "```py", "```"):
        if t.startswith(f):
            t = t[len(f):]
    return t.split("```")[0].strip()


def verify(code: str) -> bool:
    """The oracle. Runs the candidate against every example; no model is consulted."""
    ns: dict = {}
    try:
        exec(code, ns)
    except Exception:
        return False
    fn = ns.get("flatten")
    if not callable(fn):
        return False
    try:
        return all(fn(a) == b for a, b in CHECKS)
    except Exception:
        return False


def sweep(model: str, k: int) -> dict:
    print(f"\n  sweeping {model}  (K={k})", flush=True)
    wins, first, errs, t0 = 0, None, 0, time.time()
    for i in range(k):
        temp = 0.1 + (i / max(k - 1, 1)) * 0.7
        try:
            ok = verify(clean(generate(model, temp)))
        except Exception as e:
            errs += 1
            print(f"    {i+1:2d}  request failed ({type(e).__name__})", flush=True)
            continue
        wins += ok
        if ok and first is None:
            first = i + 1
        print(f"    {i+1:2d}  temp {temp:.2f}  {'VERIFIED' if ok else 'rejected'}", flush=True)
    att = k - errs
    p = wins / att if att else 0.0
    rec = {"model": model, "K": k, "attempts": att, "errors": errs, "verified": wins,
           "per_attempt_p": round(p, 3), "first_verified_at": first,
           "solved": first is not None,
           "predicted_at_K": round(1 - (1 - p) ** att, 4) if p else 0.0,
           "wall_clock_s": round(time.time() - t0, 1),
           "hardware": "AMD Radeon Pro W7900 48GB, ROCm 7.2.1, vLLM (Radeon Cloud instance)",
           "measured_over": "the instance's own HTTPS tunnel",
           "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    print(f"    -> p={p:.3f}  first={first}  "
          f"{'SOLVED' if rec['solved'] else 'NOT SOLVED'}  {rec['wall_clock_s']}s", flush=True)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--k", type=int, default=16)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + a.hours * 3600
    done: dict[str, dict] = {}
    last_seen: str | None = None
    quiet = 0

    print(f"watching the Radeon for up to {a.hours}h, sweeping each model as it appears")
    while time.time() < deadline:
        m = served()
        if m is None:
            quiet += 1
            if quiet % 10 == 1:
                print(f"  [{datetime.now():%H:%M}] nothing serving yet "
                      f"(model loading or swap in progress)", flush=True)
            time.sleep(30)
            continue
        quiet = 0
        if m in done:
            if m != last_seen:
                print(f"  [{datetime.now():%H:%M}] {m} back up, already swept", flush=True)
                last_seen = m
            time.sleep(60)
            continue
        last_seen = m
        rec = sweep(m, a.k)
        done[m] = rec
        (OUT / f"{m.replace('/', '_')}.json").write_text(json.dumps(rec, indent=1),
                                                         encoding="utf-8")
        (OUT / "all.json").write_text(json.dumps(list(done.values()), indent=1),
                                      encoding="utf-8")
        print(f"  {len(done)} model(s) swept so far", flush=True)

    print(f"\n  finished. {len(done)} model(s) measured on the Radeon.")
    for r in sorted(done.values(), key=lambda r: r["per_attempt_p"]):
        print(f"    {r['model'][:44]:<45} p={r['per_attempt_p']:<6} "
              f"first={str(r['first_verified_at'] or '-'):<4} "
              f"{'solved' if r['solved'] else 'NOT SOLVED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
