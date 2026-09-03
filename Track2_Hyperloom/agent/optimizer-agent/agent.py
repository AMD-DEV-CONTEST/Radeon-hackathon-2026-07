#!/usr/bin/env python3
"""
optimizer-agent — a private, fully-local AI agent that tunes LLM inference on AMD Radeon (RDNA4).

Architecture (JM constraint: "it has to fit on one card, testing the other"):
  - BRAIN: a local tool-calling model served by lemonade, pinned to ONE card (fits in 32GB).
  - BENCH: the agent's tools run REAL benchmarks on the OTHER card, isolated (HIP_VISIBLE_DEVICES),
           so measurements are never corrupted by the brain's own inference.
  - PLUGGABLE: an optimization "task" = (knowledge it was given + tools + goal). Swap the task to
           tune a different lever (DFlash depth, rpb, quant choice, ...) or target different hardware.

The brain never guesses numbers — it can only learn by calling tools that measure on real silicon.
This is the whole thesis: the agent optimizes inference by running experiments, exactly like the
earlier assisted session that produced the 2.34x DFlash result — but now on a local model, on-device.

Run:  python3 agent.py --task dflash_depth
"""
import os, json, time, argparse, importlib, urllib.request
import hardware, memory, codetools, research

# ---- config -------------------------------------------------------------------
BASE_URL   = os.environ.get("LEMONADE_URL", "http://localhost:13305/v1")
BRAIN      = os.environ.get("BRAIN_MODEL", "Qwen-AgentWorld-35B-A3B-GGUF-UD-Q4_K_XL")  # 20.8GB, fits 1 card
BRAIN_CARD = os.environ.get("BRAIN_CARD", "1")   # brain served here (lemonade pinned)
TEST_CARD  = os.environ.get("TEST_CARD",  "0")   # benchmarks run here, isolated
MAX_STEPS    = int(os.environ.get("MAX_STEPS", "40"))
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "0"))   # outer loop: 0 = UNLIMITED, retry until success
THINK_LOG    = os.environ.get("THINK_LOG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "thinking.log"))


def _trim(messages):
    """Drop the middle of a long conversation (old grep/read churn) to fit context — keep the system
    prompt, the initial task, and recent turns. Never leave an orphan 'tool' message at the front."""
    if len(messages) <= 26:
        return messages
    head, tail = messages[:2], messages[-22:]
    while tail and tail[0].get("role") == "tool":   # a tool msg needs its preceding assistant tool_call
        tail = tail[1:]
    return head + [{"role": "user", "content": "[earlier investigation trimmed to save context]"}] + tail

def chat(messages, tools):
    """One turn against the local tool-calling model. Robust: on context-overflow (HTTP 400) it trims
    and retries; any other HTTP/network error returns a soft message instead of crashing the agent."""
    for attempt in range(3):
        body = json.dumps({"model": BRAIN, "messages": messages, "tools": tools or [],
                           "tool_choice": "auto", "temperature": 0, "max_tokens": 4000}).encode()
        req = urllib.request.Request(BASE_URL + "/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            if e.code == 400 and attempt < 2:      # usually context overflow — trim and retry
                messages[:] = _trim(messages)
                continue
            return {"content": f"[chat error {e.code}; continuing]"}
        except Exception:
            if attempt < 2:
                time.sleep(2); continue
            return {"content": "[chat error; continuing]"}


def log_think(attempt, step, msg):
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    content   = msg.get("content") or ""
    if not (reasoning or content):
        return
    with open(THINK_LOG, "a") as f:
        f.write(f"\n{'='*70}\n[attempt {attempt} · step {step}] THINKING\n{'='*70}\n")
        if reasoning: f.write("--- reasoning ---\n" + reasoning.strip() + "\n")
        if content:   f.write("--- says ---\n" + content.strip() + "\n")
    preview = (reasoning or content).strip().replace("\n", " ")
    if preview: print(f"   \U0001f9e0 {preview[:200]}")


def dispatch(fn, args, task):
    if fn in ("detect_hardware", "hardware_map", "list_gpu_targets"):
        return hardware.hw_execute(fn, args)
    if fn in ("remember", "recall", "ingest_knowledge", "search_knowledge"):
        return memory.mem_execute(fn, args)
    if fn in ("web_search", "web_fetch"):
        return research.research_execute(fn, args)
    if fn in ("grep_source", "read_source", "edit_source", "write_file", "rebuild", "revert_source"):
        return codetools.code_execute(fn, args)
    return task.execute(fn, args, TEST_CARD)


def run_attempt(task, tools, sys_content, attempt):
    """One attempt (fresh context). Memory persists on disk across attempts. Returns (final, hit_max)."""
    user = task.GOAL
    if attempt > 1:
        user += (f"\n\nThis is attempt {attempt}. Earlier attempts did not finish. FIRST call recall() to "
                 "review what you already learned and the diagnosis of what went wrong last time, then "
                 "continue from there — do NOT repeat prior work or prior mistakes.")
    messages = [{"role": "system", "content": sys_content}, {"role": "user", "content": user}]
    sig_counts = {}
    recent_sigs = []       # rolling window of last actions — catches A/B/A/B oscillation the count misses
    observations = []      # grounded facts for the rubric diagnosis (real errors/edits/rebuilds)
    reads_since_edit = 0   # investigation-without-edit budget (kills the grep/read spiral)
    for step in range(1, MAX_STEPS + 1):
        msg = chat(messages, tools); messages.append(msg); log_think(attempt, step, msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            final = (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "").strip()
            if not final and step < MAX_STEPS:
                messages.append({"role": "user", "content": "Continue — you have not reported a final "
                                 "'BEST:' line for every model yet."})
                continue
            return final, False, observations
        step_sigs = set()
        for c in calls:
            fn = c["function"]["name"]
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                # a malformed/truncated tool call must NOT crash the agent — feed it back and continue
                print(f"[a{attempt} s{step}] malformed tool-call args (truncated?) — feeding back to retry")
                messages.append({"role": "tool", "tool_call_id": c["id"], "name": fn,
                    "content": json.dumps({"error": "your tool-call arguments were not valid JSON (likely "
                    "truncated). Retry with valid JSON. If it was a large edit_source, split it into a "
                    "smaller single edit."})})
                continue
            print(f"[a{attempt} s{step}] TOOL {fn}({args}) ...", flush=True)
            t0 = time.time()
            result = dispatch(fn, args, task)
            print(f"          -> {str(result)[:300]}  ({time.time()-t0:.1f}s)")
            messages.append({"role": "tool", "tool_call_id": c["id"], "name": fn,
                             "content": json.dumps(result)})
            # capture grounding facts for the OODA diagnosis: real errors, edits, rebuild outcomes, loads
            rs = str(result)
            if fn in ("edit_source", "write_file", "rebuild") or "'failed': True" in rs \
               or "error" in rs.lower() or "'tok_s':" in rs:
                observations.append(f"{fn}({str(args)[:80]}) -> {rs[:220]}")
            # investigation budget: reset on a real edit, count read/search actions
            if fn in ("edit_source", "write_file"):
                reads_since_edit = 0
            elif fn in ("grep_source", "read_source", "search_knowledge", "web_search", "web_fetch"):
                reads_since_edit += 1
            # PUSH RAG: on a load/compile failure auto-inject the most relevant seeded ggml-source chunks
            if ("'failed': True" in rs or "error" in rs.lower()) and fn in ("bench_decode", "rebuild"):
                hit = memory.mem_execute("search_knowledge", {"query": rs[:300], "k": 2}).get("results")
                if isinstance(hit, list) and hit:
                    messages.append({"role": "user", "content":
                        "[auto-pushed reference from your knowledge base, relevant to that error]\n" +
                        "\n---\n".join(h.get("text", "")[:700] for h in hit)})
            sig = fn + ":" + json.dumps(args, sort_keys=True)[:120]
            sig_counts[sig] = sig_counts.get(sig, 0) + 1
            step_sigs.add(sig)
            recent_sigs.append(sig)
            del recent_sigs[:-8]   # keep last 8
        # loop-breaker (a): any identical call repeated >=3x  (b): last 6 actions cycle among <=2 sigs
        spiraled = [s for s in step_sigs if sig_counts[s] >= 3]
        if not spiraled and len(recent_sigs) >= 6 and len(set(recent_sigs[-6:])) <= 2:
            spiraled = list(set(recent_sigs[-6:]))
            print(f"[a{attempt} s{step}] LOOP-BREAKER: 2-cycle oscillation detected")
        if spiraled:
            fn0 = spiraled[0].split(":")[0]
            print(f"[a{attempt} s{step}] LOOP-BREAKER: forcing off '{fn0}'")
            messages.append({"role": "user", "content":
                f"STOP. You have called '{fn0}' with the same arguments 3+ times with no progress — you "
                "are looping. Do NOT make that call again. Do something DIFFERENT right now: re-read the "
                "then web_fetch the thing you're stuck on, OR edit_source and rebuild, OR move to the next "
                "model. Also remember() what you've learned so you don't repeat it."})
            for s in spiraled: sig_counts[s] = 0
        # investigation-without-edit budget (fires on DIFFERENT greps too, which the loop-breaker misses)
        if reads_since_edit >= 8:
            print(f"[a{attempt} s{step}] BUDGET: {reads_since_edit} reads w/o an edit — forcing edit")
            messages.append({"role": "user", "content":
                "You have investigated 8+ times without editing. STOP reading/grepping. Do EXACTLY this now: "
                "(1) name which of the 6 fix-checklist steps is next, (2) make that edit with edit_source or "
                "write_file, (3) rebuild. Do not grep or read again until after you have made an edit."})
            reads_since_edit = 0
    return None, True, observations


# the fix for making a quant type load+run is ALWAYS one of these 6 steps — the plan template + rubric
FIX_CHECKLIST = (
    "1) add the type to the ggml_type ENUM (ggml.h) + bump GGML_TYPE_COUNT\n"
    "2) add its TYPE_TRAITS row (blck_size / type_size / type name) in ggml.c\n"
    "3) define its BLOCK STRUCT (block_...) in ggml-common.h\n"
    "4) add the DEQUANTIZE function (dequantize_row_...) in ggml-quants.c/.h\n"
    "5) register the CPU DISPATCH (vec_dot / from_float) so it loads on CPU\n"
    "6) register the GPU KERNEL dispatch for this card's backend (only after CPU works)")

def diagnose(task, observations):
    """CLOSED-FORM rubric diagnosis bound to the 6-step checklist. Free-form reflection produced
    'plausible-but-wrong' causes ('the loader is buggy'); a rubric with that answer removed can't reach it."""
    facts = "\n".join(f"- {o}" for o in observations[-14:]) or "- (no notable errors/edits captured)"
    msgs = [{"role": "system", "content":
             "You diagnose a failed attempt against a FIXED 6-step checklist. The model files are KNOWN-GOOD "
             "(they run on other systems). 'The file/loader/GGUF is invalid or buggy' is NOT an allowed "
             "conclusion — it is ruled out by construction. The fix is always one of the 6 steps below."},
            {"role": "user", "content":
             "The ONLY way to make a quant type load+run on this build is these 6 steps:\n" + FIX_CHECKLIST +
             "\n\nACTUAL errors / edits / results from the last attempt:\n" + facts +
             "\n\nAnswer ONLY two things, grounded in the evidence:\n"
             "STEP: which of the 6 steps is still incomplete or wrong (the compiler error usually names it, "
             "e.g. 'incomplete type block_...' = step 3 missing).\n"
             "ACTION: the ONE concrete next edit (which file, which step) to do next attempt. "
             "Do NOT propose editing the loader or 'fixing the file'."}]
    m = chat(msgs, [])
    diag = (m.get("content") or m.get("reasoning_content") or "").strip() or "(no diagnosis produced)"
    memory.mem_execute("remember", {"note": "RUBRIC DIAGNOSIS: " + diag[:800],
                                    "tags": ["diagnosis", "retry", "checklist"]})
    print(f"   \U0001f504 rubric diagnosis: {diag[:220]}")
    return diag


def run(task):
    print(f"=== optimizer-agent | task={task.NAME} | brain={BRAIN} (GPU{BRAIN_CARD}) | "
          f"bench=GPU{TEST_CARD} | max_attempts={MAX_ATTEMPTS}x{MAX_STEPS} ===\n")
    tools = (hardware.HW_TOOLS + memory.MEM_TOOLS + research.RESEARCH_TOOLS
             + codetools.CODE_TOOLS + task.TOOLS)
    port_preamble = (
        "MAKING A MODEL LOAD ON THIS BUILD — the fix is ALWAYS these 6 steps, in order (the model files "
        "are known-good; never edit the loader or 'fix the file'):\n" + FIX_CHECKLIST + "\n"
        "WORK LIKE THIS: (a) LOCALIZE first — grep_source (summary) to find WHICH files hold each step, "
        "read only what you need; (b) then EDIT one step at a time with edit_source (tolerant match) or "
        "write_file (whole file); (c) rebuild after EACH edit — a new/different compiler error is PROGRESS "
        "and usually names the next step (e.g. 'incomplete type block_...' = do step 3). Don't investigate "
        "in circles: after a couple of reads, make an edit. The compiler is your guide, edit by edit.")
    sys_content = (hardware.HW_PREAMBLE + "\n\n" + memory.MEM_PREAMBLE + "\n\n"
                   + research.RESEARCH_PREAMBLE + "\n\n" + codetools.CODE_PREAMBLE + "\n\n"
                   + port_preamble + "\n\n" + task.SYSTEM)
    # OUTER OPTIMIZATION LOOP: retry until success (NO cap by default), carrying memory forward +
    # diagnosing each failure so every attempt is smarter than the last. It relearns until it wins.
    attempt = 0
    while True:
        attempt += 1
        cap = f"/{MAX_ATTEMPTS}" if MAX_ATTEMPTS else " (uncapped — until success)"
        print(f"\n########## ATTEMPT {attempt}{cap} (memory carries over) ##########")
        final, hit_max, observations = run_attempt(task, tools, sys_content, attempt)
        success = bool(final) and "BEST:" in final and not hit_max
        if success:
            print(f"\n=== SUCCESS on attempt {attempt} ===\n{final}")
            return final
        print(f"=== attempt {attempt} did not succeed ({'max steps' if hit_max else 'no BEST'}) — "
              f"OODA diagnosis + retrying ===")
        diagnose(task, observations)
        if MAX_ATTEMPTS and attempt >= MAX_ATTEMPTS:
            print("=== reached optional attempt cap without full success ===")
            return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="dflash_depth", help="task plugin in tasks/ (e.g. dflash_depth)")
    a = ap.parse_args()
    task = importlib.import_module(f"tasks.{a.task}")
    run(task)
