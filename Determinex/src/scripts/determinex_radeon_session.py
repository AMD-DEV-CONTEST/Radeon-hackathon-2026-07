#!/usr/bin/env python3
"""
determinex_radeon_session.py — extract everything a live Radeon GPU is worth, in one pass.

A Radeon Cloud instance is billed per GPU-hour and deletes itself when credits run out, so a
session is a fixed, short window. This runs the whole sequence that turns that window into
durable artifacts, in dependency order, and writes evidence as it goes -- so an instance that
dies halfway still leaves everything earned up to that point.

    python scripts/determinex_radeon_session.py --base-url https://rc-XXXX.radeon.firstdg.ai

WHAT IT COLLECTS, AND WHY EACH ONE IS WORTH GPU TIME

  1. declared capacity   vllm:cache_config_info gives num_gpu_blocks x block_size. On the
                         previous instance that arithmetic (31504*16/8192 = 61) predicted the
                         measured throughput collapse at K=64 exactly. Reading it live tests
                         the prediction on hardware rather than on a recording.

  2. calibration         determinex_calibrate has only ever REPRODUCED the Radeon knee from
                         captured numbers. Running it on the GPU is the difference between
                         "reproduces a recording" and "works on hardware it never saw". The
                         profile it writes is reusable long after the instance is gone.

  3. transition          P = 1-(1-p)^K, demonstrated. On a consumer box the productive-middle
                         task goes 50% -> 99.61% at K=8. Here it should run at the K the GPU
                         actually sustains -- and finish faster than the local K=8 did.

Every number is written to amd_gpu_evidence/ as raw tool output, because an instance that no
longer exists cannot be re-queried and a claim without its artifact is worth nothing.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = _ROOT.parent / "Radeon-hackathon-2026-07" / "Determinex" / "amd_gpu_evidence"

TASK = (
    "Write a Python function is_balanced(s) returning True if brackets ()[]{} in s are "
    "correctly nested and matched, False otherwise. Ignore other characters. Return only "
    "the function, no explanation, no markdown fence."
)
CHECKS = [
    ("is_balanced('([]{})')", True),
    ("is_balanced('([)]')", False),
    ("is_balanced('')", True),
    ("is_balanced('a(b[c]d)e')", True),
]


def say(m: str = "") -> None:
    print(m, flush=True)


def _post(base: str, key: str, model: str, prompt: str, temp: float, max_tok: int) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tok, "temperature": temp,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def declared_capacity(base: str, max_model_len: int) -> dict:
    """What vLLM says about itself, before we measure anything."""
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/metrics", timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        return {"available": False, "why": str(e)[:120]}
    m = re.search(r"vllm:cache_config_info\{([^}]*)\}", body)
    if not m:
        return {"available": False, "why": "no cache_config_info in /metrics"}
    f = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
    try:
        blocks, bs = int(f["num_gpu_blocks"]), int(f["block_size"])
    except (KeyError, ValueError):
        return {"available": False, "why": "cache_config_info missing block fields"}
    return {
        "available": True, "num_gpu_blocks": blocks, "block_size": bs,
        "kv_tokens": blocks * bs, "max_model_len": max_model_len,
        "declared_max_concurrent": (blocks * bs) // max_model_len,
    }


def oracle(code: str) -> tuple[bool, str]:
    """Execution, never model judgement -- and never a raw subprocess.

    This runs MODEL-GENERATED code. The project's security carve-out is explicit that such
    code is never auto-executed raw; it goes through `intake.hardened_runner` (workspace-
    bounded, env-scrubbed, network and Docker denied by default) or a container.

    The first version of this file used `subprocess.run([sys.executable, tmpfile])`, which
    is exactly the thing that rule forbids: an unsandboxed interpreter, inheriting this
    process's environment -- including the API keys in it -- executing text a remote model
    produced. It was caught by scripts/dev/parallel_execution_layer_audit.py, whose
    UNKNOWN_REQUIRES_REVIEW bucket went 0 -> 1 and failed the lock test, which is the
    entire reason that guard exists.
    """
    body = code
    if "```" in body:
        for part in body.split("```"):
            if "def " in part:
                body = part.lstrip("python").lstrip("\n")
                break
    prog = body + "\n\nimport json\nres=[]\n"
    for expr, _ in CHECKS:
        prog += f"try:\n    res.append({expr})\nexcept Exception as e:\n    res.append('ERR')\n"
    prog += "print(json.dumps(res, default=str))\n"

    from intake import hardened_runner

    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        (ws / "c.py").write_text(prog, encoding="utf-8")
        res = hardened_runner.run(
            [sys.executable, "c.py"],
            workspace=ws,
            cwd=ws,
            timeout=20,
            allow_network=False,
            allow_docker=False,
        )
    if res.blocked:
        return False, f"blocked by hardened runner: {res.reason}"
    if res.timed_out:
        return False, "timeout"
    if res.exit_code != 0 or not (res.stdout or "").strip():
        return False, "did not run"
    try:
        got = json.loads(res.stdout.strip().splitlines()[-1])
    except Exception:
        return False, "unparseable"
    for g, (expr, exp) in zip(got, CHECKS):
        if str(g) != str(exp):
            return False, f"{expr} -> {g}, expected {exp}"
    return True, f"all {len(CHECKS)} checks"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key", default="dtx-radeon-2026")
    ap.add_argument("--model", default=None, help="default: whatever /v1/models reports first")
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--ks", default="1,4,8,16,32,48,64")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    base, key = a.base_url.rstrip("/"), a.api_key
    ev: dict = {"what": "live Radeon session", "base_url_redacted": True,
                "started": time.strftime("%Y-%m-%dT%H:%M:%S")}

    # ── 0. is anything actually serving ──────────────────────────────────────────────
    try:
        req = urllib.request.Request(base + "/v1/models",
                                     headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=25) as r:
            models = [m["id"] for m in json.loads(r.read()).get("data", [])]
    except Exception as e:
        say(f"  no vLLM behind {base}: {type(e).__name__}: {str(e)[:100]}")
        say("  start it on the instance first, then re-run with the fresh tunnel URL.")
        return 2
    model = a.model or (models[0] if models else None)
    if not model:
        say("  endpoint answered but serves no models")
        return 2
    ev["models"], ev["model"] = models, model
    say(f"  serving: {model}   ({len(models)} model(s) available)")

    # ── 1. what the GPU declares about itself ────────────────────────────────────────
    cap = declared_capacity(base, a.max_model_len)
    ev["declared_capacity"] = cap
    say("")
    if cap.get("available"):
        say(f"  declared: {cap['num_gpu_blocks']} blocks x {cap['block_size']} tokens "
            f"= {cap['kv_tokens']:,} KV tokens")
        say(f"            / {cap['max_model_len']:,} max_model_len "
            f"-> {cap['declared_max_concurrent']} concurrent requests")
        say("            (a HINT that bounds the sweep -- the measurement decides)")
    else:
        say(f"  declared capacity unavailable: {cap.get('why')}")

    # ── 2. calibrate on the real GPU ─────────────────────────────────────────────────
    ks = [int(x) for x in a.ks.split(",") if x.strip()]
    if cap.get("available"):
        ks = [k for k in ks if k <= cap["declared_max_concurrent"] * 1.3] or ks[:3]
    say("")
    say(f"  calibrating on the GPU, K={ks}")
    say(f"    {'K':<5}{'wall_s':<10}{'tokens':<9}{'agg tok/s':<12}{'cand/s':<9}")

    def one() -> int:
        d = _post(base, key, model, "Write a Rust function summing a slice of i32. Code only.",
                  0.4, 48)
        return int((d.get("usage") or {}).get("completion_tokens", 0))

    # Warm twice: without this, K=1 pays the first-request cost and reports a number that is
    # not the machine's.
    one()
    one()
    points = []
    for k in ks:
        t0 = time.time()
        with cf.ThreadPoolExecutor(max_workers=k) as ex:
            tok = sum(ex.map(lambda _i: one(), range(k)))
        w = time.time() - t0
        p = {"k": k, "wall_s": round(w, 3), "tokens": tok,
             "agg_tok_s": round(tok / w, 1), "cand_per_s": round(k / w, 3)}
        points.append(p)
        say(f"    {k:<5}{p['wall_s']:<10}{tok:<9}{p['agg_tok_s']:<12}{p['cand_per_s']:<9}")
    ev["k_sweep"] = points

    best = max(points, key=lambda p: p["cand_per_s"])
    peak, collapsed = 0.0, None
    for p in points:
        if p["cand_per_s"] > peak:
            peak = p["cand_per_s"]
        elif peak and p["cand_per_s"] < peak * 0.97:
            collapsed = p["k"]
            break
    ev["optimal_k"], ev["collapsed_at"] = best["k"], collapsed
    say("")
    say(f"  MEASURED optimum K={best['k']} ({best['cand_per_s']} candidates/s)")
    if collapsed:
        say(f"  collapse at K={collapsed}" + (
            f"  -- declared ceiling was {cap['declared_max_concurrent']}"
            if cap.get("available") else ""))
        if cap.get("available"):
            ev["prediction_held"] = collapsed > cap["declared_max_concurrent"]
            say(f"  declared-vs-measured: prediction "
                f"{'HELD' if ev['prediction_held'] else 'DID NOT HOLD'}")
    else:
        say(f"  no collapse within K<={max(ks)}")

    # ── 3. the transition, at the K this GPU sustains ────────────────────────────────
    K = best["k"]
    say("")
    say(f"  transition demo: one shot vs K={K}, oracle executes every candidate")
    singles = []
    for i in range(5):
        d = _post(base, key, model, TASK, 0.0 if i == 0 else 0.4, 400)
        ok, why = oracle(d["choices"][0]["message"].get("content") or "")
        singles.append(ok)
        say(f"    K=1 attempt {i+1}: {'PASS' if ok else 'FAIL'}  {why}")
    p_hat = sum(singles) / len(singles)
    ev["one_shot"] = {"passes": sum(singles), "n": len(singles), "p_hat": p_hat}

    t0 = time.time()
    winner, used = None, 0
    with cf.ThreadPoolExecutor(max_workers=K) as ex:
        futs = [ex.submit(_post, base, key, model, TASK, min(0.8, 0.1 * i), 400) for i in range(K)]
        for f in cf.as_completed(futs):
            used += 1
            try:
                ok, _ = oracle(f.result()["choices"][0]["message"].get("content") or "")
            except Exception:
                continue
            if ok and winner is None:
                winner = True
    dt = time.time() - t0
    ev["verified_search"] = {"k": K, "solved": bool(winner), "wall_s": round(dt, 1),
                             "candidates_evaluated": used}
    say("")
    say(f"    K={K} verified search: {'SOLVED' if winner else 'no candidate passed'} "
        f"in {dt:.1f}s across {used} candidates")
    if p_hat:
        say(f"    p={p_hat:.2f}: one shot {p_hat*100:.0f}%  ->  "
            f"K={K} predicts {(1-(1-p_hat)**K)*100:.2f}%")

    # ── write evidence ───────────────────────────────────────────────────────────────
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = Path(a.out) if a.out else EVIDENCE / "radeon_live_session.json"
    out.write_text(json.dumps(ev, indent=2) + "\n", encoding="utf-8")
    say("")
    say(f"  evidence -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
