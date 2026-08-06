# Radeon reproduction execution contract

This contract implements the deterministic control plane for Workstream 23.
It deliberately separates mechanisms that can be proven locally from GPU,
ROCm, model, performance, and clean-instance observations that require a live
Radeon execution plane.

## Memory and model lifecycle

Only one heavy model may be resident per rank. A swap must drop model
references, collect Python garbage, empty the device allocator cache,
synchronize, and re-measure free memory before admitting the next model.
Explicit CPU offload, bounded overlapping VAE tiles, and bounded attention
slicing are required configuration rather than silent fallback.

## Content-addressed caches

Prompt, embedding, KV, and workflow caches use distinct namespaces. Every key
binds the model revision, adapter SHA-256, input SHA-256, policy SHA-256, and
runtime fingerprint. Model, adapter, input, policy, dtype, or runtime drift is
a miss. Values are independently hashed and stored in a byte-bounded LRU.
Cache hits are optimizations only; they never alter evidence or competition
eligibility.

## Recovery

OOM recovery persists a checkpoint, releases the resident model, reduces the
microbatch or tile, and resumes only the unfinished unit. Kernel recovery
verifies the last committed checkpoint, starts a clean kernel, and restores
RNG, optimizer, and scheduler. Download recovery retains a temporary partial,
resumes with HTTP Range, verifies the expected SHA-256, and only then performs
an atomic rename. Every recovery class is capped at two attempts and cannot
replay successful work.

## Offline and clean-instance reproduction

The offline manifest uses relative non-traversing paths, exact byte sizes,
artifact hashes, a dependency-lock hash, `local_files_only=true`, and
`network_allowed=false`. The clean-instance entrypoint is
`scripts/run_v10_clean_radeon_instance.sh`. It requires a control-plane
container digest, validates the archive checksum before extraction, refuses
broad extraction targets, enables Hugging Face/Transformers/Datasets offline
mode, and runs the complete local suite without `curl`, `wget`, or package
installation.

## Evidence boundary

`evidence/v10/radeon-reproduction-mechanical-fixture.json` proves only these
control mechanics and negative controls. GPU identity/memory, ROCm/HIP/PyTorch,
BF16/FP16/backward/attention/VAE, FLUX/Wan/LTX/SeedVR2/Real-ESRGAN/Qwen3-VL/
Gemma4/hotswap, latency/utilization/I/O/load time, matched baselines, quality
retention, clean-instance execution, archive reproduction, Radeon Report,
performance evidence, and final frozen Radeon Evidence remain open until a
live instance produces content-addressed receipts.
