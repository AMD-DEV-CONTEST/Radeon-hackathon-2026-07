#!/usr/bin/env python3
"""
run_agent_harness.py — can the model write the CHECKER, not just the kernel?

The obvious objection: a model that writes both the kernel and the thing that
grades it proves only self-consistency. So this does not trust the model's
harness — it TESTS it.

The model writes a complete correctness gate: a CPU reference for fp8 E4M3, a
comparison against GPU output, and a PASS/FAIL verdict. We then compile its
harness against five kernels whose correct verdicts we already know:

    good        the bit-exact kernel            -> must PASS
    constant    writes 1.0f everywhere          -> must FAIL
    noscale     forgets the per-block scales    -> must FAIL
    halfrow     processes only half the blocks  -> must FAIL
    swapped     swaps the two scale factors     -> must FAIL

A harness that passes everything is a rubber stamp. A harness that fails
everything is broken. Only one that discriminates correctly is real, and that
verdict belongs to this script, not to the model.
"""
import json, re, subprocess, sys, urllib.request
from pathlib import Path

URL   = "http://localhost:13305/v1/chat/completions"
BRAIN = "agentworld"
HERE  = Path(__file__).resolve().parent

SPEC = r"""
Write a complete C++/HIP test harness that checks an fp8 GPU kernel for
correctness. Output ONLY code, no prose, no markdown fence.

You are writing the file harness_main.cpp. These are ALREADY DEFINED in a header
that is included before your code — do not redefine them:

    #define QK 32
    struct block_f8e4m3 { __half  d;  uint8_t qs[QK]; };
    struct block_a_fp8  { __half2 ds; uint8_t qs[QK]; };
    __global__ void kernel_under_test(const char* vw, const block_a_fp8* act,
                                      float* dst, int64_t Kb, int64_t stride);

YOUR JOB. Write `int main()` plus any helpers, doing exactly this:

1. Build test data for N=1024 rows, K=4096, so Kb = K/QK = 128 blocks per row.
   Use std::mt19937 with seed 12345. Fill every qs byte with a random value in
   0..255 but REJECT any byte b where (b & 0x7F) == 0x7F, because those two
   encodings are NaN in E4M3 and would poison the comparison. Set every weight
   scale d to 0.01f and every activation scale ds to 0.02f.

2. Write a CPU reference. fp8 here is OCP E4M3: 1 sign bit, 4 exponent bits,
   3 mantissa bits, exponent bias 7, no infinities, and 0x7F/0xFF are NaN.
     - if exponent == 0 the value is subnormal: sign * (mantissa/8) * 2^-6
     - otherwise: sign * (1 + mantissa/8) * 2^(exponent-7)
   For each row, for each of the Kb blocks, sum the 32 products of decoded
   weight and decoded activation, multiply that block sum by the weight scale
   (__half2float of d) and the activation scale (__low2float of ds), and add it
   to the row total. The scales apply ONCE per block, after the 32 products are
   summed.

3. Launch the kernel as kernel_under_test<<<N, 64, 64*sizeof(float)>>>(...)
   with stride = Kb * sizeof(block_f8e4m3), copy the result back, and compare
   every row against your CPU reference using RELATIVE error
   (fabs(got-want)/fabs(want) when fabs(want) > 1e-6, else absolute).

4. Treat any non-finite GPU output as an immediate failure.

5. Print exactly one line in this format and nothing else that matches it:
       max_rel_err=<value> VERDICT=<PASS or FAIL>
   PASS if the worst relative error is <= 1e-2, otherwise FAIL.
   Return 0 on PASS and 1 on FAIL.

Include whatever headers you need (<hip/hip_runtime.h> and <hip/hip_fp16.h> are
already included for you). Be careful: this harness will be run against kernels
that are deliberately wrong, and it must catch them.
"""

# (name, kernel body, expected verdict from a CORRECT harness)
KERNELS = [
 ("good", r'''
__global__ void kernel_under_test(const char* __restrict__ vw, const block_a_fp8* __restrict__ act,
                                  float* __restrict__ dst, int64_t Kb, int64_t stride) {
    extern __shared__ float sd[]; int tid = threadIdx.x; int row = blockIdx.x; float acc = 0.0f;
    const block_f8e4m3* wr = (const block_f8e4m3*)(vw + row * stride);
    for (int64_t c = tid; c < Kb; c += 64) {
        const uint32_t* wq = (const uint32_t*)wr[c].qs; const uint32_t* aq = (const uint32_t*)act[c].qs;
        float s = 0.0f;
        for (int i = 0; i < 8; ++i) s = __builtin_amdgcn_dot4_f32_fp8_fp8(wq[i], aq[i], s);
        acc += s * __half2float(wr[c].d) * __low2float(act[c].ds);
    }
    sd[tid] = acc; __syncthreads();
    for (int st = 32; st > 0; st >>= 1) { if (tid < st) sd[tid] += sd[tid+st]; __syncthreads(); }
    if (tid == 0) dst[row] = sd[0];
}''', "PASS"),

 ("constant", r'''
__global__ void kernel_under_test(const char* __restrict__ vw, const block_a_fp8* __restrict__ act,
                                  float* __restrict__ dst, int64_t Kb, int64_t stride) {
    if (threadIdx.x == 0) dst[blockIdx.x] = 1.0f;
}''', "FAIL"),

 ("noscale", r'''
__global__ void kernel_under_test(const char* __restrict__ vw, const block_a_fp8* __restrict__ act,
                                  float* __restrict__ dst, int64_t Kb, int64_t stride) {
    extern __shared__ float sd[]; int tid = threadIdx.x; int row = blockIdx.x; float acc = 0.0f;
    const block_f8e4m3* wr = (const block_f8e4m3*)(vw + row * stride);
    for (int64_t c = tid; c < Kb; c += 64) {
        const uint32_t* wq = (const uint32_t*)wr[c].qs; const uint32_t* aq = (const uint32_t*)act[c].qs;
        float s = 0.0f;
        for (int i = 0; i < 8; ++i) s = __builtin_amdgcn_dot4_f32_fp8_fp8(wq[i], aq[i], s);
        acc += s;                                  /* BUG: scales dropped */
    }
    sd[tid] = acc; __syncthreads();
    for (int st = 32; st > 0; st >>= 1) { if (tid < st) sd[tid] += sd[tid+st]; __syncthreads(); }
    if (tid == 0) dst[row] = sd[0];
}''', "FAIL"),

 ("halfrow", r'''
__global__ void kernel_under_test(const char* __restrict__ vw, const block_a_fp8* __restrict__ act,
                                  float* __restrict__ dst, int64_t Kb, int64_t stride) {
    extern __shared__ float sd[]; int tid = threadIdx.x; int row = blockIdx.x; float acc = 0.0f;
    const block_f8e4m3* wr = (const block_f8e4m3*)(vw + row * stride);
    for (int64_t c = tid; c < Kb/2; c += 64) {     /* BUG: half the blocks */
        const uint32_t* wq = (const uint32_t*)wr[c].qs; const uint32_t* aq = (const uint32_t*)act[c].qs;
        float s = 0.0f;
        for (int i = 0; i < 8; ++i) s = __builtin_amdgcn_dot4_f32_fp8_fp8(wq[i], aq[i], s);
        acc += s * __half2float(wr[c].d) * __low2float(act[c].ds);
    }
    sd[tid] = acc; __syncthreads();
    for (int st = 32; st > 0; st >>= 1) { if (tid < st) sd[tid] += sd[tid+st]; __syncthreads(); }
    if (tid == 0) dst[row] = sd[0];
}''', "FAIL"),

 ("swapped", r'''
__global__ void kernel_under_test(const char* __restrict__ vw, const block_a_fp8* __restrict__ act,
                                  float* __restrict__ dst, int64_t Kb, int64_t stride) {
    extern __shared__ float sd[]; int tid = threadIdx.x; int row = blockIdx.x; float acc = 0.0f;
    const block_f8e4m3* wr = (const block_f8e4m3*)(vw + row * stride);
    for (int64_t c = tid; c < Kb; c += 64) {
        const uint32_t* wq = (const uint32_t*)wr[c].qs; const uint32_t* aq = (const uint32_t*)act[c].qs;
        float s = 0.0f;
        for (int i = 0; i < 8; ++i) s = __builtin_amdgcn_dot4_f32_fp8_fp8(aq[i], wq[i], s);
        acc += s * __half2float(wr[c].d) * __high2float(act[c].ds);  /* BUG: high half */
    }
    sd[tid] = acc; __syncthreads();
    for (int st = 32; st > 0; st >>= 1) { if (tid < st) sd[tid] += sd[tid+st]; __syncthreads(); }
    if (tid == 0) dst[row] = sd[0];
}''', "FAIL"),
]

PREAMBLE = """#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>
#define QK 32
struct block_f8e4m3 { __half  d;  uint8_t qs[QK]; };
struct block_a_fp8  { __half2 ds; uint8_t qs[QK]; };
"""

def ask(messages):
    body = {"model": BRAIN, "messages": messages, "temperature": 0.2, "max_tokens": 24000}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        d = json.loads(r.read())["choices"][0]
    c = d["message"].get("content") or ""
    if not c.strip():
        raise RuntimeError(f"empty content (finish={d.get('finish_reason')})")
    return c

def extract(text):
    m = re.search(r"```(?:c\+\+|cpp|cuda|hip|c)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()

def test_harness(hsrc):
    """Compile the model's harness against each kernel; return its verdicts."""
    results = {}
    for name, body, expect in KERNELS:
        src = HERE / f"_probe_{name}.cpp"
        src.write_text(PREAMBLE + body + "\n" + hsrc + "\n")
        exe = HERE / f"_probe_{name}"
        c = subprocess.run([str(Path.home()/".local/bin/hipcc"), "--offload-arch=gfx1201",
                            "-O2", str(src), "-o", str(exe)],
                           capture_output=True, text=True)
        if c.returncode != 0:
            results[name] = ("BUILD-FAIL", expect, (c.stderr or "")[:150]); continue
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=600,
                           env={"HIP_VISIBLE_DEVICES": "0", "PATH": "/usr/bin:/bin"})
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"VERDICT=(PASS|FAIL)", out)
        results[name] = (m.group(1) if m else "NO-VERDICT", expect, out.strip()[:110])
    return results

def main():
    msgs = [{"role":"system","content":"You are a GPU test engineer. Output only compilable C++/HIP."},
            {"role":"user","content":SPEC}]
    for attempt in range(1, 4):
        print(f"\n=== harness attempt {attempt}/3 ===")
        try: reply = ask(msgs)
        except Exception as e: print(f"  model error: {e}"); return 1
        hsrc = extract(reply)
        if "int main" not in hsrc:
            print("  no main() produced -- not a submission"); continue
        (HERE/"agent_harness.cpp").write_text(hsrc + "\n")
        print(f"  wrote agent_harness.cpp ({len(hsrc)} chars)")
        res = test_harness(hsrc)
        good = 0
        for name, (got, expect, detail) in res.items():
            ok = (got == expect); good += ok
            print(f"    {name:<10} harness said {got:<11} expected {expect:<5} {'OK' if ok else 'WRONG'}")
            if not ok: print(f"      {detail}")
        if good == len(KERNELS):
            (HERE/"agent_harness_ACCEPTED.cpp").write_text(hsrc + "\n")
            print(f"\n  >>> the model's harness discriminates correctly on all {good} kernels")
            return 0
        print(f"\n  {good}/{len(KERNELS)} correct -- feeding results back")
        msgs += [{"role":"assistant","content":reply},
                 {"role":"user","content":
                  "Your harness was tested against kernels with known-correct verdicts and "
                  "got some wrong. It must PASS a correct kernel and FAIL broken ones. "
                  "Results:\n" + "\n".join(f"{n}: yours={g} expected={e} | {d}"
                                           for n,(g,e,d) in res.items()) +
                  "\n\nFix the harness. Output only the corrected code."}]
    print("\n  >>> harness did not discriminate correctly within the budget")
    return 1

if __name__ == "__main__":
    sys.exit(main())
