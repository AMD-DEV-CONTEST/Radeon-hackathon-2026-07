#!/usr/bin/env python3
"""decompose_run.py — when one-shot fails, cut the task up and verify the pieces.

A model that cannot write the whole function may still be able to write each piece of it.
P = 1 - (1-p)^K needs p > 0, and p is per-TASK: a task with four requirements at once can sit
at p=0 while each requirement alone sits well above it. Decomposition moves the measurement to
where p is non-zero.

Every sub-step has its own oracle and is verified independently. The composition itself is
fixed harness code, not model output - so a solve here means the model supplied every piece
that was actually needed and each piece was checked. Nothing is credited on the strength of
the whole thing looking right.

This is the honest answer to a p=0 row: try the tool built for it and report what happened,
rather than either hiding the zero or leaving it unexplained.

    python .local/decompose_run.py MODEL_REPO
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000/v1"
HDR = {"Authorization": "Bearer dtx-radeon-2026", "Content-Type": "application/json"}

# Each step: (name, prompt, oracle). The oracle takes the callable the model produced and
# returns True only if it satisfies every example - the same rule as the whole-task oracle.
STEPS = [
    (
        "join_path",
        "Write a Python function join_path(parent, key) that joins a parent path and a dict "
        "key with a dot, but returns the key alone when parent is empty. "
        "join_path('', 'a') returns 'a'. join_path('a', 'b') returns 'a.b'. "
        "join_path('a.b', 'c') returns 'a.b.c'. Output only the function.",
        lambda f: (f("", "a") == "a" and f("a", "b") == "a.b" and f("a.b", "c") == "a.b.c"),
    ),
    (
        "index_path",
        "Write a Python function index_path(parent, i) that appends a list index in square "
        "brackets to a path. index_path('x', 0) returns 'x[0]'. index_path('a.b', 2) returns "
        "'a.b[2]'. index_path('', 1) returns '[1]'. Output only the function.",
        lambda f: (f("x", 0) == "x[0]" and f("a.b", 2) == "a.b[2]" and f("", 1) == "[1]"),
    ),
    (
        "is_leaf",
        "Write a Python function is_leaf(v) that returns True when a value is NOT a dict and "
        "NOT a list, and False when it is either. is_leaf(1) is True. is_leaf(None) is True. "
        "is_leaf({}) is False. is_leaf([]) is False. Output only the function.",
        lambda f: (f(1) is True and f(None) is True and f({}) is False and f([]) is False),
    ),
]

# The composition is OURS, not the model's. The model supplies the verified parts; the harness
# assembles them. That is the point of decomposition - the system carries the structure.
COMPOSE = """
def flatten(obj):
    out = {}
    def walk(o, path):
        if is_leaf(o):
            out[path] = o
        elif isinstance(o, dict):
            if not o and path:
                out[path] = o
            for k, v in o.items():
                walk(v, join_path(path, k))
        else:
            for i, v in enumerate(o):
                walk(v, index_path(path, i))
    walk(obj, "")
    return out
"""

CHECKS = [({"a": {"b": 1}}, {"a.b": 1}),
          ({"x": [1, 2]}, {"x[0]": 1, "x[1]": 2}),
          ({"a": {"b": [{"c": 3}]}}, {"a.b[0].c": 3}),
          ({}, {}),
          ({"k": None}, {"k": None}),
          ({"p": {"q": {"r": [7, 8]}}}, {"p.q.r[0]": 7, "p.q.r[1]": 8})]


def generate(model, prompt, temp):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 1200, "temperature": temp}).encode()
    rq = urllib.request.Request(f"{BASE}/chat/completions", body, HDR)
    with urllib.request.urlopen(rq, timeout=180) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def clean(t):
    # Reasoning models (Qwen3 and kin) emit <think>...</think> first. Left in,
    # the fence matcher finds code the model was only considering, and with a
    # tight token budget the real answer is never reached at all.
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S)
    t = re.sub(r"^.*?</think>", "", t, flags=re.S)   # unterminated: budget ran out
    m = re.search(r"```(?:python|py)?[ \t]*\n(.*?)```", t, re.S)
    if m:
        return m.group(1).strip()
    lines = t.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r"\s*(def |import |from )", ln):
            return "\n".join(lines[i:]).strip()
    return t.strip()


def solve_step(model, name, prompt, oracle, k):
    """Verified search on ONE step. Returns the accepted source, or None."""
    for i in range(k):
        temp = 0.1 + (i / max(k - 1, 1)) * 0.7
        # A transport failure is NOT a model failure. The first version swallowed both in
        # one except, so a model that had been swapped out from under the run read as a model
        # that could not write a two-line function. Distinguish them, and abort on transport
        # errors rather than quietly scoring zero.
        try:
            raw = generate(model, prompt, temp)
        except Exception as e:
            print(f"    {name:<12} TRANSPORT ERROR {type(e).__name__} - aborting, not scoring",
                  flush=True)
            raise SystemExit(f"transport failure against {model}: {e}")
        try:
            code = clean(raw)
            ns = {}
            exec(code, ns)
            fn = ns.get(name)
            if callable(fn) and oracle(fn):
                print(f"    {name:<12} verified at sample {i+1}", flush=True)
                return code
        except Exception:
            pass   # a wrong or broken candidate IS a model failure - that one counts
    print(f"    {name:<12} NOT verified in {k} samples", flush=True)
    return None


def main():
    model = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    rq = urllib.request.Request(f"{BASE}/models", headers=HDR)
    with urllib.request.urlopen(rq, timeout=30) as r:
        live = json.load(r)["data"][0]["id"]
    if live != model:
        raise SystemExit(f"served model is {live}, not {model} - refusing to attribute results")
    print(f"  decomposed solve: {model}  (K={k} per step, served model confirmed)", flush=True)
    t0 = time.time()

    parts, per_step = {}, {}
    for name, prompt, oracle in STEPS:
        src = solve_step(model, name, prompt, oracle, k)
        per_step[name] = src is not None
        if src is None:
            break
        parts[name] = src

    rec = {"model": model, "mode": "decomposed", "K_per_step": k,
           "steps": per_step, "steps_solved": sum(per_step.values()),
           "steps_total": len(STEPS),
           "hardware": "AMD Radeon Pro W7900 48GB, ROCm 7.2.1, vLLM"}

    if len(parts) == len(STEPS):
        ns = {}
        try:
            exec("\n".join(parts.values()) + COMPOSE, ns)
            f = ns["flatten"]
            ok = all(f(a) == b for a, b in CHECKS)
        except Exception as e:
            ok = False
            rec["compose_error"] = f"{type(e).__name__}: {e}"[:200]
        rec["solved"] = ok
        print(f"  composed -> {'SOLVED' if ok else 'composed but failed the full oracle'}")
    else:
        rec["solved"] = False
        print(f"  {len(parts)}/{len(STEPS)} steps verified - cannot compose")

    rec["wall_clock_s"] = round(time.time() - t0, 1)
    out = f"/workspace/determinex_breadth/decomposed_{model.replace('/', '_')}.json"
    open(out, "w").write(json.dumps(rec, indent=1))
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
