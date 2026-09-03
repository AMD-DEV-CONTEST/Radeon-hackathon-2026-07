#!/usr/bin/env python3
"""
chat_session.py — a real multi-turn conversation with Hyperloom.

Everything here happens live: the brain is Qwen-AgentWorld-35B-A3B served by
Lemonade on the Radeon card, the tools actually execute on this machine, and
each turn carries the previous turns' context so the agent can build on what it
already established.

Nothing is scripted on the model's side. The user turns are fixed so the demo is
reproducible; every assistant turn, tool call and tool result is produced live.

Tools the agent may call:
  scan_isa    probe the target with llvm-mc and report whether an instruction
              is really present (the assembler cannot lie)
  read_kernel show the dispatch site of a kernel so it can see for itself
              which route is used
  run_bench   build and run a correctness-gated benchmark on the GPU
"""
import os, json, subprocess, sys, textwrap, time, urllib.request
from pathlib import Path

URL   = "http://localhost:13305/v1/chat/completions"
BRAIN = "agentworld"
REPO  = Path(__file__).resolve().parent.parent
C_U, C_A, C_T, C_D, C_O = "\033[1;36m", "\033[1;37m", "\033[1;33m", "\033[2m", "\033[0m"

TOOLS = [
 {"type":"function","function":{"name":"scan_isa","description":
   "Probe a gfx target with the LLVM assembler and report whether an instruction is really present on that silicon.",
   "parameters":{"type":"object","properties":{
     "target":{"type":"string","description":"e.g. gfx1201"},
     "instruction":{"type":"string"}},"required":["target","instruction"]}}},
 {"type":"function","function":{"name":"read_kernel","description":
   "Show which compute route a decode kernel dispatches to.",
   "parameters":{"type":"object","properties":{
     "name":{"type":"string","description":"kernel name, e.g. decode_dot8 or decode_dp4a"}},"required":["name"]}}},
 {"type":"function","function":{"name":"sweep_batch","description":
   "Measure the continuous-batching throughput curve for a model on this GPU: runs llama-batched-bench "
   "across a grid of concurrent-stream counts and returns tokens/s for each. Use this to find the "
   "serving parallelism that maximises throughput -- it is per-model and cannot be guessed.",
   "parameters":{"type":"object","properties":{
     "streams":{"type":"string","description":"comma-separated stream counts, e.g. '1,32,96,192'"}},
     "required":["streams"]}}},
 {"type":"function","function":{"name":"run_bench","description":
   "Build and run a correctness-gated benchmark on the Radeon GPU and return its output.",
   "parameters":{"type":"object","properties":{
     "which":{"type":"string","description":"'routes' compares dp4a vs dot8; 'production' runs the shipping kernel"},
     "shape":{"type":"string","description":"optional 'N K', e.g. '14336 4096'"}},"required":["which"]}}},
]

def sh(cmd, timeout=600):
    try:
        return subprocess.run(cmd, shell=True, cwd=REPO, capture_output=True,
                              text=True, timeout=timeout).stdout.strip()
    except Exception as e:
        return f"(tool error: {e})"

def do_tool(name, args):
    if name == "scan_isa":
        # The model does NOT get to supply the target. That is exactly the fact it
        # should be discovering, and when asked it guessed a different GPU. Detect
        # the real one and say so if the model's assumption was wrong.
        real = sh("rocminfo 2>/dev/null | grep -oE 'gfx[0-9]+' | head -1") or "gfx1201"
        asked = (args.get("target") or "").strip()
        note = ""
        if asked and asked != real:
            note = (f"NOTE: you asked about {asked}, but the GPU actually present is {real}. "
                    f"Reporting {real}.\n")
        instr = (args.get("instruction") or "").strip()
        census = sh(f"bash toolkit/scan-isa-gfx.sh {real} 2>/dev/null | grep -iE 'PRESENT|ABSENT'")
        if instr:
            hit = sh(f"bash toolkit/scan-isa-gfx.sh {real} 2>/dev/null | grep -i '{instr}'")
            if not hit:
                return (note + f"'{instr}' does not appear in the {real} ISA census. "
                        f"What IS present:\n{census}")
            return note + hit
        return note + census

    if name == "read_kernel":
        k = args.get("name", "decode_dot8")
        return sh(f"grep -nE 'sudot8|dp4a|blockIdx' kernels/decode/{k}.hip 2>/dev/null | head -4") or "(kernel not found)"
    if name == "sweep_batch":
        grid = (args.get("streams") or "1,32,96,192").strip()
        # keep the grid inside llama.cpp's hard n_seq_max limit, or the whole run aborts
        safe = ",".join(x for x in (g.strip() for g in grid.split(",")) if x.isdigit() and 1 <= int(x) <= 256)
        if not safe:
            return "no valid stream counts; llama.cpp allows 1..256 (n_seq_max)"
        model = os.environ.get("SWEEP_MODEL", "")
        bin_  = os.environ.get("BATCHED_BENCH", "")
        if not model or not bin_:
            return ("sweep_batch needs SWEEP_MODEL (a GGUF) and BATCHED_BENCH "
                    "(path to llama-batched-bench). Unset here, so no sweep was run.")
        out = sh(f"HIP_VISIBLE_DEVICES=0 {bin_} -m {model} -c 131072 -b 2048 -ub 512 "
                 f"-npp 32 -ntg 128 -npl {safe} -ngl 99 2>/dev/null | grep -E '^\\|' | tail -20", timeout=3600)
        if not out:
            return "sweep produced no rows (model or benchmark binary missing)"
        lines = ["streams | decode t/s"]
        for row in out.splitlines():
            f = [c.strip() for c in row.split("|")]
            if len(f) > 9 and f[3].isdigit():
                lines.append(f"{f[3]:>7} | {f[8]}")
        return "\n".join(lines) if len(lines) > 1 else out

    if name == "run_bench":
        if args.get("which") == "production":
            shape = args.get("shape", "")
            return sh(f"cd kernels/decode && HIP_VISIBLE_DEVICES=0 ./decode_mmvq_iu4 {shape} 2>/dev/null | tail -3")
        return sh("cd kernels/decode && HIP_VISIBLE_DEVICES=0 ./decode_dp4a 2>/dev/null | tail -1 && "
                  "HIP_VISIBLE_DEVICES=0 ./decode_dot8 2>/dev/null | tail -1")
    return "(unknown tool)"

def ask(messages, max_tokens=14000):
    body = {"model": BRAIN, "messages": messages, "tools": TOOLS,
            "temperature": 0.2, "max_tokens": max_tokens}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=1800).read())["choices"][0]

def wrap(s, indent="    "):
    for para in (s or "").split("\n"):
        for line in textwrap.wrap(para, 92) or [""]:
            print(indent + line)

TURNS = [
 "What GPU am I on, and does it have a native 8-wide int4 dot instruction? Use the tool, don't answer from memory.",
 "Is the shipped decode kernel actually using that instruction?",
 "Build both routes and measure them.",
 "That looks like a big win. Is that measurement honest?",
]

SYSTEM = ("You are Hyperloom, an agent that optimises LLM inference kernels on AMD Radeon GPUs. "
          "You have tools and you use them: never state a hardware fact from memory when a tool can "
          "check it. Keep answers to 3 sentences. Refer back to what earlier turns established. "
          "If a bandwidth figure exceeds the card's 631 GB/s DRAM roofline, say so plainly — it means "
          "the working set fit in the 64 MiB cache and the number is not a real throughput result. "
          "When you sweep batching, report the curve and say where throughput stops improving. "
          "Throughput per stream falls as concurrency rises: never call an aggregate figure a per-request speed-up.")

def main():
    msgs = [{"role":"system","content":SYSTEM}]
    for i, user in enumerate(TURNS, 1):
        print(f"\n{C_U}[turn {i}] you{C_O}"); wrap(user, "    ")
        msgs.append({"role":"user","content":user})
        for _ in range(3):                     # allow tool round-trips within a turn
            ch = ask(msgs); m = ch["message"]
            tcs = m.get("tool_calls") or []
            msgs.append({k:v for k,v in m.items() if k in ("role","content","tool_calls")})
            if not tcs:
                break
            for tc in tcs:
                fn = tc["function"]["name"]
                try: a = json.loads(tc["function"]["arguments"] or "{}")
                except Exception: a = {}
                print(f"  {C_T}→ tool: {fn}({', '.join(f'{k}={v}' for k,v in a.items())}){C_O}")
                res = do_tool(fn, a)
                print(f"{C_D}"); wrap(res, "      "); print(f"{C_O}", end="")
                msgs.append({"role":"tool","tool_call_id":tc.get("id","0"),"content":res})
        print(f"  {C_A}hyperloom{C_O}")
        wrap((m.get("content") or "").strip() or "(no answer)", "    ")
        time.sleep(1)
    print(f"\n{C_D}  4 turns, one context. Every tool result above was produced on this machine,{C_O}")
    print(f"{C_D}  and the brain that decided to call them is resident on the Radeon GPU.{C_O}")

if __name__ == "__main__":
    main()
