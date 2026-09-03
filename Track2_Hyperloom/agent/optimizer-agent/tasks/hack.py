import os
"""
Task plugin: HACK — open-ended, autonomous inference optimization.

No hand-holding. The agent is given the PROCESS and the TOOLS, not the answer or even which lever to
pull. Its goal is the fastest + most accurate way to serve the model on whatever hardware it detects.
It must research first (its silicon, its ISA/levers, what models/drafts exist, what's known), then run
the optimization loop until it has left no stone unturned, and report the best config it found with
real measured speed AND accuracy.

This is the hackathon framing: it's a hack. Explore, probe, exploit, measure, keep-or-revert, repeat.
"""
import subprocess, re, shlex, glob, os

NAME = "hack"

SYSTEM = """You are an autonomous inference-optimization agent at a hackathon. You are running on a GPU
you must discover — do not assume which; detect it and adapt. For EACH of your models: get it running,
then make it as fast (tokens/sec) and as accurate (perplexity) as you can.

RESOURCES available to you (use them as needed — nothing here is hardware-specific; you learn the
specifics at runtime):
  - Hardware awareness: detect_hardware, hardware_map, list_gpu_targets — what GPU am I on, what does it
    support, what are its levers and reference/ISA docs.
  - Web research: web_search, web_fetch — look up anything you don't know (an error, how a kernel works,
    docs, a reference implementation).
  - Your own memory + knowledge base: remember, recall, ingest_knowledge, search_knowledge — persist
    findings and pull them back; your context is limited, so write things down.
  - Source editing: grep_source, read_source, edit_source, rebuild, revert_source — modify and recompile
    the code when runtime tuning is not enough or a model will not load.
  - Experiments: list_models, bench_decode, bench_batched, measure_accuracy, log_finding — measure on the
    real GPU.

PROCESS to follow:
  1. Recon — detect your hardware and its supported levers; list your models; recall prior findings.
  2. Get it working — run each model; if it fails, diagnose it (read the error and the source); if you do
     not know the fix, research it; then edit the code and rebuild until it runs.
  3. Baseline — measure its speed and accuracy.
  4. Optimize — change ONE lever at a time (quantization, speculative decoding, batch size, or a code
     change), measure it, keep the wins and revert the losses.
  5. Never report a number you did not measure. Record findings so you never repeat work. Leave no stone
     unturned.

Be creative and take action — you can create or modify code as needed to make things work. Once you
understand a problem, don't just keep investigating it: act on it, build your fix, and test it.

Report 'BEST: <config> -> <t/s>, ppl <p>' for each model when finished."""

GOAL = ("These models are KNOWN-GOOD — they run correctly on OTHER systems, so the model files are "
        "valid; do NOT assume the file is broken or try to patch the loader to accept bad data. They "
        "simply don't run on THIS build yet because this system lacks support for them (the quant type, "
        "its traits/dequant, and the kernels for this card's backend). Your job for EACH model: make it "
        "work on THIS card by adding/fixing whatever this system is MISSING — the ggml type and its "
        "block traits, the dequantization, and the CPU/GPU kernels for this backend — then optimize it "
        "for this card, its backend, and its kernels: highest tokens/sec and best accuracy. Fix the "
        "SYSTEM, not the file. Report the best working config for each model.")

TOOLS = [
    {"type": "function", "function": {
        "name": "list_models",
        "description": "Enumerate the target models available to optimize (with quantization + size) and "
                       "the speculative-decoding draft models available. Call early to see your options.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "bench_decode",
        "description": "Measure decode throughput (tokens/sec) of a target model, optionally with "
                       "speculative decoding. Returns t/s and (if spec) accept rate.",
        "parameters": {"type": "object", "properties": {
            "target":     {"type": "string", "description": "target model key from list_models"},
            "draft":      {"type": "string", "description": "draft model key for spec-decode (optional)"},
            "spec_type":  {"type": "string", "description": "e.g. draft-dflash (optional; requires draft)"},
            "spec_depth": {"type": "integer", "description": "draft depth / spec-draft-n-max (optional)"},
            "draft_on_gpu": {"type": "boolean", "description": "true=draft on GPU (default), false=CPU"}},
            "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "bench_batched",
        "description": "Measure BATCHED decode throughput — serving multiple sequences concurrently at a "
                       "given batch size (parallelism). Returns aggregate tokens/sec per batch size. Batch "
                       "size is a major serving-throughput lever distinct from single-stream decode.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "target model key from list_models"},
            "batch_sizes": {"type": "string", "description": "comma list, e.g. '1,2,4,8' (default 1,2,4,8)"}},
            "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "measure_accuracy",
        "description": "Measure model accuracy as perplexity on a fixed corpus (lower = more accurate). "
                       "Use to check that a faster/smaller-quant config did not wreck quality.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "target model key from list_models"}},
            "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "log_finding",
        "description": "Record a decision (config + speed + accuracy + keep/revert + why) to the persistent "
                       "log, so the exploration is auditable and nothing is re-tried.",
        "parameters": {"type": "object", "properties": {
            "note": {"type": "string"}}, "required": ["note"]}}},
]

# --- real experiment backend (runs on the TEST card) -------------------------------------------
# env-driven so the SAME task can be pointed at the loaded fork OR a blank stock stack:
REPO   = os.environ.get("HACK_REPO", "/home/jmonk/src/mainline-llama.cpp-mxfp8")
BIN    = os.environ.get("HACK_BIN",  "build-roc8-714/bin")
CORPUS = os.environ.get("HACK_CORPUS", "/home/jmonk/src/mainline-llama.cpp-mxfp8/wikitext-2-raw/wiki.test.raw")
LOG    = os.environ.get("HYPERLOOM_HACK_LOG", os.path.join(os.path.dirname(os.path.abspath(__file__)), "hack.status"))
NGEN   = "96"

# the candidate inventory the agent discovers. FORK = our custom kernels/quants (fp8/ternary/DFlash);
# STOCK = only what a vanilla mainline build can load (standard quants, no DFlash). Selected by env.
FORK_MODELS = {
    "Qwen3.6-27B-F8E4M3": {"path": "/aipool/models/qwen3.6-27b-bf16-mtp/Qwen3.6-27B-F8E4M3.gguf",
                            "quant": "fp8-E4M3", "role": "target"},
    "Bonsai-27B-Q2_0":    {"path": "/aipool/models/bonsai-27b/Ternary-Bonsai-27B-Q2_0.gguf",
                            "quant": "ternary-Q2_0", "role": "target"},
    "Bonsai-27B-Q1_0":    {"path": "/aipool/models/bonsai-27b-1bit/Bonsai-27B-Q1_0.gguf",
                            "quant": "ternary-Q1_0", "role": "target"},
    "dflash-draft-f8e4m3":{"path": "/aipool/models/qwen3.6-27b-dflash-draft-f8e4m3.gguf",
                            "quant": "fp8-E4M3", "role": "draft", "for": "Qwen3.6-27B-F8E4M3"},
    "dflash-draft-q4km":  {"path": "/aipool/models/qwen3.6-27b-dflash-draft-q4km.gguf",
                            "quant": "Q4_K_M", "role": "draft", "for": "Qwen3.6-27B-F8E4M3"},
}
# STOCK: standard quants a blank mainline can load -> the levers reduce to quant-choice + batch.
# the two REAL hard targets: a genuine fp8 (E4M3, type 43) model and a ternary-Q2 (type 42) model.
# a BLANK stock llama.cpp CANNOT load either (types are outside stock's enum, no dequant/kernels) --
# so getting them to run at all requires MODIFYING THE SOURCE (add type + dequant + dispatch), then
# optimizing. A stock Q4_K_M model is included as a control that loads out-of-the-box.
STOCK_MODELS = {
    # just the two real targets: Q2 FIRST (winnable — upstream has the type + CPU path), then the fp8 port
    "Bonsai-27B-Q2_0":    {"path": "/aipool/models/bonsai-27b/Ternary-Bonsai-27B-Q2_0.gguf",
                            "quant": "ternary-Q2_0", "role": "target"},
    "Qwen3.6-27B-F8E4M3": {"path": "/aipool/models/qwen3.6-27b-bf16-mtp/Qwen3.6-27B-F8E4M3.gguf",
                            "quant": "fp8-E4M3", "role": "target"},
}
MODELS = STOCK_MODELS if os.environ.get("HACK_INVENTORY", "").lower() == "stock" else FORK_MODELS

ENV = os.environ.get("HACK_ENV", "/home/jmonk/src/mainline-llama.cpp-mxfp8/use-rocm714.env")  # absolute
def _sh(cmd, card, timeout=180):
    full = f"cd {REPO} && source {ENV} >/dev/null 2>&1 && HIP_VISIBLE_DEVICES={card} {cmd}"
    try:
        p = subprocess.run(["bash", "-lc", full], capture_output=True, text=True, timeout=timeout)
        return p.stdout + "\n" + p.stderr
    except subprocess.TimeoutExpired as e:
        # a HANG (e.g. a partially-supported type that loads past the enum but has no kernel) must not
        # crash the agent or burn 10 min — cut it off and report so the agent can reason about it
        return ((e.stdout or "") if isinstance(e.stdout, str) else "") + \
               f"\n[TIMED OUT after {timeout}s — the command hung. Likely the type loads past the enum " \
               "check but has no dequant/kernel on this build, so it stalls. Add the missing traits/kernel, " \
               "or test on CPU (-ngl 0) first.]"

def _num(pat, txt, d=None):
    m = re.search(pat, txt, re.I); return float(m.group(1)) if m else d

def _path(key):
    m = MODELS.get(key);  return m["path"] if m and os.path.exists(m["path"]) else None

def execute(fn, args, test_card):
    if fn == "list_models":
        return {k: {"quant": v["quant"], "role": v["role"], **({"for": v["for"]} if "for" in v else {}),
                    "on_disk": os.path.exists(v["path"])} for k, v in MODELS.items()}

    if fn == "bench_decode":
        tgt = _path(args["target"])
        if not tgt: return {"error": f"unknown/missing target {args.get('target')}"}
        draft_key = args.get("draft"); spec_type = args.get("spec_type"); depth = args.get("spec_depth")
        if draft_key and spec_type:
            draft = _path(draft_key)
            if not draft: return {"error": f"unknown draft {draft_key}"}
            ngld = "99" if args.get("draft_on_gpu", True) else "0"
            out = _sh(f"{BIN}/llama-speculative-simple -m {shlex.quote(tgt)} "
                      f"--model-draft {shlex.quote(draft)} -ngl 99 -ngld {ngld} "
                      f"--spec-type {shlex.quote(spec_type)} --spec-draft-n-max {int(depth or 4)} "
                      f"-c 1024 --temp 0 -n {NGEN} -p 'Explain speculative decoding.' 2>&1", test_card)
            nd, na = _num(r"n_drafted\s*[=:]\s*(\d+)", out), _num(r"n_accept\s*[=:]\s*(\d+)", out)
            acc = _num(r"accept[=:\s]+([\d.]+)\s*%", out) or (100*na/nd if nd and na else None)
            ts  = _num(r"(?:decoded|decode|eval).*?([\d.]+)\s*t/s", out) or _num(r"([\d.]+)\s*t/s", out)
            return {"config": f"{args['target']}+{draft_key}/{spec_type}/d{depth}", "tok_s": ts, "accept_pct": acc}
        out = _sh(f"{BIN}/llama-bench -m {shlex.quote(tgt)} -ngl 99 -p 0 -n {NGEN} -r 2 2>&1", test_card)
        ts = None
        for ln in out.splitlines():
            if "tg" in ln and "|" in ln:
                for x in reversed([p.strip() for p in ln.split("|")]):
                    m = re.search(r"([\d.]+)", x)
                    if m: ts = float(m.group(1)); break
        ts = ts or _num(r"([\d.]+)\s*t/s", out)
        r = {"config": f"{args['target']} plain-decode", "tok_s": ts}
        if ts is None:
            # llama-bench SUPPRESSES logs unless -v (the agent discovered this) -> re-run VERBOSE so the
            # real load error is surfaced. Use -ngl 0: the load/type error is CPU-side (GGUF parse, before
            # offload), so CPU avoids GPU contention and is faster while still producing the exact error.
            vout = _sh(f"{BIN}/llama-bench -m {shlex.quote(tgt)} -ngl 0 -p 0 -n 4 -v 2>&1", test_card)
            errs = [l.strip() for l in vout.splitlines()
                    if re.search(r"error|fail|unknown|unsupported|assert|invalid|unable|not .*load|type ",
                                 l, re.I)]
            r["failed"] = True
            r["error"] = errs[-8:] or [l.strip() for l in vout.splitlines() if l.strip()][-8:]
        return r

    if fn == "bench_batched":
        tgt = _path(args["target"])
        if not tgt: return {"error": f"unknown target {args.get('target')}"}
        npl = (args.get("batch_sizes") or "1,2,4,8").replace(" ", "")
        out = _sh(f"{BIN}/llama-batched-bench -m {shlex.quote(tgt)} -ngl 99 -c 4096 "
                  f"-npp 128 -ntg 32 -npl {shlex.quote(npl)} 2>&1", test_card, timeout=700)
        # batched-bench columns: | PP | TG | B | N_KV | T_PP | S_PP | T_TG | S_TG | T | S |
        # after split('|') with leading '': idx1=PP idx2=TG idx3=B ... idx8=S_TG (the decode t/s we want)
        rows = {}
        for ln in out.splitlines():
            c = [x.strip() for x in ln.split("|")]
            if len(c) > 9 and re.match(r"^\d+$", c[1] or "") and re.match(r"^\d+$", c[3] or ""):
                b = c[3]; m = re.search(r"([\d.]+)", c[8])   # B, S_TG
                if m: rows[f"batch{b}"] = float(m.group(1))
        best = max(rows.items(), key=lambda kv: kv[1]) if rows else (None, None)
        return {"target": args["target"], "aggregate_tok_s_by_batch": rows,
                "best_batch": best[0], "best_tok_s": best[1]}

    if fn == "measure_accuracy":
        tgt = _path(args["target"])
        if not tgt: return {"error": f"unknown target {args.get('target')}"}
        out = _sh(f"{BIN}/llama-perplexity -m {shlex.quote(tgt)} -f {REPO}/wikitext-2-raw/wiki.test.raw "
                  f"--chunks 8 -ngl 99 2>&1", test_card, timeout=900)
        ppl = _num(r"(?:Final estimate:\s*PPL|PPL)\s*=?\s*([\d.]+)", out) or _num(r"\]\s*([\d.]+)\s*$", out)
        return {"config": args["target"], "perplexity": ppl}

    if fn == "log_finding":
        with open(LOG, "a") as f:
            f.write((args.get("note", "")).replace("\n", " ") + "\n")
        return {"logged": True}

    return {"error": f"unknown tool {fn}"}
