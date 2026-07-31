# DETERMINEX
### Compiler-verified AI. Private. Local. Measured on AMD Radeon.

**Track 2 · Private AI Agents · DarthCeltic · AGPL-3.0-or-later**

---

## THE PROBLEM

> Cloud coding assistants require shipping your source to a third party.
> Local assistants hand you one small model with **nothing checking its work**.
>
> A 1.5B model that is confidently wrong costs more review time than no assistant at all.

---

## THE IDEA — one rule, strictly enforced

# ❝ No model ever judges its own output. ❞

A real compiler or a real test suite is the only oracle. The model *proposes*.
The oracle *disposes*. There is no LLM-as-judge anywhere in the loop.

```
   idea ──► ARCHITECT ──► BUILDER ──► ┏━━━━━━━━━━━━━━━━━━━┓ ──► verified program
    7B          1.5B  ╲   K cands     ┃  ORACLE           ┃
                       ╲              ┃  rustc · go       ┃
                        ╲             ┃  pytest · tsc     ┃
                         ╲────────────┃  DETERMINISTIC    ┃
                          exact error ┗━━━━━━━━━━━━━━━━━━━┛
                          injected on failure
```

**P(correct) = 1 − (1 − p)^K** — any model with p > 0 is driven toward correct
by sampling more candidates. Model quality sets `p`. **The system sets `K`.**

---

## WHY THAT MAKES IT AN AMD STORY

If correctness comes from verifying K candidates, then accuracy is bounded by
**GPU batch throughput**, not by model quality. So the GPU question becomes:
*what does the 6th candidate actually cost?*

Measured on Radeon — ROCm 7.2.1 · vLLM 0.16.1 · Qwen2.5-Coder-7B-Instruct:

| | Single stream | **K=6 concurrent** |
|---|---:|---:|
| Throughput | 30.0 tok/s | **166.9 tok/s** |
| Wall clock | 17.05 s | **18.41 s** |

# 5.56× throughput · 1.08× wall clock

**Six candidates cost 8% more time than one.**

| At p = 0.3 | one sample | six samples |
|---|---:|---:|
| Solve rate | 30.0 % | **88.2 %** |
| Time | 17.05 s | 18.41 s |

### Correctness nearly triples for an 8% time premium.
*That is a GPU property converted directly into a correctness property.*

---

## WHAT THE RADEON RUN CAUGHT

The first run on AMD hardware reported:

```
result: not solved   samples=12          ← every candidate scored 0.00
```

**The model was right all twelve times.** Each answer was correct code inside a
```` ```python ```` fence — which the harness's own prompt demands. Fence-stripping
existed in exactly one provider. Every other provider fed markdown to the oracle,
where the module failed to import and every check failed.

The system reported a *verdict about the model* for a *defect in the harness*.

```
after the fix:   result: SOLVED   samples=1
```

**The transferable rule, now stored in the project's knowledge corpus:**

> A uniform 0.00 across every sample **and** every temperature is a *harness*
> signature. A genuinely weak model fails in **varied** ways.
> Import error on all candidates → harness. Assertion failure → model.

A green test suite had carried this bug: the existing test fed fenced code and
asserted only that no *generation error* occurred — never that the build solved.
The new guard asserts the outcome, and reverting the fix fails 4 of 7 tests.

---

## WHAT WE DO NOT CLAIM

| | |
|---|---|
| **ProgramBench** | **0 / 200.** A provenance audit retracted 62 of 67 prior "solves" as upstream source builds. Zero is the honest figure — and it matches every public frontier model. |
| **AMD free API** | Never executed. Portal needs a China-registered account. Wired, labelled, not claimed. |
| **~46 GiB VRAM** | *Derived* from KV-block telemetry under a stated bf16 assumption — not read from `rocm-smi`. |
| **Local Ollama path** | Documented, not measured on a physical Radeon card. |

*A benchmark number that cannot survive a provenance audit is worth less than a zero that can.*

---

```
github.com/DarthCeltic/Determinex          AGPL-3.0-or-later
python scripts/determinex_build_from_idea.py --idea idea.md --provider vllm --k 6
```
