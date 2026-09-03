#!/usr/bin/env python3
"""
run_agent.py — ask the local model to write the fp8 decode kernel from a spec.

It is given the data layout, the arithmetic, the available intrinsic and the
required signature. It is NOT given the reference implementation, the golden
outputs, or any part of the harness. It writes agent_kernel.cuh; grade.sh
compiles it, runs it against inputs it never saw, and compares to a reference it
never saw.

The model's own claims about its kernel are ignored entirely. Only grade.sh's
verdict counts.
"""
import json, re, subprocess, sys, urllib.request
from pathlib import Path

URL   = "http://localhost:13305/v1/chat/completions"
BRAIN = "agentworld"
HERE  = Path(__file__).resolve().parent

SPEC = r"""
Write a HIP kernel for AMD gfx1201 (RDNA4) that computes an fp8 matrix-vector
product for LLM decode. Output ONLY the kernel code, no prose, no markdown fence.

DATA LAYOUT (already defined for you, do not redefine):

    #define QK 32
    struct block_f8e4m3 { __half  d;  uint8_t qs[QK]; };  // a weight block
    struct block_a_fp8  { __half2 ds; uint8_t qs[QK]; };  // an activation block

Each block holds QK=32 values in fp8 OCP E4M3 encoding (1 sign, 4 exponent,
3 mantissa, bias 7), plus a scale. For weights the scale is the __half `d`.
For activations the scale is the LOW half of `ds` — read it with
__low2float(act[c].ds).

THE MATRIX: N rows, each row is Kb = K/QK consecutive block_f8e4m3.
Row `row` begins at byte offset `row * stride` from the base pointer `vw`.
THE VECTOR: Kb consecutive block_a_fp8, shared by every row.

THE ARITHMETIC, for one output row:

    result = 0
    for each block index c in 0 .. Kb-1:
        s = 0
        for each of the 32 value positions i in that block:
            s += e4m3_to_float(weight.qs[i]) * e4m3_to_float(act.qs[i])
        result += s * __half2float(weight.d) * __low2float(act.ds)
    dst[row] = result

Note the scales multiply the per-block sum ONCE, after the 32 products are
summed — not each product individually.

AVAILABLE INTRINSIC (use it; this is the point of the exercise):

    float __builtin_amdgcn_dot4_f32_fp8_fp8(uint32_t a, uint32_t b, float acc)

It treats each uint32 as FOUR packed fp8 E4M3 values, computes the 4-element dot
product, adds `acc`, and returns the result in fp32. So 32 values = 8 calls.
You can obtain the packed uint32s by casting the qs array:
    const uint32_t* wq = (const uint32_t*)wrow[c].qs;

REQUIRED SIGNATURE — exactly this, do not change it:

    __global__ void agent_kernel(const char* __restrict__ vw,
                                 const block_a_fp8* __restrict__ act,
                                 float* __restrict__ dst,
                                 int64_t Kb, int64_t stride)

LAUNCH CONFIGURATION you must assume:
    agent_kernel<<<N, 64, 64*sizeof(float)>>>(...)
So there are N blocks (one per output row) and blockDim.x == 64 threads, with
64 floats of dynamic shared memory available via `extern __shared__ float sd[];`.

Distribute each row's Kb blocks across the 64 threads and combine their partial
sums so that exactly one thread writes dst[row]. Correctness is graded against a
reference implementation to a relative tolerance of 1e-2.
"""

def ask(messages):
    # This is a thinking model: it spends tokens reasoning before emitting visible
    # content. Too small a budget returns finish_reason=length with content="",
    # which an earlier version of this script happily wrote to disk as a 0-byte
    # "submission". Empty output is a failure, not a result -- say so.
    body = {"model": BRAIN, "messages": messages, "temperature": 0.2, "max_tokens": 24000}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        d = json.loads(r.read())["choices"][0]
    content = d["message"].get("content") or ""
    if not content.strip():
        raise RuntimeError(f"model returned EMPTY content (finish_reason="
                           f"{d.get('finish_reason')}) -- not a submission")
    return content

def extract(text):
    m = re.search(r"```(?:c\+\+|cpp|cuda|hip|c)?\s*(.*?)```", text, re.S)
    code = m.group(1) if m else text
    i = code.find("__global__")
    return code[i:].strip() if i >= 0 else code.strip()

def main():
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    msgs = [{"role": "system",
             "content": "You are a GPU kernel engineer writing HIP for AMD RDNA4. "
                        "Output only compilable code."},
            {"role": "user", "content": SPEC}]
    for n in range(1, attempts + 1):
        print(f"\n=== attempt {n}/{attempts} ===")
        try:
            reply = ask(msgs)
        except Exception as e:
            print(f"  model error: {e}"); return 1
        code = extract(reply)
        if "__global__" not in code:
            print("  model produced no kernel definition -- not a submission"); continue
        (HERE / "agent_kernel.cuh").write_text(code + "\n")
        print(f"  wrote agent_kernel.cuh ({len(code)} chars)")
        r = subprocess.run(["./grade.sh"], cwd=HERE, capture_output=True, text=True)
        out = (r.stdout or "") + (r.stderr or "")
        print("\n".join("  " + l for l in out.strip().splitlines()[-6:]))
        if "VERDICT: REPRODUCED" in out:
            (HERE / "agent_kernel_ACCEPTED.cuh").write_text(code + "\n")
            print("\n  >>> agent kernel REPRODUCED the reference")
            return 0
        # Feed the harness's verdict back -- the compiler and the grader are the
        # only feedback it gets. We never tell it what the reference does.
        msgs += [{"role": "assistant", "content": reply},
                 {"role": "user", "content":
                  "That did not pass. Here is the harness output verbatim. Fix the "
                  "kernel and output only the corrected code:\n\n" + out[-2500:]}]
    print("\n  >>> not reproduced within the attempt budget")
    return 1

if __name__ == "__main__":
    sys.exit(main())
