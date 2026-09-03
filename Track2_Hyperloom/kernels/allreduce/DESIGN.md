# T188 -- INT6 inline-compressed all-reduce for TP=2 on 2x R9700 (gfx1201)

Status: CPU-only design + numpy-validated codec + compiled (not run) HIP
kernels. No GPU execution this session (GPU0=live contest agent, GPU1=
serving+display). All numbers below are tagged MEASURED (numpy, CPU) or
PENDING (needs a GPU window).

Paths: `~/int6-allreduce/numpy/` (codec + tests), `~/int6-allreduce/hip/`
(device kernels + host orchestration, compiled for gfx1201), `~/int6-allreduce/bench/`
(prepared-not-run GPU scripts + checklist).

## 1. Why compress the all-reduce at all

TP=2 partial-sum all-reduce moves one full activation buffer per layer
between GPU0 and GPU1. Standard result on this box (measured previously,
our internal training guardrails): our RCCL build deadlocks on gfx1201
AllReduce without `NCCL_PROTO=Simple` (missing tuning-index mapping for
gfx1201, community bug vLLM#40980) -- so a custom all-reduce is doubly
motivated: (a) bypass a broken/fragile dependency, (b) exploit the fact
that on THIS box the GPU-GPU path is unusually slow (cross-socket QPI
staging, not xGMI), where compression pays off disproportionately more than
on an xGMI-connected pair.

## 2. Topology (measured, sysfs-safe reads, no GPU touched)

GPU0 @ `0000:04:00.0`, PCI root `pci0000:00`, NUMA0.
GPU1 @ `0000:8a:00.0`, PCI root `pci0000:80`, NUMA1.
Dual-Xeon E5-2699 v4, one GPU per socket, no shared PCIe switch between
them. Consequence: `hipDeviceCanAccessPeer(0,1)` is EXPECTED to be 0 (no
direct P2P) -- this is a PREDICTION from the sysfs topology, not yet
measured on-device (Stage 1 of the GPU-window checklist). If P2P actually
IS available (some ROCm versions support software-emulated P2P over PCIe
without a switch), the design still works -- it just skips the host-staging
hop and does a direct `hipMemcpyPeer` of the compressed payload instead.

Design consequence: every inter-GPU transfer in this design assumes
**host-staged** (D2H -> host memcpy across NUMA nodes -> H2D), NUMA-pinned
per socket (`numa_alloc_onnode` + `hipHostRegister`) so the D2H/H2D legs are
each NUMA-local (fast), and only the host-to-host `memcpy` crosses QPI. The
compression payoff is specifically that the QPI-crossing hop now carries the
COMPRESSED bytes (INT6: 0.8125 B/elem measured, vs fp16's 2 B/elem -- 2.46x
smaller, MEASURED via `numpy/int6_codec.py bytes_per_element(6)`).

## 3. Codec: INT6 symmetric, block-32, FP16 scale

`block_q6 { half d; uint8_t qs[24]; }` -- `sizeof(half)=2 + 24 = 26 bytes /
32 values = 0.8125 B/elem` (payload alone is 6/8=0.75 B/elem = 2.67x vs
fp16's 2 B/elem, matching the task brief's "~2.7x"; WITH the fp16 scale
overhead amortized per 32-value block the REAL achieved ratio is 2.46x --
report the amortized number, not the raw-bits number, it's the honest one).

Packing: 4 six-bit two's-complement codes per 3 bytes, IDENTICAL bit layout
to ggml's `block_mxfp6` (`mainline-llama.cpp-mxfp8` fork,
`ggml-common.h`/`common.cuh` `mxfp6_unpack4`) -- reused deliberately so the
bit-twiddling (bfe/bfi extract/insert) is a known-good pattern already
proven on this silicon, just with an integer payload instead of E3M2 float
codes. Quantization: `scale = absmax/31`, code range `[-32, 31]`
(one-sided asymmetry from two's complement, standard convention, matches
q8_0/q4_0-style symmetric quant elsewhere in ggml).

## 4. The "exact reduce" property -- MEASURED, with an important caveat

**Claim as stated in the task brief:** "int+int is lossless, so the reduce
adds zero error -- only the quant-on-send/dequant-on-recv at the ends cost
anything."

**MEASURED, literally true GIVEN A SHARED SCALE** (`numpy/test_accuracy.py`
`test_exact_reduce_shared_scale`): pack two tensors `a`, `b` to a COMMON
per-block scale (joint absmax across both operands' block), int16-accumulate
`qa+qb`, dequantize with the shared scale. Result:
```
max|reduced - (dequant(qa)+dequant(qb))| = 4.768e-07   (bits=4, 6, and 8 -- all IDENTICAL)
```
That residual is exactly float32's rounding floor (2^-21-ish), i.e. **zero
incremental error from the add itself** -- the ADD is provably lossless
given a shared scale, for any of INT4/6/8. This is the correct, narrow
reading of the "int+int is lossless" claim: it's a property of the CODEC's
add primitive, not automatically a property of the full 2-GPU protocol (see
below).

**The catch, and it matters:** in a REAL 2-shot all-reduce, GPU0 and GPU1
compute their per-block scales INDEPENDENTLY (each is blind to the other's
data before it quantizes and sends). Two independently-computed FP16 scales
are essentially NEVER equal, so a literal `int_a + int_b` across mismatched
scales is NOT valid without first rescaling one operand -- and rescaling by
an arbitrary (non-power-of-2) FP16 ratio itself costs a rounding step,
which defeats the "zero incremental error" property. **The realistic
protocol therefore does NOT do int+int across ranks; it does
`dequant(peer_int) + local_fp32`** (a plain float add) -- this is what
`allreduce_twoshot_q6.hip`'s `kernel_reduce_add_q6` actually implements, and
it's clearly commented there as a deliberate divergence from the literal
int-domain-add framing.

MEASURED for this realistic (independent-scale) case
(`test_exact_reduce_independent_scale`, bits=6, n=8192, gaussian a,b):
```
rel_l2(rank0_result, true_sum) = 0.015334
rel_l2(rank1_result, true_sum) = 0.015276
rel_l2(rank0_result, rank1_result)  [cross-rank asymmetry]  = 0.021643
```
This is a genuinely useful, NOT previously stated-in-the-brief finding: the
two ranks' final buffers are **not bit-identical** after a compressed
all-reduce -- rank0's copy of a segment it OWNS has fewer quant/dequant hops
than rank1's copy of that same segment (which arrived via the Phase-2
gather hop). This is normal/accepted behavior for compressed collectives
(same tradeoff class as NCCL's low-precision AllReduce variants) but it is
a real, measured, ~2.2% relative divergence between ranks that a naive
"the reduce is exact" claim would miss. Documented in
`allreduce_twoshot_q6.hip`'s Phase-2 comment block.

**Open engineering option (not built, flagged for a later stage if the
independent-scale error proves too large in practice):** force the per-block
scale to be power-of-2 (E8M0-style, like the MXFP6/MXFP8 codecs already in
the ggml fork) instead of continuous FP16. Then two independently-computed
scales differ by an integer left-shift, and a TRUE int+int reduce across
independently-quantized operands becomes possible (shift the smaller-scale
operand's codes up by `exp_a - exp_b`, exact, then add in an int32
accumulator with headroom). This would recover the literal "int+int is
lossless across independent operands" property at the cost of MXFP6's
coarser-scale-granularity error (measured to be WORSE than continuous-scale
INT6 for weights, see Section 6 -- the same tradeoff would likely apply
here). Not pursued this session; flagged as the natural next experiment if
Section correctness gates in the GPU-window checklist show the independent-
scale error is a problem in practice.

## 5. Two-shot protocol structure

Ring reduce-scatter (1 hop for N=2) + all-gather (1 hop for N=2), specialized
for TP=2 -- see `allreduce_twoshot_q6.hip` `q6_allreduce_twoshot()`:

**Phase 1 (Reduce-Scatter):** split the buffer into seg0 (owned by rank0)
and seg1 (owned by rank1). Each rank quantizes the segment it does NOT own
and sends it to the owner. The owner's `kernel_reduce_add_q6` dequantizes
the received chunk and adds it, IN PLACE, to its own resident full-precision
segment (LDS-free, pure warp-shuffle cross-lane exchange for the pack/unpack
-- confirmed in the compiled ISA, see Section 7). After Phase 1: rank0 owns
the fully-reduced seg0 (fp32, exact except for rank1's one quant/dequant
hop); rank1 owns the fully-reduced seg1 symmetrically.

**Phase 2 (All-Gather):** each rank quantizes its NOW-REDUCED segment
(fresh scale, computed on the post-sum data -- tighter dynamic range than
either pre-sum operand alone in most cases) and sends it to the peer, who
dequantizes into the final output buffer. Each rank's final buffer is
`[own-exact-segment, peer-quantized-segment]` -- the documented asymmetry
from Section 4.

## 6. Overflow / accumulator sizing

INT6 code range `[-32, 31]`; `int6 + int6` spans `[-64, 62]`, 7 bits --
trivially fits an `int16` accumulator (used in the numpy exact-reduce test)
with 9 bits of headroom to spare. On the actual device kernels
(`kernel_reduce_add_q6`), the add happens in FLOAT (dequant-then-add, see
Section 4), so int overflow isn't even a live concern there -- it only
matters for the literal shared-scale int-domain primitive, where int16 is
comfortably sufficient for TP=2 (would need `int32` if generalizing this
codec to >2-way reduction trees summing many int6 operands before a
rescale).

## 7. HIP kernels -- compiled, ISA-sanity-checked, NOT run

Files: `hip/codec_q6.hip` (CodecQ6::send/recv + 3 warp-cooperative kernels:
`kernel_quantize_q6`, `kernel_dequantize_q6`, `kernel_reduce_add_q6`),
`hip/allreduce_twoshot_q6.hip` (host orchestration: NUMA-aware staging
buffers, `q6_allreduce_twoshot()`, gated behind `Q6_ALLOW_MAIN` so a naive
build never touches hardware by accident).

Compiled for `--offload-arch=gfx1201` via the TheRock qat714 ROCm 7.14 SDK
clang (`hip/compile-gfx1201.sh` -- had to bypass the system `hipcc` wrapper,
which resolves to a STALE `/usr/include/hip` 5.7 header set ahead of the
SDK's own headers; fixed by calling `clang++ -isystem $SDK/include`
directly, matching the flag order in an existing real build's
`compile_commands.json`). Full link (object+host+device, not executed)
also verified clean.

**ISA sanity (device-only `-S`, `hip/build/codec_q6.gfx1201.s`):**
- `ds_bpermute_b32` -- the warp-shuffle absmax reduction and cross-lane code
  gather for packing compiled to real hardware cross-lane permute
  instructions, not a shared-memory round trip.
- `v_bfe_u32` / `v_bfe_i32` / `v_bfi_b32` -- the 6-bit bitfield extract/
  insert (pack/unpack) compiled to single hardware bitfield instructions,
  not multi-instruction shift+mask sequences.
- `v_dual_max_num_f32` / `v_dual_lshlrev_b32` / `v_dual_mul_f32` /
  `v_dual_cndmask_b32`/`v_dual_and_b32` -- the compiler auto-packed several
  independent VALU ops into VOPD dual-issue bundles for free (unprompted --
  no hand-written inline asm needed here, unlike the DOT2ACC dual-issue
  dead-end from the earlier RDNA4 decode research).
- `kernel_reduce_add_q6` confirmed LDS-free (0 `ds_write`/`ds_read`/
  `s_barrier` instructions in its body) -- the Phase-1B fused reduce never
  round-trips through shared memory.
- No `v_dot*`/`v_wmma*`/`v_swmmac*` present, and that's CORRECT for this
  kernel family -- this is a vector-add reduce, not a matmul; those
  instructions would be a red flag here, not a missing win.

## 8. ~1MB-ish activation threshold

Not yet measured (needs Stage 2 of the GPU-window checklist: `bench_bw.hip`
BW-vs-size sweep). The design anticipates a latency-bound regime for small
messages (per-launch kernel overhead + the 2 memcpy hops dominate) and a
BW-bound regime for large messages (where the 2.46x compression ratio
should show up nearly linearly in wall time) -- the crossover point is a
PENDING measurement, not assumed. A real TP=2 dense-8B layer activation is
roughly 16KB/token (4096 floats x 4B, fp32, batch=1 decode) up to several MB
for batched prefill -- `bench_allreduce_q6.hip`'s size sweep (16KB..64MB)
deliberately brackets both regimes so the threshold falls out of the data
rather than being guessed.

## 9. Scope addition: INT6 vs MXFP6 as a DECODE WEIGHT-QUANT format (MEASURED)

Distinct question from Sections 1-8: weights are MULTIPLIED, never reduced
across ranks, so the exact-reduce advantage (Section 4) does NOT apply here
-- this is pure dynamic-range/precision competition between a linear-int
codec (INT6, continuous FP16 scale) and a float codec (MXFP6 E3M2,
power-of-2 E8M0 scale).

**A-priori expectation stated in the task:** float-6 (MXFP6) should beat
int-6 on heavy-tailed weight distributions, and MXFP6 rides the existing
fp8 compute path for free. **MEASURED result contradicts the a-priori
expectation** on real weight tensors.

Method: `numpy/mxfp6_codec.py` (vectorized, bit-exact port of
`ggml_fp32_to_e3m2`/`ggml_e3m2_to_fp32`/`ggml_e8m0_to_fp32` from
`mainline-llama.cpp-mxfp8`'s `ggml-quants.c`/`ggml-impl.h` -- validated via
an exhaustive 64-code idempotency self-test (0 mismatches) and boundary
values (0, +-1, +-28 max-finite all exact) BEFORE trusting it on real data;
caught and fixed one bug in that validation pass -- the C reference's
`(int)(ax*16+0.5f)` is a TRUNCATING cast, not round-half-to-even, and
`np.round` silently gave the wrong answer for the `.5` boundary case until
switched to `np.floor`). Real weight tensors: 10 BF16 matrices from
`/aipool/models/ornith-1.0-35b-hf-bf16` (safetensors, read via a hand-rolled
mmap+`ml_dtypes` reader since the `safetensors` package's numpy backend
raises on BF16) -- 4x standard attention (`layers.3.self_attn.{q,k,v,o}_proj`)
+ 6x MoE expert (`layers.0.mlp.experts.{0,5}.{gate,up,down}_proj`).

```
              INT4 relL1   INT6 relL1   MXFP6 relL1
mean (10 t)      0.10483      0.02369      0.04498
max  (10 t)      0.12261      0.02771      0.04507

bytes/elem: INT4=0.5625  INT6=0.8125  MXFP6=0.7812  (nearly matched storage cost)

VERDICT: INT6 BEATS MXFP6 by 47.3% rel-L1 on these real ornith-35B weight tensors,
at essentially the SAME bits/element (0.8125 vs 0.7812 B/elem).
```

INT8 included as a sanity anchor (not the headline comparison): rel-L1
~0.006, i.e. ~4x lower than INT6 -- consistent, monotonic with the extra 2
bits, confirming this isn't a codec bug in either direction.

**Why this happened (a plausible mechanism, not asserted as proven):**
MXFP6's 2 mantissa bits give a coarse, CONSTANT relative-error floor
(observed: MXFP6's rel-L1 is nearly IDENTICAL across all 10 wildly
different tensors, 0.04489-0.04507 -- the textbook signature of a
floating-point codec's error being value-distribution-INDEPENDENT). INT6's
uniform 6-bit code space with a per-block-CALIBRATED continuous scale
instead devotes essentially all its bits to magnitude resolution rather
than splitting them into exponent+mantissa, and real transformer weight
blocks (post-normalization, block=32) don't span enough dynamic range
WITHIN one block to need MXFP6's wider exponent range -- so MXFP6 is paying
for headroom these blocks don't use, while giving up mantissa precision
they DO benefit from. This is consistent with (though not a re-derivation
of) known weight-PTQ literature findings that well-calibrated uniform INT
quantization is competitive with or better than microscaled float formats
when the mantissa budget is small (2 bits here) and per-block dynamic range
is modest.

**MEASURED verdict:** for these decode weight tensors, **INT6 wins over
MXFP6 by 47.3% rel-L1 at matched storage cost** -- MXFP6 does NOT
automatically stay the decode-weight king; that assumption should be
re-examined, not assumed. HOWEVER this verdict is accuracy-only. MXFP6's
real advantage (not measured/contradicted here) is that it upconverts
losslessly to e4m3 in-register and reuses the EXISTING fp8 dp4a/dot2
compute path VERBATIM (per the `mainline-llama.cpp-mxfp8` fork's own
design notes) -- INT6 would need a NEW decode compute kernel (int6 dequant
+ FMA, or a new packed-int dot path) with its own VALU-density
characteristics to be validated separately (see the family's "arithmetic
density first" decode lever ladder -- an accuracy win on paper is not
automatically a decode-speed win; that's a SEPARATE, not-yet-measured
question, PENDING a real kernel + `test-backend-ops -o MUL_MAT perf`
isolated A/B before any speed claim). This finding is scoped strictly to
ACCURACY at matched bits/element; it is not a recommendation to replace
MXFP6 as the decode format without that follow-up compute-path work.

## 10. Honest open-questions list

1. **P2P vs host-staged, unconfirmed.** `hipDeviceCanAccessPeer(0,1)` is
   predicted 0 from sysfs topology but not yet measured (Stage 1 checklist).
2. **The ~1MB activation threshold is a PLACEHOLDER, not measured**
   (Section 8) -- the bench sweep exists but hasn't run.
3. **Independent-scale cross-rank asymmetry (~2.2% rel-L2, Section 4) --
   is this acceptable for a real inference pipeline, or does it need the
   power-of-2-scale fix?** Needs an end-to-end PPL/accuracy check on a real
   model with the all-reduce actually wired into the decode/prefill path,
   not just an isolated buffer-diff test. Not attempted this session (would
   require GPU + model integration, well beyond "prepare, don't run").
4. **Uncompressed-baseline timing in `bench_allreduce_q6.hip` is a TODO
   stub** (kernels exist, not yet wired into a timed comparison loop) --
   flagged explicitly in the file and the checklist rather than silently
   left half-done.
5. **RCCL comparison is entirely PENDING** -- script is written and
   syntax-checked but never executed; no claim about beating or losing to
   RCCL should be made until Stage 4 of the checklist runs.
6. **The MXFP6-vs-INT6 weight-quant finding is accuracy-only** (Section 9)
   -- a compute-path/kernel-speed follow-up is a separate, larger piece of
   work, explicitly flagged as out of scope for this finding.
7. **NUMA-aware staging buffer sizing/reuse strategy** (per-call alloc vs a
   persistent pinned pool) is a performance-only concern not yet tuned --
   `RankState` currently allocates staging buffers once at `q6_rank_init`
   and reuses them across the two Phase-1/Phase-2 hops within one
   `q6_allreduce_twoshot()` call, but there's no persistent cross-call pool
   yet; for a real decode loop (thousands of all-reduce calls/sec) that
   would need to be a one-time setup cost, not per-call -- current code
   already does that correctly at the RankState granularity, just not yet
   validated under a real repeated-call workload.
