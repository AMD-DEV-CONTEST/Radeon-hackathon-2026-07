# FOUNDRY.md — Decision record and project spec

Decided July 16, 2026, after in-session verification of every compatibility
claim below. This is the reference for architectural decisions. If reality
contradicts this document (cloud GPU specs, credit quota, trainer
compatibility), update this document in the same session you learn it.

## The pick

**Track 2 (Agentic AI / "Private AI Agents"), project "Foundry"** — an
autonomous model-distillation agent. Solo entry. Target: 1st place ($5,000).
Deadline: **August 6, 2026, 11:59 PM UTC+8** (= 5:59 PM CEST, 8:59 AM PDT).
Internal deadline: **PR submitted August 4**. Feature freeze: **August 1**.

## The product in two sentences

You tell Foundry what you need in plain language — "a model that extracts
line items from invoices" — and the agent autonomously runs the entire model
factory on one Radeon: it plans the pipeline, generates tens of thousands of
synthetic training examples with a local ~30B teacher (grounded in seed
documents you supply), QLoRA fine-tunes a 0.6B–1.7B student, evaluates it
against the teacher, diagnoses failure clusters, regenerates targeted data,
retrains, and emits a quantized GGUF you can run anywhere. The demo's closing
shot: teacher and student side by side on the same eval — equal accuracy,
~10× faster, ~1/40 the size — "built in minutes on one Radeon, cost $0."

## Why Track 2 over the other tracks

- **Track 1 (Multimodal):** 80 of 100 points on subjective
  functional/innovation axes, judged in the thickest field (image-gen tools).
  GPU performance is only 20 points — the engineering edge is worth least here.
- **Track 3 (Physical AI):** points split five ways; 10 points require
  upstream open-source contributions accepted within three weeks (not in our
  control); solo + $0 + no robot = sim-only against robotics labs.
- **Track 2:** half the real rubric (40 ROCm + 20 bonus of 120) is objective,
  demonstrable engineering that the median agent entrant treats as a checkbox.
  Points are cheapest where the field under-invests.

## The real rubric (120 points — Luma page shows only the abbreviated 100)

Source: official Rules & Conditions doc, verified July 16, 2026. Key rule:
**"Core inference processes shall be executed locally on AMD Radeon GPU;
remote APIs are not allowed for core functions."**

| Rubric line | Pts | Target | Basis |
|---|---|---|---|
| Clear task positioning & creative scenario | 20 | 16–18 | Category of one; concrete judge-relatable end tasks |
| Core capabilities: task decomposition, tool invocation, RAG, memory | 20 | 18–20 | Pipeline planner; datagen/trainer/evaluator/quantizer tools; RAG mines seed docs into training data; experiment registry = cross-session memory. All load-bearing, none bolted on |
| Smooth multi-turn interaction | 20 | 15–17 | Natural dialogue: spec → sample review → eval report → critique → targeted retrain |
| Core inference on Radeon GPU | 20 | 20 | Teacher inference + training + student inference — three ROCm workloads on one card. Show rocm-smi live in demo |
| Targeted inference-speed optimization | 20 | 16–18 | Benchmark charts on all three workloads: batched datagen throughput, student quant ladder, student-vs-teacher latency |
| Bonus: quantized/distilled model via Radeon cloud API | 20 | 15–20 | The product IS distillation + quantization; deploy student as Radeon cloud vLLM dedicated endpoint |
| **Total** | **120** | **~100–113** | Median chat-wrapper entry plausibly ~60–70, no bonus |

Build to the rubric's own vocabulary: the four named capabilities (task
decomposition, tool invocation, RAG, memory management) must be implemented,
*labeled with those words* in the demo and docs.

## Why local ROCm is load-bearing (the anti-"API wrapper" argument)

1. **Training cannot happen over an inference API, period.** No hosted-API
   version of this product exists.
2. **Datagen is economically absurd remotely:** 30–50K synthetic examples ≈
   tens of millions of teacher tokens — hundreds to thousands of dollars via
   API, free on the Radeon.
3. **Privacy:** the seed documents the training set is mined from never leave
   the machine.

Physics and economics, not policy. This is the answer when a judge asks "why
not just call an API?"

## Prior art and differentiation (checked July 16, 2026 — cite honestly)

- **Kiln** (github.com/Kiln-AI/kiln): closest prior art. A local-first
  *workbench* a human drives stage by stage; exports fine-tuning to cloud
  platforms (Fireworks etc.); no ROCm story. Foundry = the autonomous closed
  loop (plan → generate → train → eval → diagnose → iterate) entirely on
  local AMD silicon. Cite Kiln in the writeup — it proves demand.
- **Flag autotuners** (llama-optimus, TurboLLM, OpenJet): killed an earlier
  candidate idea ("agent that tunes ROCm/llama.cpp flags") — known category,
  do not drift toward it.
- **amd/gaia issue #667** requests exactly this Unsloth QLoRA integration —
  AMD's own agent framework wants this and nobody has built it. Upstream hook
  and judge-appeal line.
- **AMD's own blog** "10x Model Fine-Tuning Using Synthetic Data with Unsloth
  on AMD GPUs" endorses the manual version of this exact workflow. Foundry's
  novelty = the agent driving it end-to-end.
- Earlier candidate "Discovery" (legal evidence-corpus agent) was vetoed by
  the user: domain too tricky, under the hood still RAG-over-documents.

## Verified facts (all checked in-session, July 16, 2026)

- **ROCm 7.2 (March 2026):** first release with official RDNA4 support
  (RX 9070 / XT, gfx1201) + RDNA3; single installer Windows+Linux; out-of-box
  llama.cpp / Ollama / vLLM / LM Studio support on Radeon.
- **Teacher performance:** Qwen3-30B-A3B-class MoE GGUF ≈ **150 tok/s** token
  generation via llama.cpp ROCm HIP on Radeon AI PRO R9700; newer
  Qwen3.5-35B-A3B / Qwen3.6 exist. Tool calling works in llama.cpp.
- **Unsloth official AMD support (May 2026):** Radeon RDNA 2/3/4
  (RX 6000–9000), QLoRA ~70% less memory, one-line installer, requires
  ROCm ≥ 6.0. AMD publishes an official Unsloth fine-tuning playbook
  (developer.amd.com/playbooks/unsloth-llms-finetuning).
- **Trainer fallbacks:** HF transformers+peft (PyTorch ROCm ≈ 95% CUDA
  feature parity — QLoRA works) and torchtune (AMD documents it on ROCm).
- **vLLM RDNA4 native FP8 is NOT mainline** — loads FP8 then silently falls
  back to FP32 dequant (vLLM forums). **GGUF Q4/Q5 is the baseline; do not
  put FP8 on the critical path.**
- **Radeon cloud (hackathon grant):** free shared OpenAI-compatible endpoints
  (Qwen, DeepSeek — no credits) + dedicated vLLM endpoints and instances that
  **burn credits continuously until explicitly destroyed** (red "Destroy
  Instance" button in Profile → Active Instance). Access via JupyterLab / SSH.
- **Local dev box:** RTX 4060 Laptop 8GB + i7-14650HX, **no AMD GPU** — all
  ROCm numbers must come from the cloud Radeon; local dev uses llama.cpp
  CUDA/Vulkan (same GGUF, same OpenAI-compatible API, zero credits).
- Windows ROCm supports only gfx1200/1201 — moot here (dev box is NVIDIA;
  cloud instance is Linux).

## Unverified — resolve before architecture hardens

1. **RESOLVED July 17:** cloud GPU = gfx1100 (RDNA3, W7900-class),
   **48 GB VRAM**, 128-thread EPYC host, 503 GiB RAM, 2.9 TB free disk.
   Image ("unsloth_llama.cpp:latest") ships NO torch/unsloth in system
   Python 3.12 — stack gets installed by us. See
   notes/radeon-cloud-instance.md.
2. **Credit quota.** Undocumented. → Ask on Discord / check Space tab.
3. **Unsloth on the cloud image.** Official AMD support ≠ works on that
   specific container (Unsloth issue #5180 shows HIP-detection env hell is
   real). → Week-1 gate below.

## Model plan

- **Teacher:** Qwen3-30B-A3B-class MoE, GGUF Q4/Q5, served by llama-server
  (tool calling + parallel slots for batched datagen).
- **Students:** Qwen3-0.6B / 1.7B (Llama-3.2-1B as alternate).
- **Trainer: LOCKED July 17 = transformers+peft** (bf16 LoRA), after
  both gates passed on the Radeon. This deviates from the
  pre-registered "unsloth if Gate B passes" rule, on evidence: identical
  train loss and eval vs peft, no measured speed win at 0.6B (our
  lora_dropout=0.05 disables unsloth's fast-path patching), and unsloth
  globally patches transformers, forcing process isolation between
  train and eval (notes/unsloth-global-patch-isolation.md). Unsloth
  stays a validated flag-flip (`backend = "unsloth"`), worth revisiting
  for 1.7B+ students or 4-bit QLoRA. torchtune never needed.
- **Packaging:** merge LoRA → convert to GGUF → llama.cpp quant ladder
  (Q4/Q5/Q6) with eval-vs-size-vs-speed table.

## Submission numbers (Radeon Session 1, July 18 — final unless re-run)

Full scale on the granted gfx1100: **base 0.15 → tuned 0.97 exact match**
(n=100); 99.0% datagen acceptance; whole loop ~21 min; quant ladder
Q4 378MB/284.9 tok/s/0.92 · **Q5 424MB/283.4/0.97** · Q6 472MB/273.9/0.97
· Q8 610MB/256.5/0.97; teacher 30B 17.7GB/110.2 tok/s → Q5 student is
**2.6× faster at 1/42 the size, same-holdout accuracy 0.97**. Details:
notes/radeon-session1-numbers.md.

## Three-week plan

- **Days 1–3 (Jul 16–18):** Radeon cloud application; Discord questions
  (GPU model, VRAM, quota); agent scaffold locally against llama-server on
  the 4060; experiment-registry schema.
- **Week-1 gate: PASSED July 17 (Gate A, peft), 6 days early.** Pilot
  slice end-to-end on the granted 48GB gfx1100 in 112s — datagen with
  30B teacher, peft LoRA train on torch-2.10-rocm7.2.4, eval, GGUF
  export + served smoke test. See notes/radeon-gate-a-passed.md.
  Gate B (unsloth) also passed same day; **full 1K run July 17 =
  headline number: base 0.15 → tuned 0.95 exact match, whole loop in
  ~20 min on gfx1100** (notes/radeon-full-run-numbers.md). Week-1 gate
  fully closed 6 days early; all three kill risks retired or bounded.
- **Week 2 (Jul 24–30):** agentify — planner, eval-driven iteration loop
  (failure clustering → targeted datagen), experiment-registry memory,
  multi-turn UI, seed-doc RAG. Datagen throughput optimization + benchmark
  harness that emits the submission charts.
  **Progress July 17 (a week ahead):** TaskSpec refactor done (task = data,
  specs/*.json; agent drafts specs from conversation); agent core live
  (llama-server tool calling, 9 tools then — 11 as of July 18, registry
  memory, GPU orchestration);
  E2E validated on 4060 — conversation → spec → preview → dataset → train
  → eval → diagnosis (weak-class detection + focus-regen proposal) →
  exported GGUF (notes/agent-e2e-milestone.md). Later same day:
  **targeted-regen round trip validated** (resume from registry →
  diagnose → augment +30 focused w/ frozen holdout → retrain → exact
  match 0.667→0.833, notes/regen-roundtrip-milestone.md) and
  **generality proven** — second domain (expense routing) built from a
  new seed doc with zero code changes, agent-drafted spec
  (notes/generality-second-task.md). **Benchmark harness validated same
  day** — quant ladder + llama-bench tok/s + served accuracy + chart,
  standalone and as an agent tool (notes/bench-harness-milestone.md);
  Radeon Session 1 (rebuild + bench, ~75 min) scripted in the runbook.
  **Web UI shipped and browser-validated same day** (Flask + one static
  page; streamed agent events, live GPU telemetry card, build badges —
  notes/web-ui-milestone.md); UI decision resolved in favor of the thin
  web view for the 20-pt multi-turn line. Remaining for week 2: optional
  seed-doc RAG chunking, demo-task/script selection.
- **Week 3 (Jul 31–Aug 4):** second demo task (prove generality), student
  quant ladder, deploy student to Radeon cloud dedicated vLLM endpoint
  (20-pt bonus), **freeze Aug 1**, video + PDF tech report + PPT,
  **PR by Aug 4.**

## Kill risks, ranked

1. **ROCm training environment on the cloud instance.** Inference is mature;
   training is the newer surface. Mitigation: week-1 gate + two fallback
   trainers. Worst case: drop training, ship datagen + eval + quantize loop
   (weaker but submittable).
2. **Credit burn.** Develop on the 4060; the Radeon is a staging/benchmark
   box hit with scripted, reproducible runs. Small students only, capped
   dataset sizes, estimate cost before every launch (project rule).
3. **Demo fragility.** Live training step kept small (minutes); pre-baked
   checkpoints as fallback for the video.

## Demo rules (these are scoring decisions, not style)

- **Never open with the machinery.** Open with the end task (an invoice, a
  ticket queue), show the tiny model nailing it, then reveal the factory.
  If the demo opens with training curves, we lose the same way a chat-box
  opening would have lost.
- Show rocm-smi / GPU telemetry live next to the agent.
- Money shot: teacher vs student side by side, same eval, ~10× speed.
- Two tasks demoed: one live, one pre-baked (generality proof).
- Video 3–5 minutes, must show actual GPU execution (rules requirement).

## Submission checklist

- [ ] AMD AI Developer Program membership (prize eligibility — hard gate)
- [ ] Luma registration; valid Discord ID + GitHub ID
- [ ] Radeon cloud access application (github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07, Radeon-Cloud-User Guide)
- [ ] PR against AMD-DEV-CONTEST/Radeon-hackathon-2026-07, title
      **"Track 2, <team name>, Foundry"**, all materials in English
- [ ] PDF technical documentation
- [ ] Source code + README
- [ ] Demo video, 3–5 min, showing GPU execution
- [ ] PPT or poster (one of the two)

Note: repo/versioning setup deliberately deferred — the submission is a PR
from a fork of the contest repo, so decide at registration whether the
project lives inside a clone of that fork; don't git-init a structure that
fights it.

## Sources (verified July 16, 2026)

- Rules & Conditions doc (Google Docs, linked from Luma page) — rubric + API prohibition
- rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html
- rocm.docs.amd.com/en/7.13.0-preview/ai-inference/vllm.html
- github.com/ggml-org/llama.cpp/discussions/15021 (ROCm HIP perf)
- github.com/ggml-org/llama.cpp/discussions/19890 (R9700 llama-bench)
- discuss.vllm.ai/t/native-fp8-wmma-support-for-amd-rdna4-rx-9070-xt-r9700-in-vllm/1900
- unsloth.ai/docs/blog/unleash-the-power-of-amd-official-support-for-unsloth-is-here
- unsloth.ai/docs/get-started/install/amd
- developer.amd.com/playbooks/unsloth-llms-finetuning
- amd.com/en/developer/resources/technical-articles/2025/10x-model-fine-tuning-using-synthetic-data-with-unsloth.html
- rocm.blogs.amd.com/artificial-intelligence/torchtune/README.html
- github.com/amd/gaia/issues/667
- github.com/Kiln-AI/kiln
- github.com/BrunoArsioli/llama-optimus (+ TurboLLM, OpenJet — autotuner prior art)
- github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07 (submission mechanics, cloud user guide)
- github.com/unslothai/unsloth/issues/5180 (HIP-detection env failure mode)
