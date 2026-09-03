# Demo — watch Hyperloom optimize a kernel, live

`run_demo.sh` runs Hyperloom's optimization mission loop end-to-end on a real AMD Radeon GPU (validated on gfx1201 / R9700). It's the whole method in ~30 seconds, on-box, correctness-gated:

```
bash demo/run_demo.sh
```

**What it does, step by step:**

| Step | Action | Ground-truth tool |
|---|---|---|
| 0 · DETECT | identify the exact silicon | `rocminfo` |
| 1 · SCAN | is the native 8-wide int4 dot (`v_dot8_i32_iu4`) present? | `llvm-mc` (the assembler can't lie) |
| 2 · FIND-GAP | the int4 decode path uses the dp4a route (2 dot instrs / 8 values) instead of the native dot8 (1 instr / 8 values) | disassembly |
| 3 · FIX | build both routes; prove which instruction each emits | `hipcc --save-temps` |
| 4 · VALIDATE + MEASURE | run both on the GPU, correctness-gate bit-exact vs a CPU int reference, time them | on-box |



**Why this is the agentic story:** Hyperloom didn't guess. It *scanned the silicon* to prove the instruction exists, *disassembled* to prove the kernel wasn't using it (the gap), *wrote* the fix, *correctness-gated* it, and *measured* the win — the same measure-never-assume loop it applies across the whole inference stack. In the full system, the local LLM brain drives this loop and escalates to a Radeon-cloud model only when genuinely stuck (see `../agent/escalation.py`).
