#!/usr/bin/env python3
"""
queue_formats.py — run the golden-reproduction protocol across quant formats.

Same rules as the fp8 run in ../: the model receives a written specification of
the block layout and decode rule, never the reference implementation or the
golden output. The harness owns inputs, reference, comparison and verdict.

Formats are run serially because the model server is the bottleneck. Each result
is appended to results.md as it lands, so an interrupted run still leaves a
record of what was and was not established.

    python3 queue_formats.py [FMT ...]      # default: all defined below
"""
import json, re, subprocess, sys, time, urllib.request
from pathlib import Path

URL   = "http://localhost:13305/v1/chat/completions"
BRAIN = "agentworld"
HERE  = Path(__file__).resolve().parent
LOG   = HERE / "results.md"

COMMON = """
The kernel signature is fixed. Do not change it:

    __global__ void agent_kernel(const block_lowbit* __restrict__ w,
                                 const float* __restrict__ act,
                                 float* __restrict__ dst, int64_t Kb)

Launched as agent_kernel<<<N, 64, 64*sizeof(float)>>>(...), so blockDim.x == 64
and 64 floats of dynamic shared memory are available via
`extern __shared__ float sd[];`.

`w` points at N rows of Kb blocks each; row `row` starts at w + row*Kb.
`act` is a plain float array of Kb*QK values shared by every row.

For each output row:
    result = 0
    for each block c in 0..Kb-1:
        s = 0
        for each element k in 0..QK-1:
            s += decoded_weight(c, k) * act[c*QK + k]
        result += s * block_scale(w[c])   // fp16 d, or 2^(e-127) for MX
    dst[row] = result
The block scale multiplies the block sum ONCE, after the QK products are summed.

Distribute the blocks across the 64 threads and reduce in shared memory so
exactly one thread writes dst[row]. Output ONLY the kernel code, no prose, no
markdown fence.
"""

FORMATS = {
 "Q1": ("""Q1_0: QK=128 elements per block, struct is
    { __half d; uint8_t qs[16]; }   // 1 bit per element
Decode: element k lives in bit (k%8) of byte (k/8). A SET bit means +1.0f and a
CLEAR bit means -1.0f.""", "1-bit binary"),

 "Q2": ("""Q2_0: QK=128 elements per block, struct is
    { __half d; uint8_t qs[32]; }   // 2 bits per element
Decode: element k lives in bit-pair (k%4) of byte (k/4).
    code = (qs[k/4] >> (2*(k%4))) & 3
The logical value is (code - 1), so code 0 -> -1.0f, 1 -> 0.0f, 2 -> +1.0f.
Code 3 does not occur. This is a ternary format.""", "2-bit ternary"),

 "Q4": ("""Q4_0: QK=32 elements per block, struct is
    { __half d; uint8_t qs[16]; }   // one nibble per element
Decode: the LOW nibble of byte j holds element j, and the HIGH nibble of byte j
holds element j+16 (note: NOT j*2 and j*2+1). Each nibble is an unsigned 0..15
value and the logical value is (nibble - 8), giving the range -8..+7.""",
        "4-bit linear"),

 "Q5": ("""Q5_0: QK=32 elements per block, struct is
    { __half d; uint8_t qh[4]; uint8_t qs[16]; }   // 5 bits per element
Decode: the low 4 bits come from the nibbles exactly as Q4_0 -- LOW nibble of
byte j holds element j, HIGH nibble of byte j holds element j+16. The FIFTH bit
of element k lives in qh: bit (k%8) of qh[k/8]. Assemble
    value = ((nibble | (fifth_bit << 4)) - 16)
giving an unsigned 0..31 code mapped to the range -16..+15.""", "5-bit linear"),

 "MXFP4": ("""MXFP4 (OCP Microscaling FP4): QK=32 elements per block, struct is
    { uint8_t e; uint8_t qs[16]; }
The scale is NOT fp16. It is a shared UE8M0 exponent byte: the block scale is
    scale = 2^(e - 127)      // use ldexpf(1.0f, (int)e - 127)
Each element is a 4-bit OCP E2M1 value: 1 sign bit, 2 exponent bits (bias 1),
1 mantissa bit, packed as nibbles the same way as Q4_0 (low nibble of byte j is
element j, high nibble is element j+16). Decode a nibble n as:
    s = (n>>3)&1, e2 = (n>>1)&3, m = n&1
    if e2 == 0:  value = sign * (m ? 0.5f : 0.0f)          // subnormal
    else:        value = sign * ldexpf(1.0f + m/2.0f, e2-1)
There are no Inf or NaN encodings in OCP FP4.""", "4-bit MX, E2M1 + UE8M0"),

 "MXFP8": ("""MXFP8 (OCP Microscaling FP8): QK=32 elements per block, struct is
    { uint8_t e; uint8_t qs[32]; }
The scale is a shared UE8M0 exponent byte, NOT fp16:
    scale = 2^(e - 127)      // ldexpf(1.0f, (int)e - 127)
Each element is one byte of OCP E4M3: 1 sign bit, 4 exponent bits (bias 7),
3 mantissa bits. Decode byte v as:
    s = (v>>7)&1, e4 = (v>>3)&0xF, m = v&0x7
    if e4 == 0:  value = sign * ldexpf(m/8.0f, -6)         // subnormal
    else:        value = sign * ldexpf(1.0f + m/8.0f, e4-7)
(The e4==15,m==7 slot is NaN and does not occur in this data.)""",
           "8-bit MX, E4M3 + UE8M0"),

 "Q8": ("""Q8_0: QK=32 elements per block, struct is
    { __half d; int8_t qs[32]; }
Decode: element k is simply (float)qs[k], a signed 8-bit value in -128..127.
This is the simplest format here -- no bit unpacking at all.""", "8-bit linear"),
}

def ask(msgs):
    body = {"model": BRAIN, "messages": msgs, "temperature": 0.2, "max_tokens": 24000}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        d = json.loads(r.read())["choices"][0]
    c = d["message"].get("content") or ""
    if not c.strip():
        raise RuntimeError(f"empty content (finish={d.get('finish_reason')})")
    return c

def extract(t):
    m = re.search(r"```(?:c\+\+|cpp|cuda|hip|c)?\s*(.*?)```", t, re.S)
    c = (m.group(1) if m else t)
    i = c.find("__global__")
    return (c[i:] if i >= 0 else c).strip()

def run_one(fmt, spec, label, attempts=3):
    print(f"\n{'='*66}\n{fmt}_0 ({label})\n{'='*66}")
    msgs = [{"role":"system","content":"You are a GPU kernel engineer writing HIP "
                                       "for AMD RDNA4. Output only compilable code."},
            {"role":"user","content":spec + "\n" + COMMON}]
    for n in range(1, attempts+1):
        print(f"  attempt {n}/{attempts}")
        try: reply = ask(msgs)
        except Exception as e:
            print(f"    model error: {e}"); return (fmt, "MODEL-ERROR", str(e)[:80])
        code = extract(reply)
        if "__global__" not in code:
            print("    no kernel produced"); continue
        (HERE/"agent_kernel.cuh").write_text(code + "\n")
        r = subprocess.run(["./grade.sh", fmt], cwd=HERE, capture_output=True, text=True)
        out = (r.stdout or "") + (r.stderr or "")
        verdict = next((l for l in out.splitlines() if l.startswith("VERDICT")), "VERDICT: ?")
        err = re.search(r"max_rel_err=([0-9.e+-]+)", out)
        print(f"    {verdict.strip()}")
        if "REPRODUCED" in out:
            (HERE/f"agent_kernel_{fmt}_ACCEPTED.cuh").write_text(code + "\n")
            return (fmt, "REPRODUCED", err.group(1) if err else "")
        msgs += [{"role":"assistant","content":reply},
                 {"role":"user","content":"That did not pass. Harness output:\n\n"
                  + out[-2000:] + "\n\nFix it. Output only the corrected kernel."}]
    return (fmt, "NOT-REPRODUCED", err.group(1) if err else "")

def main():
    want = sys.argv[1:] or list(FORMATS)
    rows = []
    for fmt in want:
        if fmt not in FORMATS:
            print(f"unknown format {fmt}"); continue
        spec, label = FORMATS[fmt]
        t0 = time.time()
        res = run_one(fmt, spec, label)
        rows.append(res + (f"{time.time()-t0:.0f}s",))
        with LOG.open("a") as f:
            f.write(f"| {res[0]}_0 | {label} | **{res[1]}** | {res[2]} | {rows[-1][3]} |\n")
    print(f"\n{'='*66}")
    for fmt, verdict, err, dt in rows:
        print(f"  {fmt}_0  {verdict:<16} max_rel_err={err:<14} {dt}")

if __name__ == "__main__":
    main()
