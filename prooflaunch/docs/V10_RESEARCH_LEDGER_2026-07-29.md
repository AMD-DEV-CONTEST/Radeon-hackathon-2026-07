# Cortex-X V10 research ledger — 2026-07-29

This ledger converts current primary research and official documentation into
falsifiable engineering decisions. A cited idea is not a claimed result.
Every row names a baseline, a kill condition, and the local contract that can
test it.

## R01 — privileged self-distillation can suppress correction

- Source: [Rethinking On-Policy Self-Distillation for Thinking Models](https://arxiv.org/abs/2607.05184)
- Finding used: privileged context can hurt long reasoning and suppress
  high-entropy forks, verification, backtracking, and reconsideration.
- V10 hypothesis: monitor high-entropy branch tokens and reject a distilled
  checkpoint if correction/backtracking falls while short-task accuracy rises.
- Baseline: ordinary on-policy distillation without privileged context.
- Kill condition: long-horizon avg@k or recovery success regresses beyond the
  frozen tolerance.
- Local contract: `v10_training.py`, on-policy stage; Radeon result pending.

## R02 — teacher strength is insufficient without compatibility and novelty

- Sources: [THUNLP OPD code](https://github.com/thunlp/OPD) and
  [paper](https://arxiv.org/abs/2604.13016)
- Finding used: OPD depends on compatible thinking patterns and genuinely new
  teacher information; off-policy cold start and aligned prompt selection can
  recover failing regimes.
- V10 hypothesis: calculate teacher/student support overlap and
  teacher-information gain before spending the OPD budget.
- Baseline: blind KL matching from a nominally larger same-family teacher.
- Kill condition: teacher overlap is high but added information and downstream
  improvement are statistically absent.
- Local contract: `v10_training.py`; overlap instrumentation and Radeon
  measurements remain open.

## R03 — agent training should preserve environment transitions

- Source: [Agent-R1](https://github.com/AgentR1/Agent-R1)
- Finding used: step-level MDPs retain prompt, response, environment state, and
  next observation instead of retokenizing one ever-growing string.
- V10 hypothesis: typed per-step trajectories reduce tool drift and improve
  failure attribution over append-only token traces.
- Baseline: append-only conversation trajectory.
- Kill condition: no significant tool-error or attribution gain on the frozen
  agent cases.
- Local contract: typed `CampaignAction`, `CampaignWorldState`, and bounded
  planner in `v10_intelligence.py`; learned trajectory result pending.

## R04 — durable human interrupts require replay-safe nodes

- Sources: [LangGraph overview](https://langchain-ai.github.io/langgraph/index.html),
  [interrupt rules](https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/breakpoints/),
  and [persistence](https://langchain-ai.github.io/langgraph/concepts/time-travel/)
- Finding used: state is checkpointed at interrupts, but a resumed node begins
  again; side effects before an interrupt therefore need idempotence.
- V10 hypothesis: a single state-owning Supervisor plus content-addressed
  checkpoints prevents duplicate external actions after recovery.
- Baseline: in-memory agent loop without durable cursor or action idempotency.
- Kill condition: any completed action repeats after injected interruption.
- Local contract: existing durable mission executor plus `AgencyTopologyV10`;
  production database-backed wait remains open.

## R05 — future-aware planning must earn its cost

- Source: [Internalizing the Future](https://arxiv.org/abs/2606.27483)
- Finding used: prospective state rollout plus plan-conditioned success
  estimation provides a textual analogue of value-guided planning.
- V10 hypothesis: bounded action-conditioned search improves strategy quality
  over direct planning without exceeding the latency budget.
- Baselines: no search, fixed-depth search, pure LLM planner.
- Kill condition: blind strategy gain is below 15%, calibration fails, or
  median/hard latency exceeds 30/120 seconds.
- Local contract: `ActionConditionedPlanner` in `v10_intelligence.py`;
  measured comparison pending.

## R06 — sparse routing must be a hardware-aware product mechanism

- Source: [DeepSeek-V3](https://github.com/deepseek-ai/DeepSeek-V3)
- Finding used: sparse activation, auxiliary-loss-free balancing, and
  multi-token prediction are architecture/hardware co-design decisions.
- V10 hypothesis: top-2 role adapters with an explicit generalist fallback can
  recover specialization without multiple resident base models.
- Baseline: one monolithic LoRA and naïve multi-LoRA averaging.
- Kill condition: no GTM gain, unstable routing, or VRAM/latency violates the
  single-Radeon budget.
- Local contract: `SparseAdapterRouter` and adapter consolidation stage; the
  local design does not claim DeepSeek-scale MoE or MTP training.

## R07 — efficient video needs composite evaluation

- Source: [Efficient Video Diffusion Models](https://arxiv.org/abs/2604.15911)
- Finding used: step distillation, efficient attention, model compression, and
  cache/trajectory optimization attack different cost components; composed
  acceleration can lose quality.
- V10 hypothesis: distilled generation plus one-step temporal restoration and
  truthful 4K mastering improves time consistency without identity loss.
- Baselines: unaccelerated base, per-frame restoration, and V7 video path.
- Kill condition: temporal gain is below 30%, A/V alignment below 0.96, or
  product identity below 99.5%.
- Local contract: V10 media tensor and existing codec/identity gates; real
  Radeon video outputs pending.

## R08 — evaluation must remain multidimensional and inspectable

- Sources: [HELM](https://crfm.stanford.edu/helm/index.html),
  [VHELM](https://crfm.stanford.edu/helm/vhelm/v2.0.0/), and
  [HEIM](https://crfm.stanford.edu/helm/heim/latest/)
- Finding used: scenarios, adaptations, metrics, raw generations, and multiple
  aspects prevent one aggregate score from hiding regressions.
- V10 hypothesis: the 28-bar contract plus five same-hardware baselines catches
  failures hidden by a single leaderboard value.
- Baseline: one internal mean score.
- Kill condition: any claimed result lacks raw cases, parameters, outputs, or
  a declared incomparable axis.
- Local contract: `QualityTier.CORTEX_X_V10`; compiled evidence pending.

## R09 — noisy judges require human calibration

- Source: [Noisy but Valid](https://arxiv.org/abs/2601.20913)
- Finding used: judge TPR/FPR uncertainty affects statistical validity and must
  be estimated from human-labelled calibration data.
- V10 hypothesis: a binary judge is admissible only after at least 100 human
  labels with TPR and TNR each strictly above 80%.
- Baseline: uncalibrated LLM-as-judge scores.
- Kill condition: label count, TPR, or TNR misses the gate.
- Local contract: `JudgeCalibration` in `v10_training.py`; human labels pending.

## R10 — causal recommendations need explicit observational limits

- Source: [EconML](https://github.com/py-why/EconML)
- Finding used: orthogonal/doubly robust estimation and offline policy learning
  separate treatment effects from ordinary prediction.
- V10 hypothesis: stabilized observational estimates can rank hypotheses, but
  only qualified randomized evidence may support causal business claims.
- Baseline: correlation prediction.
- Kill condition: placebo, pseudo-treatment, time-reversal, calibration, or
  time-holdout tests fail.
- Local contract: `CausalMarketTwin` and `CausalExperimentAutopilot`; the
  reference twin is intentionally labelled simulated/predicted.

## R11 — provenance is not truth

- Sources: [C2PA 2.4](https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html)
  and [C2PA principles](https://c2pa.org/principles/)
- Finding used: manifests bind assertions and content history; they do not
  certify that an assertion is substantively true.
- V10 hypothesis: Claim→Source→Region/Frame→Transform→Approval binding improves
  auditability, while truth still comes from the source/claim gate.
- Baseline: unattached sidecar metadata.
- Kill condition: any transform, region, source hash, or approval cannot be
  traversed, or the UI describes provenance as truth.
- Local contract: `ProofManifestV10`; cryptographic C2PA signing is not claimed.

## R12 — the official Radeon matrix is exact, not generic “ROCm support”

- Sources: [ROCm 7.2 Radeon/Ryzen overview](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.2/)
  and [ROCm 7.2 compatibility matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.2/docs/compatibility/compatibilityryz/native_linux/native_linux_compatibility.html)
- Finding used: supported GPU, OS, framework, Python, dtype, user-space, and
  driver combinations are versioned and specific.
- V10 hypothesis: preflight must record exact device architecture, driver,
  ROCm/HIP, PyTorch, Python, dtype, disk, and immutable model revisions.
- Baseline: checking only `torch.cuda.is_available()`.
- Kill condition: any required tuple is outside the official matrix or cannot
  be reproduced from the trace.
- Local contract: `ProofLaunchRadeonPreflightV2`; target execution is blocked
  until the remote kernel channel works.

## Status

All twelve entries have a local testable contract. None of the learned,
human-rated, causal, or Radeon-dependent hypotheses is marked validated.

