# Gemma 4 E4B-it emotion LoRA audit

Observed on 2026-07-30. This document distinguishes static correctness from
Radeon execution evidence. No training result is claimed until the real ROCm
run produces the required manifests.

## Decision

The pasted V2 Notebook is a useful safety step but is not yet a top-tier
multimodal training submission. It correctly rejects `all-linear` and adds a
visual regression guard, but the executable Notebook contained a corrupted
regex boundary, accepted verbose answers as valid labels, used a broad
`language_model` name test, loaded a generic causal-LM class, reused the test
split during development comparison, did not fingerprint frozen modality
weights, and offered no real distributed-launch path.

V3 fixes those static defects and adds fail-closed two/four-GPU launch assets.
The remaining blocker is empirical: image and audio semantic retention,
distributed scaling, accuracy, macro-F1, calibration, latency, peak VRAM, and
RCCL stability must be measured on the designated Radeon environment.

The observed ModelScope heads are pinned to model commit
`1fe35ce743b357484b97a11646125adffee0b410` and dataset commit
`21e1bff1b4ff17af78543d79d69f074a26b08266`. The lock receipt is
`evidence/GEMMA4_MODELSCOPE_REVISION_LOCK_2026-07-30.json`; final execution
must also seal the downloaded file-manifest fingerprint.

## P0 findings and repairs

1. **Corrupted exact-label regex.** JSON decoded `\b` into literal backspace
   bytes in executable source. V3 removes regex-based permissive scoring and
   accepts only an exact normalized label.
2. **Wrong multimodal loading contract.** V2 used
   `AutoModelForCausalLM`; V3 uses the official
   `AutoModelForMultimodalLM` path and `AutoProcessor`.
3. **Over-broad LoRA discovery.** Merely containing `language_model` is not a
   sufficient boundary. V3 positively allows only attention and MLP
   projections under numbered text-decoder layers, then independently rejects
   every vision/audio/projection/embedding/head path.
4. **Frozen tower proof was incomplete.** `requires_grad=False` prevents
   optimizer updates but is not an artifact-level proof. V3 records exact
   pre/post SHA-256 fingerprints of vision/audio towers and modality
   projections.
5. **Evaluation leakage.** V3 uses validation for before/after development
   comparison and runs the locked test once after checkpoint selection.
6. **Best checkpoint was named but not loaded.** V3 sets
   `load_best_model_at_end=True` with matching evaluation and save cadence.
7. **Notebook multi-GPU is the wrong abstraction.** V3 delegates distributed
   launch to a deterministic script and Accelerate profiles. It never uses
   `device_map="auto"` for training.

## Multi-GPU progression

1. Run the RCCL all-reduce preflight. A visible second GPU is not sufficient;
   every rank must return the exact collective sum.
2. Start with two-GPU DDP if the complete model fits on each GPU. Keep the
   effective global batch at 16 (`2 per device × 4 accumulation × 2 ranks`) so
   the optimization comparison is controlled.
3. Use two-GPU FSDP2 when memory, rather than throughput, is the constraint.
   FSDP activation checkpointing is enabled in the Accelerate profile while
   Trainer checkpointing is disabled to avoid double wrapping. The profile
   explicitly wraps `Gemma4TextDecoderLayer`; it omits the removed
   `fsdp_use_orig_params` FSDP1 option because FSDP2 uses original parameters
   through DTensor semantics.
4. Scale to four-GPU DDP only after two-GPU convergence parity and throughput
   efficiency pass. Use `2 × 2 × 4 = 16` to preserve the global batch while
   reducing accumulation overhead if the per-rank memory-fit preflight passes.
5. Accept a distributed run only if its adapter hash, immutable model/data
   revisions, world size, effective batch, ROCm version, per-rank device
   identity, validation curve, and final locked-test outputs are sealed.
   The trainer aborts on a mismatched global batch or Accelerate backend and
   atomically seals one completion receipt per rank.

## Evidence gates

- Exact-label accuracy and macro-F1 with confidence intervals.
- Invalid-output rate and per-class recall, especially minority `surprise`.
- Seed variance across at least three training seeds for the promoted
  configuration.
- Frozen vision/audio/module fingerprints identical before and after.
- A larger held-out image suite plus a real audio semantic-retention suite.
  The four synthetic image fixtures remain only a smoke regression guard.
- DDP/FSDP convergence parity against the single-GPU global-batch-controlled
  run.
- Throughput, peak VRAM, wall time, communication overhead, and failure/retry
  logs.
- No final submission claim until real Radeon evidence exists.

## Primary references

- Gemma 4 official Transformers documentation:
  <https://huggingface.co/docs/transformers/model_doc/gemma4>
- Gemma 4 official implementation:
  <https://github.com/huggingface/transformers/blob/main/src/transformers/models/gemma4/modeling_gemma4.py>
- TRL distributed-training documentation:
  <https://huggingface.co/docs/trl/distributing_training>
- AMD ROCm documentation:
  <https://rocm.docs.amd.com/>
