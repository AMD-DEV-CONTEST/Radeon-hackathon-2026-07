# Examples — worked, MEASURED on gfx1201

Every example below was run on a Radeon AI PRO R9700 (gfx1201), correctness-gated.

## 1. Step-0 scan → find an unexploited instruction
```
scripts/scan-isa-gfx.sh gfx1201 > isa-map.md         # PRESENT/ABSENT census (llvm-mc)
scripts/unused-isa-sweep.sh /path/to/llama.cpp/build gfx1201   # cross-ref vs kernels
```
Result: of ~19 present ML instructions, 2 were emitted 0× anywhere — `v_swmmac_i32_16x16x64_iu4` and `v_dot2_f32_bf16`. That list is the plan's starting point.

## 2. Compare two kernel implementations (correctness + speed)
`compare.yaml`:
```yaml
performance: { backend: metrix, metrix: { profile: quick } }
kernels:
  - { id: dp4a_baseline, type: hip, source_files: [./decode_dp4a.hip],
      compile_command: [["hipcc","--offload-arch=gfx1201","-O3","decode_dp4a.hip","-o","decode_dp4a"]],
      testcase_command: ./decode_dp4a, env: { HIP_VISIBLE_DEVICES: "0" } }
  - { id: dot8_iu4, type: hip, source_files: [./decode_dot8.hip],
      compile_command: [["hipcc","--offload-arch=gfx1201","-O3","decode_dot8.hip","-o","decode_dot8"]],
      testcase_command: ./decode_dot8, env: { HIP_VISIBLE_DEVICES: "0" } }
```
```
scripts/magpie.sh compare -k compare.yaml --baseline 0   # compile + correctness 2/2
# rank by metrix duration (auto-winner is CDNA-scored, ignore it):
metrix profile --profile quick -- ./decode_dp4a | grep -oE 'avg=[0-9.]+'
metrix profile --profile quick -- ./decode_dot8 | grep -oE 'avg=[0-9.]+'
```
Result (MEASURED, bit-exact vs CPU ref): dp4a 83 µs vs dot8 38 µs → **native `v_dot8_i32_iu4` wins ~2.2×** for int4 decode.

## 3. Verify a kernel emits the instruction you think (don't assert)
```
scripts/disasm-gfx.sh mul_mat_2of4_fp8.cu gfx1201 'v_swmmac|v_wmma|v_dot'
```
Confirms e.g. `v_swmmac_f32_16x16x32_fp8_fp8` is really emitted in a real loop (not folded), before trusting any throughput number.

## 4. Latency-vs-issue-bound diagnosis (the ILP lever)
A single-accumulator microbench showed `v_swmmac_i32_16x16x64_iu4` 13% below the dense-WMMA issue rate. The diagnostic: apply independent-accumulator ILP (N=2,4,8) to BOTH the target and the baseline.
- Baseline (dense WMMA) flat under ILP → already at the hardware issue peak.
- Target (SWMMAC) climbed 22.2→24.9 Ginstr/s → it was latency-limited; ILP recovered 82% of the gap.
Result (MEASURED): raw-instruction ceiling **3.49× → 3.90×** vs int8; the residual ~2.7% is a genuine fixed sparsity-decode cost (survives ILP + occupancy) — 4.0× does not hold. *Both prior assumptions — "full 4×" and "stuck at 3.49×" — were wrong; only running it gave the truth.*

## 5. Unlock the "broken" memory counters (perf-level gate, not firmware)
```
scripts/profile-datapath-gfx.sh ./my_kernel      # sets STABLE_STD, runs rocprofv3, restores AUTO
```
On RDNA3/4, GL2C_EA_*/FETCH_SIZE read 0 under the default perf level — they are perf-level-gated, not broken. STABLE_STD unlocks a real measured memory roofline where others give up or derive-from-scaling.
