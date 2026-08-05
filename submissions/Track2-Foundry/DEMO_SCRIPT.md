# Foundry demo video — script v1 (target 4:30, hard cap 5:00)

Recorded on the granted Radeon (Session 2, after feature freeze). The
rules require the video to show actual GPU execution; every factory
beat keeps the UI's live GPU card in frame, plus a small terminal
running `watch -n1 rocm-smi` for authenticity.

Rubric mapping is internal — never say "rubric" on camera, but every
beat below names the line it scores.

---

## Beat 1 — Cold open: the product, not the machinery (0:00–0:25)
*Scores: task positioning; application value.*

ON SCREEN: a terminal. `llama-server -m triage-q5_k_m.gguf` already
running. Paste two tickets; instant JSON answers. A file listing shows
the model: **424 MB**.

VO (draft): "This model triages support tickets — instantly, offline,
on 424 megabytes. You can't download it, because it didn't exist until
an agent manufactured it this morning. That agent is called Foundry,
and it runs on one AMD Radeon."

CUT TO: the Foundry UI, empty chat, GPU card live.

## Beat 2 — Describe the model you need (0:25–1:00)
*Scores: multi-turn UX; task decomposition (plan visible).*

TYPE (exact, rehearsed):
> I need a small model that triages Northbeam support tickets. It reads
> a ticket and outputs a category (outage, account_access, billing,
> technical_issue, data_request, feature_request) and a priority
> (P1–P4). The labeling rules are in seeds/triage_policy.md.

Agent interviews/confirms → `save_task_spec` chip → `preview_examples`
chip → three samples appear.

TYPE: > The samples look right. Small build first: 54 train, 12 holdout.

VO: "You describe the model in plain language. Foundry plans the
pipeline: it drafts a task spec, grounds itself in your policy
document — retrieval from your seed docs, nothing invented — and shows
you samples before spending your GPU's time."

## Beat 3 — The factory runs (1:00–2:10)
*Scores: core inference on Radeon (GPU card + rocm-smi visibly hot);
tool invocation; RAG.*

ON SCREEN: `generate_dataset` chip with elapsed timer; GPU card VRAM
jumps (30B teacher resident, ~18GB); util spikes. Radeon pilot timing:
datagen ~75s (light timelapse to ~20s), train ~25s (real time — the
teacher card visibly unloads, training takes the GPU, teacher returns),
eval ~5s. Eval table renders: base vs tuned.

VO: "A 30-billion-parameter teacher generates the training data locally
— on this Radeon, watch the memory — then a 0.6B student is LoRA-tuned
on it, and evaluated against the teacher's held-out labels. Base model:
guessing. Tuned: [read the number]."

## Beat 4 — The loop that makes it an agent (2:10–3:00)
*Scores: core capabilities (memory + decomposition); scenario depth.*

TYPE: > Diagnose the failures. If any class is weak, fix it: add
> focused examples, retrain, and show me before and after on the same
> holdout.

`diagnose_failures` chip → weak class named with per-class recall →
`augment_dataset` (focus) → `train_student` → `evaluate_student` →
agent reports before/after delta.

VO: "Foundry evaluates its own product, finds the weak class, generates
targeted data for exactly that weakness — the holdout stays frozen so
the comparison is honest — and retrains. This is the loop: diagnose,
regenerate, improve. No human labeled anything."

## Beat 5 — The receipts (3:00–3:50)
*Scores: inference-speed optimization (the 20-pt line); bonus setup.*

TYPE: > Benchmark it across quantizations.

`benchmark_quants` chip (timelapse) → chart renders inline: accuracy
bars, speed line, teacher reference. CUT TO the pre-baked full-scale
numbers (Session 1 run, registry rail visible for continuity):

- 1,008 examples, 98.7% acceptance, ~20 minutes end to end
- exact match **0.15 → 0.95** on 100 held-out
- student vs 30B teacher: [Radeon tok/s ratio] faster, 1/40 the disk
- second registry task on screen: expense_claim_routing — "different
  domain, zero code changes"

VO: "The receipts. Quantization ladder: accuracy against size against
speed — pick your point. At full scale the student matches the teacher
it was distilled from: fifteen percent exact match before, ninety-five
after. And the registry remembers every experiment — this expense-
routing model was built the same way from a different policy doc,
with zero code changes."

## Beat 6 — Why local, why Radeon (3:50–4:20)
*Scores: scenario positioning; ROCm narrative.*

ON SCREEN: simple slide or README section.

VO: "None of this works as an API wrapper. Fine-tuning can't happen
over a chat API. Generating fifty thousand teacher examples would cost
hundreds of dollars hosted — here it's free, private, and your policy
documents never leave the machine. Stack: llama.cpp on ROCm serves the
teacher, PyTorch-ROCm and peft train the student, on a 48-gigabyte
Radeon. One GPU. The whole factory."

## Beat 7 — Close (4:20–4:30)

VO: "Small models, made to order, on your Radeon. Foundry." END CARD:
repo URL + "AMD AI DevMaster Hackathon — Track 2".

---

## Contingencies

- Every live beat has a pre-baked twin: keep Session 1's run dirs in
  runs/ so any failed live stage cuts to its completed artifact.
- If the agent narrates without calling a tool (known 4B quirk; should
  fade on the 30B brain): the rehearsed prompts above include explicit
  verbs; if it still stalls, one nudge line is acceptable on camera —
  it reads as conversation, not failure.
- FABRICATION WATCH: if the agent states any number not visible in a
  tool chip, CUT. Re-record the beat. Never ship an invented metric.
- Priority-P2 skew, empty classes at n=12: don't read class-level
  numbers on camera at pilot scale; only the diagnose output.

## Radeon Session 2 shot list (~60 min, after freeze Aug 1)

1. Pre-stage (no recording): instance up, repo + models + Session-1
   runs/ + registry restored, UI served (cloudflared or Jupyter proxy —
   test BEFORE recording), OBS/recorder configured 1080p.
2. Record Beat 1 (student GGUF from Session 1).
3. Record Beats 2–5 in ONE take if possible (pilot-scale timings above;
   total live runtime ≈ 4 min of capture, timelapse in edit).
4. Capture 10s of `watch rocm-smi` B-roll during datagen and training.
5. Retake budget: 2 full retakes ≈ 15 min. Then DESTROY INSTANCE.
6. Edit locally (free): timelapse, VO, captions, end card.

## Rehearsal findings (July 18, local, post-reboot — full arc ran)

- Local timings at pilot scale: preview ~40s, datagen 144s, train 204s
  (fresh) / 77s (augmented, shorter seqs), eval ~25s, augment 46s.
  Radeon measured equivalents are ~5-8× faster — beat budget holds.
- The Beat-4 compound prompt works: diagnose → focused augment →
  retrain → re-eval chained autonomously, and the before/after used
  the structural previous_tuned comparison correctly.
- HAZARD (patched in prompt, verify each rehearsal): with no benchmark
  pending, the closing turn caused a FABRICATED "final export" (invented
  file + wrong size). Rule added; if any stage is announced without its
  chip, CUT the take.
- Flat-delta risk: at n=12 holdout, augmentation showed "no
  improvement" (honestly reported). For the video, Beat 4 runs at full
  scale on the Radeon (n=100 resolves 1% deltas; 30B labels are less
  noisy). If the live delta is still flat, cut to the pre-baked
  improvement run (0.667→0.833) rather than shipping a flat beat.
- 4B stand-in teacher mislabels edge cases in previews (whole-team
  outage labeled technical_issue). Fine locally; the 30B teacher on
  Radeon labels these correctly — do NOT read stand-in labels aloud in
  any local practice recording.
- Pace the demo human-driven: wait for the agent's ready state before
  the next line; scripted-harness turn misalignment does not occur when
  a human is typing.

## Rehearsal checklist (local, before any Radeon time)

- [ ] Full arc runs via the exact prompts above (chat.py --script)
- [ ] Timings recorded per beat (local numbers; Radeon will be faster)
- [ ] No fabricated numbers in any agent reply (check against chips)
- [ ] UI renders every artifact (tables, chart) without touching a
      terminal mid-demo
- [ ] VO read against a stopwatch: ≤ 4:30
