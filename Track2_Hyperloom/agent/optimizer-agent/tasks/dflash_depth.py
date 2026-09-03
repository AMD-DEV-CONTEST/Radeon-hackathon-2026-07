import os
"""
Task plugin: find the DFlash draft depth that maximizes decode throughput on this RDNA4 box.

This is the "framework of what we learned" handed to a LOCAL model: the methodology + the hardware
facts + the DFlash-specific knowledge an earlier assisted session earned — then the model has to
re-derive the optimum by running real benchmarks itself (it is never told the answer is depth 4).

Pluggable: copy this file, swap SYSTEM/GOAL/TOOLS/execute() to tune a different lever (rpb, quant,
nwarps) or a different target model / GPU arch.
"""
import subprocess, re, shlex

NAME = "dflash_depth"

# --- the knowledge we mined, given to the local model as its operating framework ---------------
SYSTEM = """You are a fully-local GPU inference-optimization agent running on an AMD Radeon AI PRO
R9700 (RDNA4 / gfx1201). You tune LLM inference by RUNNING EXPERIMENTS — you never guess or invent
numbers; the only way you learn a speed is to call a tool that measures it on the real GPU.

METHODOLOGY (follow strictly):
1. Establish the plain-decode BASELINE first (run_baseline).
2. Change ONE variable at a time; measure it; compare to baseline.
3. Prefer the fewest experiments that find the optimum — do not brute-force all values blindly.
4. A result is only real once measured. Report medians of what you measured, never extrapolate.

DFLASH FACTS you already know about this hardware:
- DFlash is block-diffusion speculative decoding; the drafter's block_size is 16, so the draft
  depth (spec-draft-n-max) can be at most 15.
- Acceptance falls as depth rises (deeper drafts compound rejection); throughput is a TRADE-OFF
  that peaks at some middle depth, not at the extremes. Your job is to find that peak.
- The draft runs on the GPU alongside the target; context is fixed at 1024.

GOAL BEHAVIOR: probe a few depths intelligently (e.g. bracket then refine), find the depth with the
highest decode tokens/sec, and stop as soon as you're confident. Then output a final summary line:
'BEST: depth=<d>, <t/s> t/s, <speedup>x vs baseline (accept <a>%)' and briefly justify it.
"""

GOAL = ("Find the DFlash draft depth that gives the highest decode throughput on this box, and "
        "how much faster it is than plain decode. Begin by measuring the baseline.")

TOOLS = [
    {"type": "function", "function": {
        "name": "run_baseline",
        "description": "Measure plain (non-speculative) decode throughput of the target model on the "
                       "benchmark GPU. Returns tokens/sec. Call once at the start.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "run_dflash_bench",
        "description": "Run a DFlash speculative-decoding benchmark at the given draft depth on the "
                       "benchmark GPU. Returns decode tokens/sec, accept rate, and speedup vs baseline.",
        "parameters": {"type": "object", "properties": {
            "depth": {"type": "integer", "description": "draft depth (spec-draft-n-max), 1..15"}},
            "required": ["depth"]},
    }},
]

# --- real benchmark implementations (run on the TEST card, isolated) ---------------------------
REPO   = os.environ.get("HYPERLOOM_REPO", "/home/jmonk/src/mainline-llama.cpp-mxfp8")
TARGET = "/aipool/models/qwen3.6-27b-bf16-mtp/Qwen3.6-27B-F8E4M3.gguf"
DRAFT  = "/aipool/models/qwen3.6-27b-dflash-draft-f8e4m3.gguf"
NGEN   = "64"                       # bounded so the agent loop iterates quickly
PROMPT = "Explain how speculative decoding speeds up large language model inference."
_baseline = {"tok_s": None}

def _sh(cmd, card, timeout=400):
    full = f"cd {REPO} && source use-rocm714.env >/dev/null 2>&1 && HIP_VISIBLE_DEVICES={card} {cmd}"
    p = subprocess.run(["bash", "-lc", full], capture_output=True, text=True, timeout=timeout)
    return p.stdout + "\n" + p.stderr

def _f(pattern, text, default=None):
    m = re.search(pattern, text, re.I)
    return float(m.group(1)) if m else default

def execute(fn, args, test_card):
    if fn == "run_baseline":
        out = _sh(f"build-roc8-714/bin/llama-bench -m {shlex.quote(TARGET)} -ngl 99 "
                  f"-p 0 -n {NGEN} -r 2 2>&1", test_card)
        # llama-bench tg row: t/s is the 8th '|' field; fall back to a regex sweep
        ts = None
        for line in out.splitlines():
            if "tg" in line and "|" in line:
                parts = [x.strip() for x in line.split("|")]
                for x in reversed(parts):
                    m = re.search(r"([\d.]+)", x)
                    if m: ts = float(m.group(1)); break
        ts = ts or _f(r"([\d.]+)\s*(?:t/s|tokens per second)", out)
        _baseline["tok_s"] = ts
        return {"tok_s": ts, "note": "plain decode baseline"}

    if fn == "run_dflash_bench":
        d = int(args["depth"])
        out = _sh(f"build-roc8-714/bin/llama-speculative-simple -m {shlex.quote(TARGET)} "
                  f"--model-draft {shlex.quote(DRAFT)} -ngl 99 -ngld 99 "
                  f"--spec-type draft-dflash --spec-draft-n-max {d} -c 1024 --temp 0 "
                  f"-n {NGEN} -p {shlex.quote(PROMPT)} 2>&1", test_card)
        n_draft = _f(r"n_drafted\s*[=:]\s*(\d+)", out)
        n_acc   = _f(r"n_accept\s*[=:]\s*(\d+)", out)
        accept  = _f(r"accept[=:\s]+([\d.]+)\s*%", out)
        if accept is None and n_draft and n_acc: accept = 100.0 * n_acc / n_draft
        toks = _f(r"(?:decoded|decode|generation|eval).*?([\d.]+)\s*t/s", out) or \
               _f(r"([\d.]+)\s*t/s", out)
        base = _baseline["tok_s"]
        speedup = round(toks / base, 3) if (toks and base) else None
        return {"depth": d, "tok_s": toks, "accept_pct": accept, "speedup_vs_baseline": speedup}

    return {"error": f"unknown tool {fn}"}
