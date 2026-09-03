# ROCm-native executable robot port

Date: 2026-07-29  
Work package: `WP-ROCM-NATIVE-ROBOT-PORT-005`

## Purpose

This phase turns the static URDF compiler into an executable, AMD-native port
surface. The declarative Genesis file is named `genesis-port-spec.json`; it is
not called an adapter because the JSON does not execute anything. The bundle
also contains a generated `run-genesis-port.py` that consumes the spec and an
explicit external URDF path.

The runtime proof uses the project-owned bimanual 7+7 fixture. It does not copy
or transfer the external Mantis URDF.

## Generated runtime boundary

The generated runner must:

1. verify the external URDF against the compile-time SHA-256;
2. require an explicit `cpu` or `amdgpu` backend;
3. use `gs.amdgpu` without silent fallback for the AMD gate;
4. build the fixed-base robot, map the selected arm joints to distinct Genesis
   degrees of freedom, step a headless scene, and record finite readback;
5. write one fresh exclusive receipt; and
6. expose no controller, motion target, data capture, rendering, training, or
   learned-policy path.

## ROCm tuning evidence

The compiler emits a morphology-aware `rocm-tuning-plan.json`. Its first
measurement family compares one FP32 baseline with supported BF16 and FP16
automatic-mixed-precision candidates on the same Radeon GPU, model weights,
inputs, batch shape, action dimension, and iteration protocol.

Required measurements include inference and training-step latency p50/p95/p99,
throughput, peak allocated memory, finite outputs, maximum absolute difference,
and cosine similarity against FP32. Unsupported precisions are recorded, not
silently replaced.

This is an ACT-shaped synthetic compute microbenchmark. It is not ACT training
or learned-policy inference. A candidate may reach only
`ROCM_TUNING_MEASURED`; it cannot become `AMD_DEPLOYABLE`.

## ACT quality remains authoritative

The existing quality ladder remains unchanged:

- dataset admission before training;
- finite natural training completion with checkpoint/config hashes;
- ordered, bounded, latency-measured open-loop inference;
- G3 at least 6/10 with zero safety failures;
- competitive target 8/10; and
- G4 only after G3 passes.

The existing Mantis ACT result remains 0/10 and not deployable. A faster
microbenchmark never changes that result.

## Current official technical basis

The frozen dated reference snapshot uses:

- [Genesis initialization and explicit `gs.amdgpu` backend](https://genesis-world.readthedocs.io/en/latest/user_guide/configuration/initialization.html);
- [PyTorch HIP semantics and intentional `torch.cuda` API reuse](https://docs.pytorch.org/docs/main/notes/hip.html); and
- [AMD ROCm PyTorch compatibility and mixed-precision support](https://rocm.docs.amd.com/en/docs-7.2.3/compatibility/ml-compatibility/pytorch-compatibility.html).

All performance choices still require measurement on the actual contest
Radeon worker.

## Persistent execution path

The verified execution layout separates fast disposable runtime state from
durable evidence:

- runtime environment: `/workspace/mantis-track3-runtime-wp005` on the ext4
  local SSD mounted at `/workspace`;
- source, package snapshots, manifests, logs, and receipts:
  `/workspace/persistent/mantis-track3` on the durable PVC.

The persistent link resolves to `/persistent`. It is the observed NFS PVC and
must not be described as direct local SSD. A first full-environment install
into the PVC completed only after a prolonged `rpc_wait`; this negative result
freezes SSD-for-runtime/PVC-for-evidence as the operational rule. The phase
neither restarts nor destroys the instance.

## User-provided ROCm/Genesis/SmolVLA flow

The 2026-07-28 Xbotics tutorial confirms the event-baseline chain
ROCm→PyTorch→Genesis→LeRobot→policy training and contributed the NumPy 2.1.2
plus scikit-image ABI repair. It is not an AMD platform specification. Its
`/workspace` persistence statement disagrees with the current portal, and its
reported SmolVLA loss decrease is not closed-loop capability evidence.
SmolVLA remains an optional later backend; ACT and the existing G3 gate remain
authoritative. The review is frozen in
`receipts/rocm-native-robot-port-amd-20260729-v1/official-flow-review.json`.

## Claim boundary

Completion can prove generated fixed-base fixture execution on one current AMD
worker and a bounded same-device precision comparison. It cannot prove a
second real robot port, ACT task accuracy, general AMD performance advantage,
real-robot safety, public asset rights, or submission readiness.
